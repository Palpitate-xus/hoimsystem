const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { parse } = require('@babel/parser');
const root = path.resolve(__dirname, '..');
function load(source, injected, exports) {
  const ast = parse(source, { sourceType: 'module' });
  const ranges = ast.program.body.flatMap(node => node.type === 'ImportDeclaration' ? [[node.start, node.end]] : node.type === 'ExportNamedDeclaration' ? [[node.start, node.declaration?.start ?? node.end]] : []);
  for (const [start, end] of ranges.sort((a, b) => b[0] - a[0])) source = source.slice(0, start) + source.slice(end);
  return new Function(...Object.keys(injected), source + '\nreturn {' + exports + '};')(...Object.values(injected));
}
const { providerSnapshotKeys } = load(fs.readFileSync(path.join(root, 'src/api/ai/providerRetrySnapshot.js'), 'utf8'), {}, 'providerSnapshotKeys');
const schema = load(fs.readFileSync(path.join(root, 'src/api/sofaSchema.js'), 'utf8'), { registry: require('../src/api/sofaSchemas.json') }, 'decodeGeneratedSchemas:unpackRegistry,generatedSchemaMatches');
const cohort = require('../e2e/fixtures/research-cohort-tasks/chat.json').parts.task.execution_snapshot.provider_snapshot;
const operations = require('../e2e/fixtures/operations-support-packets.cjs').loadOperationsPackets('task-lifecycle-v2');
const operationTask = operations.data(operations.rows.find(row => row.status === 200 && row.path.endsWith('/parts/task')));
const training = require('../e2e/fixtures/clinical-training-task-packets.cjs');
const providers = [cohort, JSON.parse(operationTask.execution_snapshot_json).provider_snapshot,
  JSON.parse(Object.values(training.groups)[0].parts.task.value.execution_snapshot_json).provider_snapshot];
const invalidAttempts = [null, true, false, 0, -1, 4, 1.5, '2', undefined, NaN, Infinity];

test('the three actual legacy manual provider frames remain closed and byte-preserved without adding a retry field', () => {
  for (const original of providers) {
    assert.equal(Object.hasOwn(original, 'max_attempts'), false);
    const value = Object.freeze(structuredClone(original)), before = JSON.stringify(value);
    assert.equal(providerSnapshotKeys(value, Object.keys(original)), true);
    assert.equal(JSON.stringify(value), before);
    assert.equal(Object.hasOwn(value, 'max_attempts'), false);
  }
});

test('manual provider frames accept only explicit integer attempts one through three without rewriting their original fields', () => {
  for (const original of providers) for (const max_attempts of [1, 2, 3]) {
    const value = { ...original, max_attempts }, before = JSON.stringify(value);
    assert.equal(providerSnapshotKeys(value, Object.keys(original)), true);
    assert.equal(JSON.stringify(value), before);
  }
});

test('explicit null booleans strings and out-of-range attempts cannot become legacy missing-field fallback', () => {
  for (const original of providers) for (const max_attempts of invalidAttempts) {
    assert.equal(providerSnapshotKeys({ ...original, max_attempts }, Object.keys(original)), false);
  }
});

test('the optional retry field does not relax any original provider key or admit foreign content', () => {
  for (const original of providers) {
    const fields = Object.keys(original);
    assert.equal(providerSnapshotKeys({ ...original, max_attempts: 2, foreign_private_content: 'synthetic' }, fields), false);
    for (const field of fields) {
      const value = { ...original, max_attempts: 2 };
      delete value[field];
      assert.equal(providerSnapshotKeys(value, fields), false);
    }
  }
});

test('provider key closure rejects nonobjects and hidden-field substitutions', () => {
  for (const value of [null, undefined, [], 1, 'provider', true]) assert.equal(providerSnapshotKeys(value, []), false);
  const value = { revision: 1, foreign: true };
  Object.defineProperty(value, 'provider_id', { value: 1, enumerable: false });
  assert.equal(providerSnapshotKeys(value, ['provider_id', 'revision']), false);
});

// These are actual legacy provider values, with explicit synthetic retry
// variants, checked against the schemas generated from current backend models.
for (const filename of ['chargeReconciliationResultSchemas.json', 'codingResultSchemas.json', 'deidentificationTaskSchemas.json',
  'documentExtractionSchemas.json', 'documentChangeResultSchemas.json', 'drugLabelTaskSchemas.json',
  'researchVariableTaskSchemas.json', 'rcaEvidenceSchemas.json', 'satisfactionResultSchemas.json']) {
  test('generated provider contracts retain legacy frames and enforce strict retry attempts: ' + filename, () => {
    const registry = require(path.join(root, 'src/api/ai', filename));
    const models = schema.decodeGeneratedSchemas(filename === 'satisfactionResultSchemas.json' ? registry.schemas : registry);
    let checked = 0;
    for (const [name, model] of Object.entries(models)) {
      for (const [definition, candidate] of [[null, model], ...Object.entries(model.$defs || {})]) {
        if (!['provider_id', 'revision', 'timeout_seconds', 'max_output_tokens', 'effective_output_limit'].every(key => Object.hasOwn(candidate.properties || {}, key))) continue;
        const valid = value => schema.generatedSchemaMatches(models, name, value, definition);
        const original = Object.freeze(structuredClone(cohort)), before = JSON.stringify(original);
        assert.equal(valid(original), true, name + '/' + definition + ' legacy');
        assert.equal(JSON.stringify(original), before);
        assert.equal(Object.hasOwn(original, 'max_attempts'), false);
        for (const max_attempts of [1, 2, 3]) assert.equal(valid({ ...original, max_attempts }), true, name + '/' + definition + ' explicit' + max_attempts);
        for (const max_attempts of invalidAttempts) assert.equal(valid({ ...original, max_attempts }), false, name + '/' + definition + ' invalid' + String(max_attempts));
        assert.equal(valid({ ...original, max_attempts: 2, foreign_private_content: 'synthetic' }), false);
        checked++;
      }
    }
    assert(checked > 0, 'No actual closed provider schema found in ' + filename);
  });
}
