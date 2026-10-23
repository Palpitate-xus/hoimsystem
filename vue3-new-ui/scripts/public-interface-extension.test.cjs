const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const {test}=require('node:test');
const generator=require('./generate-public-interface-text-pool.cjs');
const loader=require('./public-interface-text-loader.cjs');
const {encodeStaticJson}=require('./public-static-data.cjs');
const {decodeSchemaText,MAX_SCHEMA_BYTES}=require('../src/api/schemaDataCodec.cjs');
const group=generator.EXTENSION_GROUP;
const pool=require('../src/api/publicInterfaceExtensionTextPool.json');
const read=require('../src/api/publicInterfaceExtensionText.cjs');

test('both independently bounded public records retain their complete source text and original bytes',()=>{
  assert.deepEqual(pool,generator.buildPool(generator.ROOT,group));
  generator.checkBindings(pool,generator.ROOT,group);
  assert(group.files.length>20&&group.files.every(name=>!generator.FILES.includes(name)));
  assert.equal(new Set(loader.FILES).size,loader.FILES.length);
  for(const current of generator.GROUPS){
    const raw=fs.readFileSync(path.join(generator.ROOT,current.output));
    assert(raw.length<=MAX_SCHEMA_BYTES);
    const packed=encodeStaticJson(raw);
    assert.equal(decodeSchemaText(packed.encoded,packed.byteLength),raw.toString('utf8'));
  }
});

test('an extension module uses its own actual reader and exact strings after the real Babel result hook',()=>{
  const filename=group.files.find(name=>name.startsWith('src/api/'));
  const value=pool.values.find(value=>Buffer.byteLength(value)>=24);
  const context={resourcePath:path.join(generator.ROOT,filename),context:generator.ROOT,utils:{contextify:(_c,name)=>name},cacheable(){},addDependency(){}};
  const result=require('./public-interface-babel.cjs')().result.call(context,{code:'module.exports='+JSON.stringify(value)+';',map:null});
  assert(result.code.includes('publicInterfaceExtensionText.cjs'));
  assert(!result.code.includes('publicInterfaceText.cjs'));
  const module={exports:null};
  vm.runInNewContext(result.code,{module,require:name=>{assert.equal(name,path.join(generator.ROOT,group.reader));return read;}});
  assert.equal(module.exports,value);
});

test('each record rejects another group or stale source identities before authorizing string indexes',()=>{
  assert.throws(()=>generator.checkBindings(pool),/stale/);
  const altered=structuredClone(pool);
  altered.sources[group.files[0]]='0'.repeat(64);
  assert.throws(()=>generator.checkBindings(altered,generator.ROOT,group),/stale/);
  assert.throws(()=>loader.transformPublicText('module.exports=1;',{resourcePath:path.join(generator.ROOT,'src/api/patient.js')}),/not allowlisted/);
});

test('all extension lookups are exact and invalid indexes never coerce or fall back to another record',()=>{
  for(let index=0;index<pool.values.length;index++)assert.equal(read(index),pool.values[index]);
  for(const invalid of [-1,0.5,NaN,Infinity,'0',null,true,pool.values.length])assert.throws(()=>read(invalid),/index/);
});


test('actual production pool loader verifies build bindings and retains every runtime text while omitting only build metadata',()=>{
  const contract=require('./static-contract-data-loader.cjs'),codec=require('../src/api/schemaDataCodec.cjs');
  for(const current of generator.GROUPS){
    const raw=fs.readFileSync(path.join(generator.ROOT,current.output)),original=JSON.parse(raw),dependencies=[];
    const context={resourcePath:path.join(generator.ROOT,current.output),context:generator.ROOT,cacheable(){},getOptions:()=>({}),addDependency:name=>dependencies.push(name),utils:{contextify:(_c,name)=>name}};
    const code=contract.call(context,raw),module={exports:null};
    vm.runInNewContext(code,{module,require:name=>{assert.equal(name,path.join(generator.ROOT,'src/api/schemaDataCodec.cjs'));return codec;}});
    assert.deepEqual(module.exports,{schema_version:'hoim_runtime_interface_text_v1',values:original.values});
    assert.equal(dependencies.length,Object.keys(original.sources).length);
    const stale=structuredClone(original);stale.sources[current.files[0]]='0'.repeat(64);
    assert.throws(()=>contract.call(context,JSON.stringify(stale)),/stale/);
  }
});
