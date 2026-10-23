const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),crypto=require('node:crypto');
const {encodeHtmlCodeBytes,embedSchemaData}=require('../scripts/schema-html-data-plugin.cjs');
const {encodeStaticJson}=require('../scripts/public-static-data.cjs');
const {decodeStaticCodeBytes,decodeSchemaText,MAX_SCHEMA_BYTES}=require('../src/api/schemaDataCodec.cjs');
const restore=(encoded,limit)=>Buffer.from(decodeStaticCodeBytes(encoded,limit),'binary');

test('radix85 versioned words preserve independent fixed numeric vectors',()=>{
 for(const [bytes,encoded]of [[[0,0,0,0],'~10!!!!!'],[[0,0,0,1],'~10!!!!#'],[[255,255,255,255],'~10z;]0!']]){
  assert.equal(encodeHtmlCodeBytes(Buffer.from(bytes)),encoded);assert.deepEqual(restore(encoded,4),Buffer.from(bytes));
 }
});

test('all single-byte values, word tails and block boundaries preserve exact original bytes',()=>{
 for(let value=0;value<256;value++)assert.deepEqual(restore(encodeHtmlCodeBytes(Buffer.from([value])),1),Buffer.from([value]));
 for(const size of [...Array.from({length:1025},(_,i)=>i+1),8191,8192,8193,65535,65536,262144]){
  const bytes=Buffer.alloc(size);for(let i=0;i<size;i++)bytes[i]=(i*37+size*13)%256;
  const encoded=encodeHtmlCodeBytes(bytes);assert(!/["'\\<>`&\s]/u.test(encoded));assert.deepEqual(restore(encoded,size),bytes);
 }
});

test('the original canonical base64 remains readable and noncanonical old padding is rejected',()=>{
 for(const size of [1,2,3,4,31,32,33,65535]){const bytes=crypto.randomBytes(size);assert.deepEqual(restore(bytes.toString('base64'),size),bytes);}
 for(const invalid of ['', 'Zg==\n','Zh==','Zg=','Zg===','@@=='])assert.throws(()=>restore(invalid,20));
 assert.equal(decodeSchemaText('AHg=',1),'x');
});

test('unknown versions, illegal words, overflow, lengths and nonzero padding fail before admission',()=>{
 for(const invalid of ['~1','~10','~20!!!!!','~1x!!!!!','~14!!!!!','~10!!!!','~10|||||','~10!!!!"','~10!!!!\\','~10!!!!<','~10!!!!>','~10!!!!&','~11!!!!#'])assert.throws(()=>restore(invalid,32),invalid);
 for(const size of [0,-1,1.5,NaN,Infinity,MAX_SCHEMA_BYTES*2+1])assert.throws(()=>restore('~10!!!!!',size));
 assert.throws(()=>restore('~10!!!!!',3));
});

test('original512KiB code bound remains exact for both binary transports',()=>{
 const bytes=crypto.randomBytes(MAX_SCHEMA_BYTES*2),dense=encodeHtmlCodeBytes(bytes);
 assert.deepEqual(restore(dense,bytes.length),bytes);assert.deepEqual(restore(bytes.toString('base64'),bytes.length),bytes);
 assert.throws(()=>restore(dense,bytes.length-1));assert.throws(()=>encodeHtmlCodeBytes(Buffer.alloc(0)));assert.throws(()=>encodeHtmlCodeBytes(Buffer.alloc(bytes.length+1)));
});

test('every real public JSON retains full UTF8 and SHA in the actual inert HTML envelope',()=>{
 const directory=path.resolve(__dirname,'../src/api'),assets=new Map(),originals=new Map();
 function files(folder){return fs.readdirSync(folder,{withFileTypes:true}).flatMap(entry=>entry.isDirectory()?files(path.join(folder,entry.name)):[path.join(folder,entry.name)]);}
 for(const file of files(directory).filter(file=>file.endsWith('.json'))){
  const raw=fs.readFileSync(file),packed=encodeStaticJson(raw),bytes=Buffer.from(packed.encoded,'base64'),sha=crypto.createHash('sha256').update(bytes).digest('hex'),name=`static/schema-data/${sha}.schema.json`;
  assets.set(name,{name,source:{source:()=>JSON.stringify({schema_version:'hoim_static_schema_record_v1',encoded:packed.encoded,byteLength:packed.byteLength,packedBytes:bytes.length,sha256:sha})}});originals.set(sha,{raw,bytes});
 }
 const compilation={getAssets:()=>[...assets.values()],deleteAsset:name=>assets.delete(name)};
 const html=embedSchemaData(compilation,'<!doctype html><head></head>'),doc=JSON.parse(html.match(/<script id="hoim-schema-data" type="application\/json">([^<]+)<\/script>/u)[1]);
 assert.equal(assets.size,0);assert.equal(Object.keys(doc.entries).length,originals.size);assert(Object.values(doc.entries).some(entry=>entry.encoded.startsWith('~1')));
 for(const [sha,entry]of Object.entries(doc.entries)){
  const {raw,bytes}=originals.get(sha),restored=restore(entry.encoded,entry.packedBytes);
  assert.deepEqual(restored,bytes);assert.equal(crypto.createHash('sha256').update(restored).digest('hex'),sha);assert.equal(decodeSchemaText(entry.encoded,entry.byteLength),raw.toString('utf8'));
 }
});
