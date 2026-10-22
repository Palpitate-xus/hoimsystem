const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),crypto=require('node:crypto'),path=require('node:path');
const loader=require('../scripts/schema-data-loader.cjs'),{decodeSchemaText,decodeSchemaData,MAX_SCHEMA_BYTES}=require('../src/api/schemaDataCodec.cjs');
const vm=require('node:vm');
const hash=value=>crypto.createHash('sha256').update(value).digest('hex');
for(const file of loader.PUBLIC_FIXED_PATHS)test('whole actual public fixed file survives byte-for-byte: '+path.basename(file),()=>{
 const raw=fs.readFileSync(file),packed=loader.encodePublicFixedData(raw),text=decodeSchemaText(packed.encoded,packed.byteLength);assert.equal(text,raw.toString('utf8'));assert.equal(hash(text),hash(raw));assert.deepEqual(decodeSchemaData(packed.encoded,packed.byteLength),JSON.parse(raw));
 const output=loader.call({cacheable(){},getOptions:()=>({kind:'public_fixed'}),resourcePath:file,context:path.dirname(file),utils:{contextify:(_,v)=>v}},raw);assert.ok(output.startsWith('module.exports = require('));assert.ok(output.includes('.decodeSchemaData('));assert.ok(!output.includes('eval(')&&!output.includes('new Function'));
 const target={exports:{}};vm.runInNewContext(output,{module:target,require:request=>{assert.equal(request,path.resolve(__dirname,'../src/api/schemaDataCodec.cjs'));return require('../src/api/schemaDataCodec.cjs');}},{timeout:1000});assert.deepEqual(target.exports,JSON.parse(raw));
});
test('whole public fixed UTF8 boundary retains whitespace, BOM inside values and exact numeric lexemes',()=>{
 const prefix='{"text":"\\ufeff\\r\\n🧪é","zero":0.0,"small":1e-6}',raw=Buffer.from(prefix+' '.repeat(MAX_SCHEMA_BYTES-Buffer.byteLength(prefix))),packed=loader.encodePublicFixedData(raw);assert.equal(decodeSchemaText(packed.encoded,packed.byteLength),raw.toString('utf8'));assert.throws(()=>loader.encodePublicFixedData(Buffer.concat([raw,Buffer.from(' ')])));assert.throws(()=>loader.encodePublicFixedData(Buffer.from([255])));
});
test('wrong whole fixed shape, overflow numbers, forbidden object keys and surrogate text refuse',()=>{
 for(const raw of ['null','[]','0','{"v":1e400}','{"__proto__":{}}','{"constructor":{}}','{"v":"\\ud800"}','{"\\udc00":0}'])assert.throws(()=>loader.encodePublicFixedData(raw),raw);
});
test('fixed node and depth limits reject whole input rather than returning a prefix',()=>{
 const valid=JSON.stringify({values:Array(loader.MAX_FIXED_NODES-2).fill(0)}),packed=loader.encodePublicFixedData(valid);assert.equal(decodeSchemaText(packed.encoded,packed.byteLength),valid);assert.throws(()=>loader.encodePublicFixedData(JSON.stringify({values:Array(loader.MAX_FIXED_NODES-1).fill(0)})));
 const chain=n=>'{"v":'.repeat(n)+'0'+'}'.repeat(n);assert.doesNotThrow(()=>loader.encodePublicFixedData(chain(loader.MAX_FIXED_DEPTH)));assert.throws(()=>loader.encodePublicFixedData(chain(loader.MAX_FIXED_DEPTH+1)));
});
test('fixed mode is build-only and exact path allowlisted; schema mode remains strict',()=>{
 const raw=fs.readFileSync(loader.PUBLIC_FIXED_PATHS[0]);const context={cacheable(){},context:__dirname,utils:{contextify:(_,v)=>v}};
 assert.throws(()=>loader.call({...context,getOptions:()=>({kind:'public_fixed'}),resourcePath:path.join(__dirname,'private.json')},raw));assert.throws(()=>loader.call({...context,getOptions:()=>({kind:'unknown'})},raw));assert.throws(()=>loader.call({...context,getOptions:()=>({kind:'public_fixed',extra:true}),resourcePath:loader.PUBLIC_FIXED_PATHS[0]},raw));assert.throws(()=>loader.encodeSchemaData(raw));
});
