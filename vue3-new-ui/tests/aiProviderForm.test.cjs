const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const source = fs.readFileSync(path.join(__dirname, '../src/utils/aiProviderForm.js'), 'utf8');
const { createProviderForm, providerAttemptLimit, providerWritePayload } = new Function(
  source.replaceAll('export function ', 'function ') + '\nreturn { createProviderForm, providerAttemptLimit, providerWritePayload };'
)();

test('new text providers default to three total attempts with an unchanged timeout', () => {
  for (const row of [undefined, null, { kind: 'responses' }]) {
    const form = createProviderForm(row);
    assert.equal(form.max_attempts, 3);
    assert.equal(form.timeout_seconds, 30);
    assert.equal(form.expected_revision, 0);
    assert.equal(providerWritePayload(form).max_attempts, 3);
  }
});

test('all three configured text attempt limits survive editing and the CAS write payload', () => {
  for (const kind of ['chat', 'responses']) for (const max_attempts of [1, 2, 3]) {
    const row = { kind, max_attempts, timeout_seconds: 17, revision: 9 };
    const form = createProviderForm(row), payload = providerWritePayload(form);
    assert.equal(providerAttemptLimit(form), max_attempts);
    assert.equal(payload.max_attempts, max_attempts);
    assert.equal(payload.timeout_seconds, 17);
    assert.equal(payload.expected_revision, 9);
  }
});

test('specialist adapters remain single-attempt even with a stored or edited text retry value', () => {
  const form = createProviderForm({ kind: 'specialist', max_attempts: 3, revision: 4 });
  assert.equal(form.max_attempts, 1);
  form.max_attempts = 3;
  assert.equal(providerAttemptLimit(form), 1);
  assert.equal(providerWritePayload(form).max_attempts, 1);
  assert.equal(providerWritePayload(form).expected_revision, 4);
});

test('changing the service kind derives a single attempt without losing the previous text setting', () => {
  const form = createProviderForm({ kind: 'chat', max_attempts: 2 });
  form.kind = 'specialist';
  assert.equal(providerAttemptLimit(form), 1);
  assert.equal(providerWritePayload(form).max_attempts, 1);
  form.kind = 'responses';
  assert.equal(providerAttemptLimit(form), 2);
  assert.equal(providerWritePayload(form).max_attempts, 2);
});

test('provider reads never refill a saved API key and explicit new or cleared credentials retain their meaning', () => {
  const form = createProviderForm({ kind: 'chat', api_key: 'synthetic-read-must-not-refill', api_key_env: 'SYNTHETIC_PROVIDER_KEY', has_api_key: true });
  assert.equal(form.api_key, '');
  assert.equal(providerWritePayload(form).api_key, null);
  assert.equal(providerWritePayload(form).api_key_env, 'SYNTHETIC_PROVIDER_KEY');
  form.api_key = 'synthetic-explicit-new-key';
  assert.equal(providerWritePayload(form).api_key, 'synthetic-explicit-new-key');
  form.api_key = '';
  form.clear_api_key = true;
  assert.equal(providerWritePayload(form).clear_api_key, true);
  assert.equal(providerWritePayload(form).api_key, null);
});

test('editing attempts preserves independent feature choices, zero temperature and patient transmission scope', () => {
  const row = { kind: 'responses', max_attempts: 1, supported_features: ['patient_summary'], temperature: 0, allows_patient_data: false, enabled: true };
  const form = createProviderForm(row);
  form.supported_features.push('record_quality');
  form.max_attempts = 2;
  assert.deepEqual(row.supported_features, ['patient_summary']);
  const payload = providerWritePayload(form);
  assert.equal(payload.temperature, 0);
  assert.equal(payload.allows_patient_data, false);
  assert.equal(payload.enabled, true);
  assert.equal(payload.max_attempts, 2);
});

test('invalid explicit text attempt values are retained for server rejection instead of silently enabling defaults', () => {
  for (const max_attempts of [null, 0, 4, 1.5, '2', false]) {
    const form = createProviderForm({ kind: 'chat', max_attempts });
    assert.equal(form.max_attempts, max_attempts);
    assert.equal(providerWritePayload(form).max_attempts, max_attempts);
  }
});
