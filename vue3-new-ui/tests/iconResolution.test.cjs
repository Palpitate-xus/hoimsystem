const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { test } = require('node:test');
const babel = require('@babel/core');
const { parse } = require('@babel/parser');
const vue = require('vue');
const { renderToString } = require('@vue/server-renderer');
const installedIcons = require('@element-plus/icons-vue');

const root = path.resolve(__dirname, '..');
const resolverSource = fs.readFileSync(path.join(root, 'src/utils/icons.js'), 'utf8');
const compiledResolver = babel.transformSync(resolverSource, {
  configFile: false,
  babelrc: false,
  presets: [[require.resolve('@babel/preset-env'), { targets: { node: 'current' } }]],
}).code;

function loadResolver(polluted = false) {
  const moduleValue = { exports: {} };
  const context = vm.createContext({
    module: moduleValue,
    exports: moduleValue.exports,
    require(name) {
      assert.equal(name, '@element-plus/icons-vue', 'resolver must only load its explicit icon dependency');
      return installedIcons;
    },
  });
  if (polluted) vm.runInContext('Object.prototype.injectedIcon = { name: "WrongInheritedIcon" };', context);
  vm.runInContext(compiledResolver, context, { filename: 'src/utils/icons.js' });
  return moduleValue.exports.resolveIcon;
}

const resolveIcon = loadResolver();
const resolverAst = parse(resolverSource, { sourceType: 'module' });
const iconImports = resolverAst.program.body.filter(node => node.type === 'ImportDeclaration' && node.source.value === '@element-plus/icons-vue');
const declaredIconNames = iconImports.flatMap(node => node.specifiers.map(specifier => {
  assert.equal(specifier.type, 'ImportSpecifier', 'icons use explicit named imports rather than a full-library namespace');
  return specifier.imported.name;
}));
const routerAst = parse(fs.readFileSync(path.join(root, 'src/router/index.js'), 'utf8'), { sourceType: 'module' });
const property = (node, name) => node?.type === 'ObjectExpression'
  ? node.properties.find(item => item.type === 'ObjectProperty' && (item.key.name || item.key.value) === name)?.value
  : undefined;

// Read the route data from syntax only. Router imports and lazy screens never run.
const routeArrays = new Map();
for (const statement of routerAst.program.body) {
  const declaration = statement.type === 'ExportNamedDeclaration' ? statement.declaration : statement;
  if (declaration?.type !== 'VariableDeclaration') continue;
  for (const item of declaration.declarations) {
    if (['constantRoutes', 'asyncRoutes'].includes(item.id.name)) {
      assert.equal(item.init.type, 'ArrayExpression', 'route arrays remain statically inspectable');
      routeArrays.set(item.id.name, item.init.elements);
    }
  }
}

const routeIcons = [];
function collectRouteIcons(routes, parentPath = '') {
  for (const route of routes) {
    assert.equal(route.type, 'ObjectExpression', 'route metadata must be explicit');
    const routePath = property(route, 'path');
    assert.equal(routePath?.type, 'StringLiteral');
    const fullPath = routePath.value.startsWith('/') ? routePath.value : `${parentPath}/${routePath.value}`;
    const meta = property(route, 'meta');
    const icon = property(meta, 'icon');
    if (property(meta, 'title')) {
      assert.equal(icon?.type, 'StringLiteral', `${fullPath}: every titled page or module needs a static icon`);
      assert.ok(icon.value.trim(), `${fullPath}: titled routes cannot have empty icons`);
    }
    if (icon) {
      assert.equal(icon.type, 'StringLiteral', `${fullPath} icon must be a static name`);
      routeIcons.push({ path: fullPath, name: icon.value });
    }
    const children = property(route, 'children');
    if (children) {
      assert.equal(children.type, 'ArrayExpression');
      collectRouteIcons(children.elements, fullPath === '/' ? '' : fullPath);
    }
  }
}
for (const routes of routeArrays.values()) collectRouteIcons(routes);

test('all configured route icons resolve to their exact installed SVG component', () => {
  assert.equal(routeArrays.size, 2);
  assert.ok(routeIcons.length > 0, 'configured routes contain menu icons');
  for (const route of routeIcons) {
    assert.ok(Object.hasOwn(installedIcons, route.name), `${route.path}: unknown icon ${route.name}`);
    assert.equal(resolveIcon(route.name), installedIcons[route.name], `${route.path}: ${route.name} must not fall back`);
  }
});

