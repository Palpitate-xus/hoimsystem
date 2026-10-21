const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const {createHash, randomBytes} = require('node:crypto');
const {test} = require('node:test');
const loader = require('./schema-data-loader.cjs');
const {embedSchemaData} = require('./schema-html-data-plugin.cjs');
const codec = require('../src/api/schemaDataCodec.cjs');
const {schemaDataHash} = require('../src/api/schemaDataHash.cjs');
const root = path.resolve(__dirname, '..');
const readerCode = fs.readFileSync(path.join(root, 'src/api/schemaDataDocument.cjs'), 'utf8');

function files(directory) {
  return fs.readdirSync(directory, {withFileTypes: true}).flatMap(entry => entry.isDirectory() ? files(path.join(directory, entry.name)) : [path.join(directory, entry.name)]);
}

function artifact(file = path.join(root, 'src/api/ai/drugLabelSourceSchemas.json')) {
  const source = fs.readFileSync(file), data = loader.encodeSchemaData(source);
  const packed = Buffer.from(data.encoded, 'base64');
  const sha256 = createHash('sha256').update(packed).digest('hex');
  return {source, data, packed, sha256, entry: {encoded: data.encoded, byteLength: source.length, packedBytes: packed.length}};
}

function reader(documentText, count = 1) {
  const exports = {};
  const module = {exports};
  const document = {querySelectorAll: () => Array.from({length: count}, () => ({textContent: documentText}))};
  vm.runInNewContext(readerCode, {
    module, exports, document, Uint8Array, atob, btoa,
    require: name => name === './schemaDataCodec.cjs' ? codec : {schemaDataHash},
  });
  assert.equal(typeof module.exports.readSchemaDocumentData, 'function');
  return module.exports.readSchemaDocumentData;
}

function documentOf(value) {
  return JSON.stringify({schema_version: 'hoim_static_schema_document_v1', entries: {[value.sha256]: value.entry}});
}

test('synchronous SHA matches independent native crypto across block boundaries and the full byte cap', () => {
  for (const size of [0,1,2,3,55,56,63,64,65,127,128,65535,262144,524288]) {
    const bytes = randomBytes(size);
    assert.equal(schemaDataHash(bytes), createHash('sha256').update(bytes).digest('hex'), String(size));
  }
  assert.equal(schemaDataHash(new TextEncoder().encode('abc')), 'ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad');
  assert.throws(() => schemaDataHash(new Uint8Array(524289)));
});

test('every whole generated contract retains original UTF8 bytes and complete constraints through the inert document', () => {
  const schemas = files(path.join(root, 'src/api')).filter(file => /[A-Za-z]+Schemas\.json$/.test(file));
  assert(schemas.length > 20);
  const entries = {}, expected = [];
  for (const file of schemas) {
    const value = artifact(file);
    assert.equal(codec.decodeSchemaText(value.data.encoded, value.source.length), value.source.toString('utf8'));
    entries[value.sha256] = value.entry;
    expected.push(value);
  }
  const load = reader(JSON.stringify({schema_version: 'hoim_static_schema_document_v1', entries}));
  for (const value of expected) {
    const actual = load(value.sha256, value.source.length, value.packed.length);
    assert.deepEqual(actual, JSON.parse(value.source));
    assert.equal(actual, load(value.sha256, value.source.length, value.packed.length));
  }
  console.log(JSON.stringify({complete_generated_schema_files: schemas.length, original_contract_bytes: expected.reduce((n,v) => n+v.source.length,0)}));
});

for (const fault of ['missing', 'duplicate', 'registry_extra', 'record_extra', 'encoded_sha', 'short', 'binding', 'non_ascii']) {
  test(`refuse the whole static registry or record on ${fault}`, () => {
    const value = artifact();
    let doc = JSON.parse(documentOf(value)), count = 1;
    if (fault === 'missing') count = 0;
    if (fault === 'duplicate') count = 2;
    if (fault === 'registry_extra') doc.patient = {secret: true};
    if (fault === 'record_extra') doc.entries[value.sha256].secret = 'unexpected';
    if (fault === 'encoded_sha') {
      const changed = Buffer.from(value.packed); changed[changed.length - 1] ^= 1;
      doc.entries[value.sha256].encoded = changed.toString('base64');
    }
    if (fault === 'short') doc.entries[value.sha256].encoded = value.data.encoded.slice(0, -4);
    if (fault === 'binding') doc.entries[value.sha256].byteLength++;
    const text = JSON.stringify(doc) + (fault === 'non_ascii' ? '\ufeff' : '');
    const load = reader(text, count);
    assert.throws(() => load(value.sha256, value.source.length, value.packed.length));
  });
}

test('loader and HTML plugin move data only, preserve ordinary assets and reject damaged build records', () => {
  const value = artifact(), emitted = [];
  const output = loader.call({cacheable() {}, getOptions: () => ({documentData: true}), emitFile: (...args) => emitted.push(args), context: root, utils: {contextify: (context, target) => target}}, value.source);
  assert.equal(emitted.length, 1);
  assert(output.includes('readSchemaDocumentData'));
  assert(!output.includes('await') && !output.includes('fetch') && !output.includes(value.data.encoded));
  const ordinary = {name: 'js/ordinary.js', source: {source: () => 'unchanged executable bytes'}};
  const assets = [ordinary, ...emitted.map(([name, body]) => ({name, source: {source: () => body}}))];
  const deleted = [];
  const compilation = {getAssets: () => assets.filter(asset => !deleted.includes(asset.name)), deleteAsset: name => deleted.push(name)};
  const html = embedSchemaData(compilation, '<html><head></head><body></body></html>');
  const text = html.match(/<script id="hoim-schema-data" type="application\/json">([^<]+)<\/script>/)[1];
  assert.deepEqual(reader(text)(value.sha256, value.source.length, value.packed.length), JSON.parse(value.source));
  assert.deepEqual(deleted, [emitted[0][0]]);
  assert.deepEqual(compilation.getAssets(), [ordinary]);
  assert.equal(embedSchemaData(compilation, '<head></head>'), html.match(/<head>.*<\/head>/)[0]);
  const invalid = {getAssets: () => [{...assets[1], source: {source: () => emitted[0][1].replace(value.sha256, 'f'.repeat(64))}}], deleteAsset() {throw new Error('Must not delete invalid data');}};
  assert.throws(() => embedSchemaData(invalid, '<head></head>'));
});

test('development loader remains synchronous and inlines the same complete schema data', () => {
  const value = artifact();
  const output = loader.call({cacheable() {}, context: root, utils: {contextify: (context, target) => target}}, value.source);
  assert(output.includes('decodeSchemaData'));
  assert(output.includes(value.data.encoded));
  assert(!output.includes('readSchemaDocumentData'));
});
