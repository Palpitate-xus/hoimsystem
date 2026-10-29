const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const test = require('node:test');
const root = path.resolve(__dirname, '..');
const plain = value => JSON.parse(JSON.stringify(value));
const snapshot = (version = '1', names = ['MedicalRecord']) => ({ version, permission_codes: ['GET:/medicalRecord/getList'], denied_route_names: names, data_scope: 'existing' });
const deferred = () => { let resolve; const promise = new Promise(done => { resolve = done; }); return { promise, resolve }; };
function userModule(overrides = {}) {
  const source = fs.readFileSync(path.join(root, 'src/store/modules/user.js'), 'utf8').replace(/^import[\s\S]*?;\r?\n/gm, '').replace('export default ', 'module.exports = ');
  const context = vm.createContext({ module: { exports: {} }, getAccessToken: () => 'synthetic-token', setAccessToken() {}, removeAccessToken() {}, resetRouter() {}, tokenName: 'accesstoken', ElMessage: { error() {} }, getUserInfo: async () => ({ data: { permissions: ['doctor'], username: 'synthetic-doctor', avatar: '', authorization: snapshot() } }), getMyAccess: async () => ({ data: snapshot('2') }), ...overrides });
  new vm.Script(source).runInContext(context);
  const module = context.module.exports, state = module.state(), commit = (name, value) => module.mutations[name](state, value);
  return { ...module, state, commit, context: { state, commit } };
}
test('userInfo retains legacy role identity separately from effective API permissions', async () => {
  const user = userModule();
  assert.deepEqual(plain(await user.actions.getUserInfo(user.context)), ['doctor']);
  assert.deepEqual(plain(user.getters.permissions(user.state)), ['doctor']);
  assert.deepEqual(plain(user.getters.authorization(user.state)), snapshot());
  const legacy = userModule({ getUserInfo: async () => ({ data: { permissions: ['patient'], username: 'synthetic-patient' } }) });
  assert.deepEqual(plain(await legacy.actions.getUserInfo(legacy.context)), ['patient']);
  assert.equal(legacy.state.authorization, null);
});
test('identity mutations and logout remove a previous authorization snapshot', () => {
  for (const [mutation, value] of [['setAccessToken', 'another-token'], ['setUsername', 'another-user'], ['setPermissions', ['nurse']]]) {
    const user = userModule(); user.commit('setAuthorization', snapshot()); user.commit(mutation, value);
    assert.equal(user.state.authorization, null, mutation);
  }
  const user = userModule(); user.commit('setAuthorization', snapshot()); user.actions.resetAccessToken(user.context);
  assert.equal(user.state.authorization, null); assert.equal(user.state.accessToken, ''); assert.equal(user.state.username, '');
});
test('a delayed permission refresh cannot attach a previous token or user authorization', async () => {
  for (const [mutation, value] of [['setAccessToken', 'another-token'], ['setUsername', 'another-user']]) {
    const pending = deferred(), user = userModule({ getMyAccess: () => pending.promise });
    const refreshing = user.actions.refreshAuthorization(user.context);
    user.commit(mutation, value); pending.resolve({ data: snapshot('old') });
    assert.equal(await refreshing, null); assert.equal(user.state.authorization, null);
  }
  const user = userModule(); await user.actions.refreshAuthorization(user.context); assert.equal(user.state.authorization.version, '2');
});
test('late userInfo and malformed authorization cannot restore an old session', async () => {
  const pending = deferred(), user = userModule({ getUserInfo: () => pending.promise });
  const loading = user.actions.getUserInfo(user.context); user.commit('setAccessToken', 'replacement');
  pending.resolve({ data: { username: 'old', permissions: ['admin'], authorization: snapshot() } });
  assert.equal(await loading, false); assert.equal(user.state.username, '');
  for (const value of [{}, { ...snapshot(), permission_codes: 'admin' }, { ...snapshot(), denied_route_names: [null] }, { ...snapshot(), data_scope: 'all' }]) assert.throws(() => user.commit('setAuthorization', value), /权限数据格式错误/);
});
function guardHarness({ roles = ['doctor'], authorization = snapshot(), pendingRefresh } = {}) {
  const callbacks = new Map(), nexts = [], dispatches = [], added = [], redirects = [];
  const state = { token: 'synthetic-token', roles, authorization };
  const getters = {};
  Object.defineProperties(getters, { 'user/accessToken': { get: () => state.token }, 'user/permissions': { get: () => state.roles }, 'user/authorization': { get: () => state.authorization } });
  const store = { getters, async dispatch(name) { dispatches.push(name); if (name === 'user/refreshAuthorization') { state.authorization = await (pendingRefresh || Promise.resolve(snapshot('2'))); return state.authorization; } if (name === 'user/getUserInfo') { state.roles = ['doctor']; return state.roles; } if (name.startsWith('routes/')) return [{ name: 'Registered' }]; } };
  const router = { currentRoute: { value: { name: 'MedicalRecord' } }, beforeEach(fn) { this.before = fn; }, afterEach() {}, addRoute(value) { added.push(value); }, resolve() { return { name: 'MedicalRecord' }; }, async replace(value) { redirects.push(value); } };
  const eventBus = { on(name, fn) { callbacks.set(name, fn); } };
  const source = fs.readFileSync(path.join(root, 'src/config/permission.js'), 'utf8').replace(/^import[\s\S]*?;\r?\n/gm, '');
  new vm.Script(source).runInContext(vm.createContext({ router, store, eventBus, VabProgress: { configure() {}, start() {}, done() {} }, getPageTitle: value => value, authentication: 'intelligence', loginInterception: true, progressBar: false, recordRoute: true, routesWhiteList: ['/login', '/401'], document: {} }));
  return { state, callbacks, nexts, dispatches, added, redirects, navigate: to => router.before({ path: '/medicalRecord', fullPath: '/medicalRecord', meta: {}, matched: [], ...to }, {}, value => nexts.push(value)) };
}
test('the actual router guard blocks denied registered routes and denied ancestors', async () => {
  const guard = guardHarness(); await guard.navigate({ name: 'MedicalRecord' }); assert.equal(guard.nexts.pop(), '/401');
  await guard.navigate({ name: 'OtherChild', matched: [{ name: 'MedicalRecord' }] }); assert.equal(guard.nexts.pop(), '/401');
  await guard.navigate({ name: 'Allowed' }); assert.equal(guard.nexts.pop(), undefined);
  const legacy = guardHarness({ authorization: null }); await legacy.navigate({ name: 'MedicalRecord' }); assert.equal(legacy.nexts.pop(), undefined);
  const initial = guardHarness({ roles: [] }); await initial.navigate({ name: undefined }); assert.equal(initial.nexts.pop(), '/401'); assert.equal(initial.added.length, 1);
});
test('403 and access policy SSE coalesce a snapshot refresh without replaying the original request', async () => {
  const pending = deferred(), guard = guardHarness({ pendingRefresh: pending.promise });
  const first = guard.callbacks.get('access-denied')();
  const second = guard.callbacks.get('access-denied')();
  guard.callbacks.get('clinical-event')({ type: 'access.policy_changed' });
  assert.equal(first, second); assert.deepEqual(guard.dispatches, ['user/refreshAuthorization']);
  pending.resolve(snapshot('3')); await first;
  assert.deepEqual(guard.dispatches, ['user/refreshAuthorization', 'routes/setRoutes']);
  assert.deepEqual(guard.redirects, ['/401']); assert.equal(guard.state.token, 'synthetic-token');
});
test('an authorization refresh from a replaced token never updates routes', async () => {
  const pending = deferred(), guard = guardHarness({ pendingRefresh: pending.promise });
  const refreshing = guard.callbacks.get('access-denied')(); guard.state.token = 'replacement'; pending.resolve(snapshot('old')); await refreshing;
  assert.deepEqual(guard.dispatches, ['user/refreshAuthorization']); assert.deepEqual(guard.redirects, []);
});

