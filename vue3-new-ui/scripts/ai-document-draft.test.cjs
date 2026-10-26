const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const Module = require('node:module');
const { transformSync } = require('@babel/core');
const file = path.resolve(__dirname, '../src/utils/aiDocumentDraft.js');
const loaded = new Module(file, module);
loaded.paths = module.paths;
loaded._compile(transformSync(fs.readFileSync(file, 'utf8'), {
  configFile: false, babelrc: false,
  presets: [[require.resolve('@babel/preset-env'), { targets: { node: 'current' }, modules: 'commonjs' }]],
}).code, file);
const { documentBody, documentReviewNotes, documentSections, isDocumentDraft } = loaded.exports;

test('clinical document tasks have a separate copy policy from patient answers and native extraction', () => {
  for (const key of ['outpatient_note', 'admission_note', 'progress_note', 'discharge_summary', 'imaging_report_assistant']) assert.equal(isDocumentDraft(key), true);
  for (const key of ['patient_summary', 'patient_report_explanation', 'research_extraction', 'deidentification', undefined]) assert.equal(isDocumentDraft(key), false);
});

test('only selected clinical sections enter the clipboard, with original text and order preserved', () => {
  const body = '\uFEFF主诉原文\r\n🧪e\u0301，0，不详';
  const result = { summary: '此说明不属于正文', warnings: ['待复核，不可忽略'], missing_data: ['缺检查结果'], sections: [
    { title: '主诉', content: body, source_ids: ['original-1'] },
    { title: '病史', content: '既往记录，未增补阴性体征', source_ids: ['original-2'] },
    { title: '诊疗经过', content: '尚未记录' },
  ] };
  assert.equal(documentBody(result, [2, 0, 0, -1, 0.5, 90, '1']), '主诉\n' + body + '\n\n诊疗经过\n尚未记录');
  assert.equal(documentBody(result), '');
  assert.equal(documentBody(result, []), '');
  assert.equal(documentBody(result, [1]), '病史\n既往记录，未增补阴性体征');
});

test('missing clinical sections never silently fall back to summaries or warning text', () => {
  for (const result of [undefined, { summary: '缺少正文', sections: [] }, { sections: [{ title: '空项', content: null }, { content: '  ' }] }]) {
    assert.deepEqual(documentSections(result), []);
    assert.equal(documentBody(result, [0]), '');
  }
});

test('review requirements remain explicit, distinct and unchanged outside the copied body', () => {
  const result = { warnings: ['原始风险\r\n保留措辞', '缺少复查'], missing_data: ['缺少复查', '尚无确认诊断', '', null] };
  assert.deepEqual(documentReviewNotes(result), ['原始风险\r\n保留措辞', '缺少复查', '尚无确认诊断']);
  assert.deepEqual(documentReviewNotes(undefined), []);
});
