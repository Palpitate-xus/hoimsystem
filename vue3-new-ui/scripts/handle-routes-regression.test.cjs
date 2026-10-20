/**
 * Resolver contract tests for the actual source, with only dynamic imports
 * replaced by an observable loader. These Node/vm checks do not mount Vue,
 * execute page modules or prove production browser/bundler loading.
 */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

const root = path.resolve(__dirname, '..');
const source = fs.readFileSync(path.join(root, 'src/utils/handleRoutes.js'), 'utf8');
const plain = value => JSON.parse(JSON.stringify(value));

function implementation(load = async specifier => ({ specifier })) {
  const messages = [];
  const context = vm.createContext({
    __load: load,
    module: { exports: {} },
    console: { warn: (...args) => messages.push(['warn', ...args]), error: (...args) => messages.push(['error', ...args]) },
  });
  const transformed = source.replace(/^export (?=function\b)/gm, '').replace(/\bimport\s*\(/g, '__load(');
  new vm.Script(`${transformed}\nmodule.exports = {convertRouter, filterAsyncRoutes};`, { filename: 'actual-handleRoutes.vm.js' }).runInContext(context);
  return { ...context.module.exports, messages };
}

function moduleFile(specifier) {
  if (!specifier.startsWith('@/')) return null;
  const base = path.join(root, 'src', specifier.slice(2));
  return [base, base + '.vue', base + '.js', path.join(base, 'index.vue'), path.join(base, 'index.js')].find(file => fs.existsSync(file) && fs.statSync(file).isFile()) || null;
}

const formats = [
  ['@/views/index/index', '@/views/index/index'],
  ['views/index/index', '@/views/index/index'],
  ['index/index', '@/views/index/index'],
  ['@/views/inpatient/surgery.vue', '@/views/inpatient/surgery.vue'],
  ['views/system/aiManagement.vue', '@/views/system/aiManagement.vue'],
  ['system/aiManagement', '@/views/system/aiManagement'],
  ['/views/index/index.vue', '@/views/index/index.vue'],
  ['./views/index/index.vue', '@/views/index/index.vue'],
];

for (const [component, expected] of formats) {
  test(`actual converter resolves ${component}`, async () => {
    const calls = [];
    const { convertRouter } = implementation(async specifier => { calls.push(specifier); return { specifier }; });
    const [route] = convertRouter([{ path: '/synthetic', component }]);
    assert.equal((await route.component()).specifier, expected);
    assert.deepEqual(calls, [expected]);
    assert.ok(moduleFile(expected), 'the selected business page exists on disk');
  });
}

test('layout sentinels retain their existing imports', async () => {
  const { convertRouter } = implementation();
  for (const [component, expected] of [['Layout', '@/layouts'], ['EmptyLayout', '@/layouts/EmptyLayout']]) {
    const [route] = convertRouter([{ component }]);
    assert.equal((await route.component()).specifier, expected);
    assert.ok(moduleFile(expected));
  }
});

test('an actual rejected page load awaits the original 404 fallback', async () => {
  const calls = [];
  const { convertRouter, messages } = implementation(async specifier => {
    calls.push(specifier);
    if (specifier !== '@/views/404') throw new Error('Synthetic missing page');
    return { specifier };
  });
  const [route] = convertRouter([{ component: 'missing/synthetic-page' }]);
  assert.equal((await route.component()).specifier, '@/views/404');
  assert.deepEqual(calls, ['@/views/missing/synthetic-page', '@/views/404']);
  assert.equal(messages.filter(item => item[0] === 'error').length, 1);
});

test('malformed components use the original parse-failure fallback', async () => {
  const { convertRouter, messages } = implementation();
  for (const component of [123, {}]) {
    assert.equal((await convertRouter([{ component }])[0].component()).specifier, '@/views/404');
  }
  assert.equal(messages.length, 2);
});

test('empty and nested menus retain metadata and remove null children', async () => {
  const { convertRouter } = implementation();
  for (const invalid of [undefined, null, {}, 'not-an-array']) assert.deepEqual(plain(convertRouter(invalid)), []);
  const [route] = convertRouter([null, { path: '/parent', meta: { permissions: ['doctor'] }, component: 'Layout', children: [null, { path: 'child', component: 'views/inpatient/surgery.vue', children: [] }] }]);
  assert.equal(route.children.length, 1);
  assert.equal(Object.hasOwn(route.children[0], 'children'), false);
  assert.deepEqual(plain(route.meta), { permissions: ['doctor'] });
  assert.equal((await route.children[0].component()).specifier, '@/views/inpatient/surgery.vue');
});

test('all actual mock menu strings preserve loading or their existing 404 fallback', async t => {
  const menu = require(path.join(root, 'mock/controller/router.js'));
  const original = menu.find(item => item.url === '/menu/navigate').response().data;
  const expected = [];
  function collect(rows) { for (const row of rows) { if (row.component) expected.push(row.component); if (row.children) collect(row.children); } }
  collect(original);
  let fallbackCount = 0;
  const { convertRouter } = implementation(async specifier => {
    if (!moduleFile(specifier)) throw new Error('No matching page in current repository');
    return { specifier };
  });
  const converted = convertRouter(plain(original));
  const actual = [];
  async function inspect(rows) { for (const row of rows) { if (row.component) actual.push(await row.component()); if (row.children) await inspect(row.children); } }
  await inspect(converted);
  assert.equal(actual.length, expected.length);
  for (let index = 0; index < expected.length; index++) {
    const specifier = expected[index] === 'Layout' ? '@/layouts' : expected[index] === 'EmptyLayout' ? '@/layouts/EmptyLayout' : expected[index];
    assert.ok(specifier.startsWith('@/views/') || specifier.startsWith('@/layouts'));
    const resolved = moduleFile(specifier) ? specifier : '@/views/404';
    if (resolved !== specifier) fallbackCount++;
    assert.equal(actual[index].specifier, resolved);
  }
  t.diagnostic(`${expected.length} actual mock component strings; ${fallbackCount} already missing targets use 404, not a claim that those pages exist`);
});

function staticBusinessRoutes() {
  const text = fs.readFileSync(path.join(root, 'src/router/index.js'), 'utf8').split('\nconst router = createRouter(')[0];
  const context = vm.createContext({ module: { exports: {} }, Layout: {}, EmptyLayout: {} });
  const declarations = text.replace(/^import .*;\r?\n/gm, '').replace(/^export (?=const\b)/gm, '');
  new vm.Script(`${declarations}\nmodule.exports = {asyncRoutes};`, { filename: 'actual-static-routes.vm.js' }).runInContext(context);
  return context.module.exports.asyncRoutes;
}

function routeKeys(rows) {
  const result = [];
  function visit(items, parent = '') { for (const item of items) { const key = parent + '/' + item.path; result.push(key); if (item.children) visit(item.children, key); } }
  visit(rows);
  return result;
}

function permittedKeys(rows, roles, ancestors = [], parent = '') {
  const result = [];
  for (const item of rows) {
    const restrictions = [...ancestors, item.meta?.permissions].filter(Boolean);
    const key = parent + '/' + item.path;
    if (restrictions.every(list => roles.some(role => list.includes(role)))) result.push(key);
    if (item.children) result.push(...permittedKeys(item.children, roles, restrictions, key));
  }
  return result;
}

test('original role filtering remains the intersection of real ancestor/child menus', () => {
  const { filterAsyncRoutes } = implementation();
  const routes = staticBusinessRoutes();
  const original = JSON.stringify(routes);
  for (const roles of [[], ['doctor'], ['patient'], ['admin'], ['director'], ['super_admin'], ['nurse', 'doctor'], ['unknown_role']]) {
    assert.deepEqual(routeKeys(filterAsyncRoutes(routes, roles)), permittedKeys(routes, roles));
  }
  assert.equal(JSON.stringify(routes), original, 'filtering must not mutate the original menu');
  for (const invalid of [null, undefined, {}, 'doctor']) assert.deepEqual(plain(filterAsyncRoutes(routes, invalid)), []);
  assert.deepEqual(plain(filterAsyncRoutes(null, ['doctor'])), []);
  const doctor = routeKeys(filterAsyncRoutes(routes, ['doctor']));
  assert.ok(doctor.includes('//ai/workbench'));
  assert.ok(!doctor.includes('//ai/manage'));
});