test('route store filters visible menus by the snapshot while guarded route names remain resolvable', async () => {
  const routes = [{ name: 'Clinical', path: '/clinical', meta: { permissions: ['doctor'] }, children: [{ name: 'Read', path: 'read' }, { name: 'Write', path: 'write' }] }];
  const context = vm.createContext({ module: { exports: {} }, asyncRoutes: routes, constantRoutes: [], console });
  const helpers = fs.readFileSync(path.join(root, 'src/utils/handleRoutes.js'), 'utf8').replace(/^export (?=function\b)/gm, '');
  new vm.Script(helpers).runInContext(context);
  const source = fs.readFileSync(path.join(root, 'src/store/modules/routes.js'), 'utf8').replace(/^import[^\n]+\n/gm, '').replace('export default ', 'module.exports = ');
  new vm.Script(source).runInContext(context);
  const module = context.module.exports, state = module.state(), rootGetters = { 'user/authorization': snapshot('1', ['Write']) };
  const registered = await module.actions.setRoutes({ rootGetters, commit: (name, value) => module.mutations[name](state, value) }, ['doctor']);
  assert.deepEqual(plain(state.routes[0].children).map(item => item.name), ['Read']);
  assert.deepEqual(plain(registered[0].children).map(item => item.name), ['Read', 'Write']);
  assert.deepEqual(routes[0].children.map(item => item.name), ['Read', 'Write']);
});

test('legacy role-only sessions do not start a new authorization transport on a denied request', () => {
  const guard = guardHarness({ authorization: null });
  assert.equal(guard.callbacks.get('access-denied')(), undefined);
  guard.callbacks.get('clinical-event')({ type: 'access.policy_changed' });
  assert.deepEqual(guard.dispatches, []);
});

test('an access-denied notification from a previous stream token cannot refresh a replacement login', () => {
  const guard = guardHarness();
  assert.equal(guard.callbacks.get('access-denied')({ token: 'stale-stream-token', status: 403 }), undefined);
  assert.deepEqual(guard.dispatches, []);
});