test('visible top-level business modules use distinct, resolved icons', () => {
  const modules = routeArrays.get('asyncRoutes').filter(route => property(route, 'hidden')?.value !== true && property(route, 'meta'));
  assert.ok(modules.length >= 16, 'include every business module');
  const components = modules.map(route => {
    const name = property(property(route, 'meta'), 'icon')?.value;
    assert.ok(name, `${property(route, 'path').value} needs a module icon`);
    const component = resolveIcon(name);
    assert.notEqual(component, installedIcons.QuestionFilled);
    assert.notEqual(component, installedIcons.More);
    return component;
  });
  assert.equal(new Set(components).size, modules.length, 'module icons must remain distinguishable');
});

test('configured PascalCase names, kebab-case names and FA arrays share the same identity', () => {
  const names = new Set([...declaredIconNames, ...routeIcons.map(route => route.name)]);
  for (const name of names) {
    const kebab = name.replace(/([a-z0-9])([A-Z])/g, '$1-$2').toLowerCase();
    for (const input of [name, kebab, kebab.replaceAll('-', '_'), ` ${kebab} `, ['fas', kebab]]) {
      assert.equal(resolveIcon(input), installedIcons[name], `${name} must retain its SVG across supported representations`);
    }
  }
});

test('canonical Element Plus names take precedence when a historical alias has the same spelling', () => {
  for (const name of ['Folder', 'folder', 'folder-open', 'folder_open', ['fas', 'folder']]) {
    // The former migration mapped "folder" to FolderOpened and "folder-open" to Folder.
    // Modern canonical names retain their own exact component; unambiguous aliases still work.
    assert.equal(resolveIcon(name), installedIcons.Folder, String(name));
  }
  assert.equal(resolveIcon('FolderOpened'), installedIcons.FolderOpened);
  assert.equal(resolveIcon('folder-opened'), installedIcons.FolderOpened);
});

test('historical icon names preserve the expected business/action meaning', () => {
  const cases = [
    ['home', 'HomeFilled'], ['user-alt', 'User'], ['mobile-alt', 'Cellphone'],
    ['info-circle', 'InfoFilled'], ['code-branch', 'Share'], ['palette', 'Brush'],
    ['sync-alt', 'Refresh'], ['expand-arrows-alt', 'FullScreen'], ['compress-arrows-alt', 'ScaleToOriginal'],
    ['box-open', 'Box'], ['chart-line', 'TrendCharts'], ['chart-pie', 'PieChart'],
    ['chart-bar', 'Histogram'], ['file-alt', 'Document'], ['folder-plus', 'FolderAdd'],
    ['money-bill', 'Money'], ['dollar-sign', 'Money'], ['comments', 'ChatDotRound'],
    ['times-circle', 'CircleCloseFilled'], ['bars', 'Menu'], ['arrow-alt-circle-left', 'Back'],
    ['arrow-alt-circle-right', 'Right'], ['ban', 'Remove'], ['sign-out-alt', 'SwitchButton'],
    ['github', 'Platform'], ['vuejs', 'ElementPlus'],
    ['information-line', 'InfoFilled'], ['send-plane-2-line', 'Promotion'], ['arrows-alt', 'FullScreen'],
  ];
  for (const [legacyName, expectedName] of cases) {
    assert.equal(resolveIcon(legacyName), installedIcons[expectedName], legacyName);
    assert.equal(resolveIcon(['fas', legacyName]), installedIcons[expectedName], `FA array: ${legacyName}`);
  }
});

test('unknown, malformed and inherited names render a stable question icon', () => {
  const poisonedResolver = loadResolver(true);
  const invalid = [
    undefined, null, false, true, 0, 123, {}, { name: 'User' }, new String('User'),
    [], ['fas'], ['fas', null], ['fas', {}], '', 'unknown-icon',
    '__proto__', 'constructor', 'toString', 'hasOwnProperty', 'injectedIcon',
  ];
  for (const input of invalid) {
    assert.equal(resolveIcon(input), installedIcons.QuestionFilled, `unsupported input ${String(input)}`);
    assert.equal(poisonedResolver(input), installedIcons.QuestionFilled, `inherited input ${String(input)}`);
  }
  assert.equal(poisonedResolver('User'), installedIcons.User, 'inherited keys cannot replace valid icons');
});

test('each distinct route icon and the unknown fallback actually renders SVG geometry', async () => {
  for (const name of [...new Set(routeIcons.map(route => route.name)), 'unknown-icon']) {
    const markup = await renderToString(vue.createSSRApp({
      render: () => vue.h(resolveIcon(name), { class: 'resolved-icon', 'aria-label': name }),
    }));
    assert.match(markup, /^<svg\b/, name);
    assert.match(markup, /viewBox="0 0 1024 1024"/, name);
    assert.match(markup, /<path\b[^>]*\bd="[^\"]+"/, `${name} needs visible geometry`);
    assert.match(markup, /class="resolved-icon"/, `${name} forwards caller attributes`);
    assert.match(markup, new RegExp(`aria-label="${name}"`));
  }
});
