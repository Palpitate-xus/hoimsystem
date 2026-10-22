'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const os = require('node:os');
const { analyzeFile, sourceFiles, styleClosure, generate, resolveImport, OUTPUT } = require('./generate-element-plus-style-entry.cjs');
const ROOT = path.resolve(__dirname, '..');

for (const [name, source, expected] of [
  ['HTML template and service directives', '<template><el-dialog><ElTable><el-table-column/><el-input v-loading="busy"/></ElTable></el-dialog></template>', ['dialog', 'input', 'loading', 'table', 'table-column']],
  ['four services and named aliases', '<script>import {ElLoading as L,ElMessage,ElMessageBox as Box,ElNotification} from "element-plus";</script>', ['loading', 'message', 'message-box', 'notification']],
  ['JSX and static render aliases', 'import {h as render,resolveComponent as component} from "vue"; render("el-alert");component("ElCheckbox");const jsx=<ElRadio/>;', ['alert', 'checkbox', 'radio']],
  ['direct named component render', 'import {ElButton as B} from "element-plus";import {h as render} from "vue";render(B);', ['button']],
  ['static component selector', '<template><component :is="\'ElTransfer\'"/><component is="el-tree"/></template>', ['transfer', 'tree']],
  ['script-only reexport', 'export {ElUpload,ElDatePicker} from "element-plus";', ['date-picker', 'upload']],
]) test(name, () => assert.deepEqual(analyzeFile(name.endsWith('render') || name.includes('JSX') || name.includes('reexport') ? 'fixture.js' : 'fixture.vue', source).requirements, expected));

test('deep component and direct CSS imports are preserved', () => {
  const result = analyzeFile('fixture.js', 'import "element-plus/es/components/table/style/css";import "element-plus/theme-chalk/el-transfer.css";');
  assert.deepEqual(result.requirements, ['table']);
  assert.deepEqual(result.explicitStyles, ['element-plus/es/components/table/style/css', 'element-plus/theme-chalk/el-transfer.css']);
  const styles = styleClosure(result.requirements, result.explicitStyles);
  assert.ok(styles.css['element-plus/theme-chalk/el-transfer.css']);
  assert.ok(styles.css['element-plus/theme-chalk/el-table.css']);
});

test('real installed child dependency closure includes select, tree and checkbox styles', () => {
  const result = styleClosure(['tree-select']);
  for (const name of ['base.css', 'el-tree-select.css', 'el-select.css', 'el-tree.css', 'el-checkbox.css', 'el-scrollbar.css', 'el-option.css']) assert.ok(result.css['element-plus/theme-chalk/' + name], name);
  assert.equal(result.entryImports[0], 'element-plus/es/components/base/style/css');
  assert.ok(result.styleModules['element-plus/es/components/select/style/css.mjs']);
  assert.ok(!result.css['element-plus/theme-chalk/el-transfer.css']);
});

for (const [name, filename, source, error] of [
  ['unknown dynamic template', 'fixture.vue', '<template><component :is="chosen"/></template>', /unreviewed dynamic component/],
  ['unknown dynamic render', 'fixture.js', 'import {h} from "vue";h(chosen);', /unreviewed dynamic component/],
  ['namespace import', 'fixture.js', 'import * as EP from "element-plus";', /whole Element Plus namespace/],
  ['unclassified package entry', 'fixture.js', 'import {ElButton} from "element-plus/es";', /unclassified Element Plus entry/],
  ['CommonJS dynamic namespace', 'fixture.js', 'require("element-plus");', /CommonJS Element Plus require/],
  ['default whole install', 'fixture.js', 'import EP from "element-plus";', /whole Element Plus namespace/],
  ['lazy component import', 'fixture.js', 'import("element-plus/es/components/calendar");', /lazy Element Plus import/],
  ['external script', 'fixture.vue', '<script src="./unscanned.js"></script>', /external\/non-JavaScript script/],
  ['external template', 'fixture.vue', '<template src="./unscanned.html"></template>', /external\/non-HTML template/],
  ['Sass library import', 'fixture.js', 'import "element-plus/theme-chalk/src/index.scss";', /Sass library import/],
]) test(name + ' fails closed', () => assert.throws(() => analyzeFile(filename, source), error));

test('reviewed current dynamic selector cannot change its script silently', () => {
  const file = 'src/layouts/components/VabSide/components/VabSideItem.vue';
  const source = fs.readFileSync(path.join(ROOT, file), 'utf8');
  const current = analyzeFile(file, source);
  assert.ok(current.dynamics.some(value => value.endsWith('|template|menuComponent')));
  assert.throws(() => analyzeFile(file, source.replace('return "VabMenuItem";', 'return "ElCalendar";')), /unreviewed dynamic component/);
});

test('unknown installed component and path escape are refused', () => {
  assert.throws(() => styleClosure(['unknown-widget']), /No actual installed style contract/);
  assert.throws(() => styleClosure(['../button']), /Invalid component style name/);
  assert.throws(() => styleClosure([], [require.resolve('vue')]), /escaped Element Plus/);
});

test('a library style module cannot execute code during generation', () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'hoim-element-style-test-'));
  try {
    const ep = path.join(root, 'node_modules/element-plus');
    fs.mkdirSync(path.join(ep, 'es/components/base/style'), { recursive: true });
    fs.writeFileSync(path.join(ep, 'package.json'), JSON.stringify({ name: 'element-plus', version: 'synthetic', main: 'index.js' }));
    fs.writeFileSync(path.join(ep, 'es/components/base/style/css.mjs'), 'throw new Error("must not execute");');
    assert.throws(() => styleClosure([], [], root), /Unexpected executable library style module/);
  } finally { fs.rmSync(root, { recursive: true, force: true }); }
});

test('current complete source scan preserves each literal el tag independently', () => {
  const result = generate();
  assert.equal(fs.readFileSync(path.join(ROOT, OUTPUT), 'utf8'), result.entry);
  const selected = new Set(result.requirements);
  for (const file of sourceFiles()) {
    const raw = fs.readFileSync(file, 'utf8');
    for (const match of raw.matchAll(/<(el-[a-z0-9-]+)(?=[\s/>])/g)) assert.ok(selected.has(match[1].slice(3)), path.relative(ROOT, file) + ':' + match[1]);
  }
  for (const service of ['loading', 'message', 'message-box', 'notification']) assert.ok(selected.has(service));
  assert.ok(result.analysis.some(value => value.filename.startsWith('layouts/')));
  assert.ok(result.rawCssSavings > 0 && result.rawCssSavings < 80000, 'Current audited full usage does not support an 80KB saving claim');
  for (const name of result.closure.entryImports) assert.ok(resolveImport(ROOT, name), name);
  assert.ok(result.entry.indexOf('/base/style/css') < result.entry.indexOf('/alert/style/css'));
});
