const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const {test} = require('node:test');
const {encodeStaticJson} = require('./public-static-data.cjs');
const schema = require('./schema-data-loader.cjs');
const loader = require('./static-contract-data-loader.cjs');
const {decodeSchemaText, decodeSchemaData, MAX_SCHEMA_BYTES} = require('../src/api/schemaDataCodec.cjs');
const root = path.resolve(__dirname, '..');
for (const file of loader.PUBLIC_CONTRACTS) test(`complete public source bytes and its exact compiled contract survive ${file}`, () => {
  const bytes = fs.readFileSync(path.join(root,file));
  const data = encodeStaticJson(bytes);
  assert.equal(decodeSchemaText(data.encoded,data.byteLength),bytes.toString('utf8'));
  const output = loader.call({resourcePath:path.join(root,file),cacheable(){},utils:{contextify:(_c,p)=>p},context:root},bytes);
  const module = {exports:{}};
  vm.runInNewContext(output,{module,require:()=>({decodeSchemaData})});
  const original=JSON.parse(bytes);
  const textGroup=require('./generate-public-interface-text-pool.cjs').GROUPS.find(group=>group.output===file);
  assert.deepEqual(module.exports,textGroup?{schema_version:'hoim_runtime_interface_text_v1',values:original.values}:original);
  if(textGroup)assert.equal(Object.hasOwn(module.exports,'sources'),false);
});
test('arbitrary resource paths never enter the public document', () => {
  for (const file of ['patient.json','src/api/patient.json','src/api/ai/../patient.json','src/api/bedFixedPolicy.json/private.json']) {
    assert.throws(()=>loader.call({resourcePath:path.join(root,file),cacheable(){throw Error('must reject first');}},Buffer.from('{}')),/not allowlisted/);
  }
});
test('schema registry contract stays closed independently of general static JSON storage', () => {
  for (const value of [{},[],null,{models:{},nodes:[],extra:true}]) assert.throws(()=>schema.encodeSchemaData(JSON.stringify(value)),/actual complete generated schema registry/);
  assert.deepEqual(decodeSchemaData(encodeStaticJson('{}').encoded,2),{});
});
test('storage rejects malformed UTF8 JSON, oversized original bytes and incomplete JSON', () => {
  for (const bytes of [Buffer.from([0xff]),Buffer.from('{'),Buffer.alloc(MAX_SCHEMA_BYTES+1,32),Buffer.alloc(0)]) assert.throws(()=>encodeStaticJson(bytes));
});
