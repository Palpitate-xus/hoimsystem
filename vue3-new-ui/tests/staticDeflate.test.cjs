const {test}=require('node:test');
const assert=require('node:assert/strict');
const zlib=require('node:zlib');
const fs=require('node:fs');
const path=require('node:path');
const {inflateStatic}=require('../src/api/staticDeflate.cjs');
const {decodeSchemaText,MAX_SCHEMA_BYTES}=require('../src/api/schemaDataCodec.cjs');
const {encodeStaticJson}=require('../scripts/public-static-data.cjs');

test('independent Node zlib stored, fixed and dynamic blocks restore exact bounded bytes',()=>{
  const data=[Buffer.from('A'),Buffer.from('原文\ufeff\r\n🧪é'.repeat(1000)),Buffer.from(JSON.stringify(require('../src/api/ai/rcaEvidenceSchemas.json'))),Buffer.from(Array.from({length:MAX_SCHEMA_BYTES},(_,i)=>i%251))];
  const options=[{level:0},{level:1},{level:6},{level:9,memLevel:9},{level:9,strategy:zlib.constants.Z_FIXED},{level:9,strategy:zlib.constants.Z_HUFFMAN_ONLY},{level:9,strategy:zlib.constants.Z_RLE}];
  for(const original of data)for(const option of options){const compressed=zlib.deflateRawSync(original,option);assert.deepEqual(Buffer.from(inflateStatic(compressed,original.length)),original);assert.deepEqual(zlib.inflateRawSync(compressed),original);}
});

test('every original public schema and fixed JSON retains exact UTF8 bytes through the chosen old or new codec',()=>{
  const root=path.join(__dirname,'../src/api');
  const files=[];
  function collect(directory){for(const item of fs.readdirSync(directory,{withFileTypes:true})){const filename=path.join(directory,item.name);if(item.isDirectory())collect(filename);else if(item.name.endsWith('.json'))files.push(filename);}}
  collect(root);
  let deflated=0;
  for(const filename of files){const original=fs.readFileSync(filename);if(original.length>MAX_SCHEMA_BYTES)continue;const packed=encodeStaticJson(original);assert.equal(decodeSchemaText(packed.encoded,packed.byteLength),original.toString('utf8'),filename);if(Buffer.from(packed.encoded,'base64').subarray(0,4).equals(Buffer.from([255,0,0,1])))deflated++;}
  assert(deflated>20);
});

test('exact output bounds reject short or overlong declarations, truncation, trailing bytes and expansions before producing a prefix',()=>{
  const original=Buffer.from('bounded-public-only-'.repeat(10000)),compressed=zlib.deflateRawSync(original,{level:9});
  for(const length of [1,original.length-1,original.length+1,MAX_SCHEMA_BYTES+1])assert.throws(()=>inflateStatic(compressed,length));
  for(let end=0;end<compressed.length;end++)assert.throws(()=>inflateStatic(compressed.subarray(0,end),original.length));
  assert.throws(()=>inflateStatic(Buffer.concat([compressed,Buffer.from([0])]),original.length),/trailing/);
  const expansion=zlib.deflateRawSync(Buffer.alloc(MAX_SCHEMA_BYTES*2,65));
  assert.throws(()=>inflateStatic(expansion,MAX_SCHEMA_BYTES),/overflow|reference/);
});

function bits(values){const output=Buffer.alloc(Math.ceil(values.length/8));values.forEach((value,index)=>output[index>>>3]|=value<<(index&7));return output;}
function integer(value,width){return Array.from({length:width},(_,index)=>(value>>>index)&1);}
function code(value,width){return integer(value,width).reverse();}

test('reserved block/symbol/count, impossible Huffman trees and references before output fail closed',()=>{
  assert.throws(()=>inflateStatic(bits([1,1,1]),1),/block type/);
  // Fixed length257 followed by distance1 before any literal has been produced.
  assert.throws(()=>inflateStatic(bits([1,1,0,...code(1,7),...code(0,5),...code(0,7)]),3),/reference/);
  assert.throws(()=>inflateStatic(bits([1,1,0,...code(198,8),...code(0,7)]),1),/length/);
  assert.throws(()=>inflateStatic(bits([1,0,1,...integer(31,5),...integer(0,5),...integer(0,4)]),1),/literal count/);
  const header=[1,0,1,...integer(0,5),...integer(0,5),...integer(15,4)];
  assert.throws(()=>inflateStatic(bits([...header,...Array.from({length:19},()=>integer(1,3)).flat()]),1),/Oversubscribed/);
});

test('new framing is unambiguous to the original zero-distance rule and malformed UTF8 is never replaced',()=>{
  for(const raw of [[255,0,0],[255,0,0,0],[255,0,0,2,0]])assert.throws(()=>decodeSchemaText(Buffer.from(raw).toString('base64'),100));
  const source=Buffer.alloc(32,255),packed=Buffer.concat([Buffer.from([255,0,0,1]),zlib.deflateRawSync(source)]);
  assert.throws(()=>decodeSchemaText(packed.toString('base64'),32),/encoded data/);
  assert.equal(decodeSchemaText(Buffer.from([0,65]).toString('base64'),1),'A');
});
