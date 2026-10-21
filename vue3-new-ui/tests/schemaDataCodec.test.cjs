const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const loader = require('../scripts/schema-data-loader.cjs');
const { MAX_SCHEMA_BYTES, decodeSchemaData, decodeSchemaText } = require('../src/api/schemaDataCodec.cjs');
const root = path.resolve(__dirname, '../src/api');
function registries(directory) {
  return fs.readdirSync(directory, { withFileTypes: true }).flatMap(entry => {
    const target = path.join(directory, entry.name);
    return entry.isDirectory() ? registries(target) : /Schemas\.json$/.test(entry.name) ? [target] : [];
  });
}
for (const file of registries(root)) {
  test(`complete original bytes and constraints survive storage: ${path.relative(root, file)}`, () => {
    const source = fs.readFileSync(file);
    const { encoded, byteLength } = loader.encodeSchemaData(source);
    assert.equal(decodeSchemaText(encoded, byteLength), source.toString('utf8'));
    assert.deepEqual(decodeSchemaData(encoded, byteLength), JSON.parse(source));
    assert.deepEqual(loader.encodeSchemaData(source), { encoded, byteLength });
  });
}
const source = Buffer.from(JSON.stringify({ models: { '工程🧪': 0 }, nodes: [{ pattern: '\ufeffa\r\n🙂e\u0301', type: 'string' }] }));
const packed = loader.encodeSchemaData(source);
test('literal Unicode, line boundaries and independent decoded objects', () => {
  const first = decodeSchemaData(packed.encoded, packed.byteLength);
  first.nodes[0].pattern = 'changed';
  assert.deepEqual(decodeSchemaData(packed.encoded, packed.byteLength), JSON.parse(source));
  assert.equal(decodeSchemaText(packed.encoded, packed.byteLength), source.toString('utf8'));
});
for (const size of [0, -1, 1.5, true, '12', MAX_SCHEMA_BYTES + 1, Infinity]) {
  test(`invalid declared original byte length ${String(size)}`, () => assert.throws(() => decodeSchemaData(packed.encoded, size)));
}
for (const encoded of ['', '@@@@', 'eAA=\n', 'eA==', 'AAAAAA==', 'AAE=', 'AAACAQ==', '/wA=']) {
  test(`invalid code/base64/UTF8/JSON ${JSON.stringify(encoded)}`, () => assert.throws(() => decodeSchemaData(encoded, 4)));
}
test('complete output cannot exceed or fall short of declared length', () => {
  assert.throws(() => decodeSchemaData(packed.encoded, packed.byteLength - 1));
  assert.throws(() => decodeSchemaData(packed.encoded, packed.byteLength + 1));
});
test('whole static source boundary; malformed registry and UTF8 refuse', () => {
  const prefix = '{"models":{},"nodes":[]}';
  const boundary = Buffer.from(prefix + ' '.repeat(MAX_SCHEMA_BYTES - prefix.length));
  const result = loader.encodeSchemaData(boundary);
  assert.equal(decodeSchemaText(result.encoded, result.byteLength), boundary.toString());
  assert.throws(() => loader.encodeSchemaData(Buffer.concat([boundary, Buffer.from(' ')])));
  for (const invalid of ['null', '[]', '{"models":[],"nodes":[]}', '{"models":{},"nodes":[],"extra":0}']) assert.throws(() => loader.encodeSchemaData(invalid));
  assert.throws(() => loader.encodeSchemaData(Buffer.from([255])));
});
test('wrapped complete registries retain literal metadata and reject partial or unknown wrappers', () => {
  const registry = JSON.parse(source);
  for (const name of ['policy', 'constants']) {
    const original = JSON.stringify({ schemas: registry, [name]: { text: '\ufeff\r\n🧪e\u0301', nested: [0, null, false] } });
    const encoded = loader.encodeSchemaData(original);
    assert.equal(decodeSchemaText(encoded.encoded, encoded.byteLength), original);
    assert.deepEqual(decodeSchemaData(encoded.encoded, encoded.byteLength), JSON.parse(original));
  }
  for (const invalid of [
    { schemas: registry }, { schemas: registry, extra: {} },
    { schemas: registry, policy: {}, constants: {} }, { schemas: registry, policy: null },
    { schemas: registry, constants: [] }, { schemas: { models: {} }, policy: {} },
    { schemas: { models: {}, nodes: [], extra: 1 }, constants: {} },
  ]) assert.throws(() => loader.encodeSchemaData(JSON.stringify(invalid)));
});
test('loader emits only data decoding; source modules and validation are retained', () => {
  const emitted = loader.call({ cacheable() {}, context: root, utils: { contextify: (_, value) => value } }, source);
  assert.ok(emitted.startsWith('module.exports = require('));
  assert.ok(emitted.includes('.decodeSchemaData('));
  assert.ok(!emitted.includes('eval') && !emitted.includes('new Function'));
});
test('fatal UTF8 decoding and JSON parsing are independently enforced', () => {
  assert.throws(() => decodeSchemaText('AP8=', 1), TypeError);
  assert.equal(decodeSchemaText('AHg=', 1), 'x');
  assert.throws(() => decodeSchemaData('AHg=', 1), SyntaxError);
});
test('complete large source survives the bounded 16-bit lookback window', () => {
  let seed = 20261021;
  let value = '';
  const alphabet = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/';
  for (let i = 0; i < 200000; i++) {
    seed ^= seed << 13; seed ^= seed >>> 17; seed ^= seed << 5;
    value += alphabet[(seed >>> 0) % alphabet.length];
  }
  const original = Buffer.from(JSON.stringify({ models: { Saturated: 0 }, nodes: [{ pattern: value }] }));
  const encoded = loader.encodeSchemaData(original);
  assert.ok(original.length > 65535);
  assert.equal(decodeSchemaText(encoded.encoded, encoded.byteLength), original.toString());
});

test('overlapping matches decode forward and invalid references refuse', () => {
  const bytes = Buffer.from([0, 97, 128, 1, 0]).toString('base64');
  assert.equal(decodeSchemaText(bytes, 5), 'aaaaa');
  for (const invalid of [[128, 1, 0], [0, 97, 128, 0, 0], [0, 97, 128, 2, 0], [0, 97, 128, 1], [127, 97]]) {
    assert.throws(() => decodeSchemaText(Buffer.from(invalid).toString('base64'), 132));
  }
});
