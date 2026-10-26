const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const root = path.resolve(__dirname, '..');
const source = fs.readFileSync(path.join(root, 'src/utils/aiManagementNavigation.js'), 'utf8');
const { AI_MANAGEMENT_GROUPS: groups, AI_MANAGEMENT_ENTRIES: entries } = new Function(source.replaceAll('export const ', 'const ') + '\nreturn { AI_MANAGEMENT_GROUPS, AI_MANAGEMENT_ENTRIES };')();
const management = fs.readFileSync(path.join(root, 'src/views/system/aiManagement.vue'), 'utf8');
const panes = [...management.matchAll(/<el-tab-pane\b[^>]*>/g)].map(([tag]) => ({ name: tag.match(/\bname="([^"]+)"/)[1], label: tag.match(/\blabel="([^"]+)"/)[1], guard: tag.includes('canCheckForecast') ? 'forecast' : tag.includes('canManageDrugLabels') ? 'drug_labels' : tag.includes('canManageResearchSources') ? 'research' : undefined }));
test('all 41 existing management panes remain findable once with their exact names and permission guards', () => {
  assert.equal(entries.length, 41); assert.equal(new Set(entries.map(entry => entry.name)).size, 41);
  assert.deepEqual(entries.map(({ name, label, guard }) => ({ name, label, guard })), panes);
  for (const entry of entries) assert(groups.some(group => group.key === entry.group), entry.name);
});
test('four task-oriented groups include configuration, data, tasks and access without dropping a dedicated domain', () => {
  assert.deepEqual(groups.map(group => group.label), ['功能与模型', '知识与数据', '任务与用量', '权限与审计']);
  assert.deepEqual(entries.filter(entry => entry.group === 'tasks_usage').map(entry => entry.name), ['technical_tasks', 'runs', 'usage']);
  assert.deepEqual(entries.filter(entry => entry.group === 'permissions_audit').map(entry => entry.name), ['grants', 'audit', 'review_excerpts']);
  for (const name of ['infection_sources', 'drug_label_sources', 'research_variable_sources', 'operations_support_sources', 'clinical_training_sources', 'rca_evidence']) assert.equal(entries.find(entry => entry.name === name).group, 'knowledge_data');
});
