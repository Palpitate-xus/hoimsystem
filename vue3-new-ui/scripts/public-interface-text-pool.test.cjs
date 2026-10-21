const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {test} = require('node:test');
const generator = require('./generate-public-interface-text-pool.cjs');
const pool = require('../src/api/publicInterfaceTextPool.json');
const read = require('../src/api/publicInterfaceText.cjs');
const {encodeStaticJson} = require('./public-static-data.cjs');
const {decodeSchemaData} = require('../src/api/schemaDataCodec.cjs');

test('the complete generated pool equals all selected public source literals with current source bindings',()=>{
 assert.deepEqual(pool,generator.buildPool());generator.checkBindings(pool);
 assert.equal(new Set(generator.FILES).size,generator.FILES.length);
 assert(generator.FILES.every(name=>/^src\/(?:components\/|api\/|views\/system\/aiManagement\.vue)/.test(name)));
 assert(pool.values.length>1000);
 const original=fs.readFileSync(path.join(generator.ROOT,generator.OUTPUT));
 const encoded=encodeStaticJson(original);
 assert.deepEqual(decodeSchemaData(encoded.encoded,encoded.byteLength),pool);
});

test('every shared runtime lookup preserves its original complete string and rejects non-indices',()=>{
 for(let index=0;index<pool.values.length;index++)assert.equal(read(index),pool.values[index]);
 for(const bad of [-1,0.5,NaN,Infinity,'0',null,true,pool.values.length])assert.throws(()=>read(bad),/index/);
});

test('stale source bindings, duplicate text or unordered values fail the closed pool check',()=>{
 const stale=structuredClone(pool);stale.sources[generator.FILES[0]]='0'.repeat(64);assert.throws(()=>generator.checkBindings(stale),/stale/);
 const duplicate=structuredClone(pool);duplicate.values.push(duplicate.values[0]);assert.throws(()=>generator.checkBindings(duplicate),/stale/);
 const unordered=structuredClone(pool);unordered.values.reverse();assert.throws(()=>generator.checkBindings(unordered),/stale/);
});
