const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const babel = require('@babel/parser');
const sfc = require('@vue/compiler-sfc');
const root = path.resolve(__dirname, '..');
const backend = path.resolve(root, '../fastapi_be');
const mapping = JSON.parse(fs.readFileSync(path.join(backend, 'app/access_route_map.json')));
const matrix = JSON.parse(fs.readFileSync(path.join(backend, 'rbac_matrix.json')));
const property = (node, key) => node?.properties?.find(item => item.key?.name === key || item.key?.value === key)?.value;
function walk(node, visit) {
  if (!node || typeof node !== 'object') return;
  visit(node);
  for (const [key, value] of Object.entries(node)) {
    if (['loc', 'extra', 'tokens', 'comments'].includes(key)) continue;
    if (Array.isArray(value)) value.forEach(child => walk(child, visit));
    else if (value && typeof value === 'object') walk(value, visit);
  }
}
function parse(file) {
  let source = fs.readFileSync(file, 'utf8');
  if (file.endsWith('.vue')) {
    const { descriptor, errors } = sfc.parse(source, { filename: file });
    assert.equal(errors.length, 0, file);
    source = [descriptor.script?.content, descriptor.scriptSetup?.content].filter(Boolean).join('\n');
  }
  return babel.parse(source, { sourceType: 'module', plugins: ['typescript'] });
}
function literal(node, constants = {}, seen = new Set()) {
  if (node?.type === 'StringLiteral') return node.value;
  if (node?.type === 'Identifier' && !seen.has(node.name) && constants[node.name]) return literal(constants[node.name], constants, new Set([...seen, node.name]));
  if (node?.type === 'TemplateLiteral') return node.quasis.map((part, i) => part.value.cooked + (i < node.expressions.length ? literal(node.expressions[i], constants, seen) : '')).join('');
  return '*';
}
function sourceFile(specifier, importer) {
  const candidate = specifier.startsWith('@/') ? path.join(root, 'src', specifier.slice(2)) : path.resolve(path.dirname(importer), specifier);
  return [candidate, `${candidate}.vue`, `${candidate}.js`, path.join(candidate, 'index.vue'), path.join(candidate, 'index.js')].find(file => fs.existsSync(file) && fs.statSync(file).isFile());
}
const routes = [];
walk(parse(path.join(root, 'src/router/index.js')), node => {
  if (node.type !== 'ObjectExpression' || !property(node, 'meta')) return;
  const name = literal(property(node, 'name')), title = literal(property(property(node, 'meta'), 'title'));
  if (name === '*' || title === '*') return;
  let component;
  walk(property(node, 'component'), value => { if (value.type === 'CallExpression' && value.callee.type === 'Import') component = literal(value.arguments[0]); });
  routes.push({ name, title, component, parent: !!property(node, 'children') });
});
// Read only the imported API functions and child components. Following the global
// router/store graph would incorrectly count unrelated pages as evidence.
function apiEvidence(page, requiredCodes) {
  const result = [], visited = new Set();
  function visit(file, importedNames) {
    const key = file + ':' + (importedNames || []).join(',');
    if (visited.has(key)) return;
    visited.add(key);
    const ast = parse(file), constants = {};
    walk(ast, node => { if (node.type === 'VariableDeclarator' && node.id.type === 'Identifier') constants[node.id.name] = node.init; });
    const requestCalls = node => walk(node, value => {
      if (value.type !== 'CallExpression' || value.callee.name !== 'request' || value.arguments[0]?.type !== 'ObjectExpression') return;
      const options = value.arguments[0], url = literal(property(options, 'url'), constants), methodNode = property(options, 'method');
      if (url === '*') return;
      const method = methodNode ? literal(methodNode, constants).toUpperCase() : 'GET';
      result.push({ method, path: url.startsWith('/api/') ? url : '/api/' + url.replace(/^\//, ''), file });
    });
    if (importedNames) {
      walk(ast, node => { if (node.type === 'FunctionDeclaration' && importedNames.includes(node.id?.name) || node.type === 'VariableDeclarator' && importedNames.includes(node.id?.name)) requestCalls(node); });
      return;
    }
    requestCalls(ast);
    walk(ast, node => {
      if (node.type !== 'ImportDeclaration') return;
      const specifier = node.source.value;
      if (specifier.startsWith('@/api/')) {
        const target = sourceFile(specifier, file);
        if (target) visit(target, node.specifiers.map(item => item.imported?.name || '*'));
      }
    });
    if (requiredCodes.every(code => supports(result, code))) return;
    walk(ast, node => {
      if (node.type !== 'ImportDeclaration') return;
      const specifier = node.source.value;
      if (specifier.startsWith('@/components/') || specifier.startsWith('.') && /\.(vue|js)$/.test(specifier)) {
        const target = sourceFile(specifier, file);
        if (target && !requiredCodes.every(code => supports(result, code))) visit(target);
      }
    });
  }
  visit(page);
  return result;
}
function supports(evidence, code) {
  const separator = code.indexOf(' '), method = code.slice(0, separator), endpoint = code.slice(separator + 1);
  return evidence.some(item => item.method === method && new RegExp('^' + item.path.split('*').map(part => part.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')).join('[^/]+') + '$').test(endpoint));
}
const basicPages = ['Account', 'Index', 'HtmlEditor', 'Error401', 'Error404'];
test('backend route map covers every actual titled route and keeps only basic local pages ungated', () => {
  assert.equal(routes.length, 144);
  assert.deepEqual(Object.keys(mapping).sort(), routes.map(route => route.name).sort());
  for (const route of routes) {
    assert.ok(Array.isArray(mapping[route.name]), route.name);
    assert.equal(new Set(mapping[route.name]).size, mapping[route.name].length, `${route.name}: duplicate permissions`);
    if (route.parent || basicPages.includes(route.name)) assert.deepEqual(mapping[route.name], [], route.name);
    else assert.ok(mapping[route.name].length, `${route.name}: business page lacks a gate`);
  }
});
test('every route permission exists in the real backend METHOD + path matrix', () => {
  const codes = new Set(matrix.map(row => `${row.method} ${row.path}`));
  for (const [name, permissions] of Object.entries(mapping)) for (const code of permissions) assert.ok(codes.has(code), `${name}: unknown ${code}`);
});
test('every mapped permission has AST evidence in the actual page, imported API function or child component', () => {
  for (const route of routes.filter(row => mapping[row.name].length)) {
    const evidence = apiEvidence(sourceFile(route.component, path.join(root, 'src/router/index.js')), mapping[route.name]);
    for (const code of mapping[route.name]) assert.ok(supports(evidence, code), `${route.name}: ${code} is not called by its source`);
  }
});
test('primary business lists remain the gate when auxiliary patient and department directories are allowed', () => {
  const cases = {
    DoctorManagement: 'doctorManagement/getList', DepartmentManagement: 'departmentManagement/getList',
    InventoryAdjustment: 'pharmacy/inventoryAdjustment/list', DrugDamage: 'pharmacy/drugDamage/list',
    SpecialDrug: 'specialDrug/list', PrescriptionReview: 'pharmacy/reviewList',
    EmergencyRescue: 'emergency/rescue/list', EmergencyObservation: 'emergency/observation/list',
    EmergencyMedicalRecord: 'emergency/medicalRecord/list', NursingAssessment: 'nursingAssessment/list',
    NursingPlan: 'nursingPlan/list', CriticalCareRecord: 'criticalCareRecord/list',
    MedicalRecordHome: 'medicalRecordHome/list', MedicalRecordArchive: 'medicalRecordArchive/list',
    MedicalRecordHomeQuality: 'medicalRecordHomeQuality/list',
  };
  for (const [name, endpoint] of Object.entries(cases)) {
    assert.ok(mapping[name].includes(`GET /api/${endpoint}`), name);
    for (const auxiliary of ['GET /api/patientManagement/getList', 'GET /api/departmentManagement/getList', 'GET /api/admission/getList']) if (`GET /api/${endpoint}` !== auxiliary) assert.ok(!mapping[name].includes(auxiliary), `${name}: auxiliary endpoint would keep a denied main page visible`);
  }
  assert.deepEqual(mapping.Permission, ['GET /api/access/catalog']);
  assert.deepEqual(mapping.Triage, ['POST /api/triage/suggest']);
  assert.deepEqual(mapping.Review, ['POST /api/review/create']);
});
