// Mechanical lossless storage only. Every expanded subtree and the whole
// original packet retain canonical SHA/byte proofs; no clinical/quantity edits.
const fs=require('node:fs'),path=require('node:path'),crypto=require('node:crypto');
const target=path.join(__dirname,'inventory-production/packets.json');
const canonical=v=>v===null||typeof v!=='object'?JSON.stringify(v):Array.isArray(v)?'['+v.map(canonical).join(',')+']':'{'+Object.keys(v).sort().map(k=>JSON.stringify(k)+':'+canonical(v[k])).join(',')+'}';
const sha=s=>crypto.createHash('sha256').update(s).digest('hex');
function expand(bundle){
 if(Object.keys(bundle).sort().join('|')!=='canonical_bytes|canonical_sha256|parts|root|source_bytes|source_path|source_sha256')throw new Error('Unexpected production fixture manifest');
 const cache=new Map(),visiting=new Set();
 function decode(v){
  if(v===null||typeof v!=='object')return v;
  if(!Array.isArray(v)&&Object.hasOwn(v,'$production_ref')){
   const id=v.$production_ref;if(Object.keys(v).length!==1||!/^[a-f0-9]{64}$/.test(id)||!Object.hasOwn(bundle.parts,id)||visiting.has(id))throw new Error('Malformed or cyclic production fixture reference');
   if(cache.has(id))return cache.get(id);visiting.add(id);const expanded=decode(bundle.parts[id]);visiting.delete(id);if(sha(canonical(expanded))!==id)throw new Error('Production fixture subtree SHA mismatch');cache.set(id,expanded);return expanded;
  }
  return Array.isArray(v)?v.map(decode):Object.fromEntries(Object.entries(v).map(([k,x])=>[k,decode(x)]));
 }
 const value=decode(bundle.root),text=canonical(value);if(Buffer.byteLength(text)!==bundle.canonical_bytes||sha(text)!==bundle.canonical_sha256)throw new Error('Production original packet does not reconstruct');
 return JSON.parse(text);
}
function actual(){return expand(JSON.parse(fs.readFileSync(target,'utf8')));}
if(require.main===module){
 const source='/tmp/hoim-inventory-production-actual-packets-v4.json',bytes=fs.readFileSync(source),raw=JSON.parse(bytes),parts={},original=canonical(raw);
 function pack(v){
  if(v===null||typeof v!=='object')return v;if(!Array.isArray(v)&&Object.hasOwn(v,'$production_ref'))throw new Error('Original packet collides with storage reference namespace');
  const text=canonical(v),body=Array.isArray(v)?v.map(pack):Object.fromEntries(Object.entries(v).map(([k,x])=>[k,pack(x)]));
  if(Buffer.byteLength(text)<8192)return body;const id=sha(text);if(parts[id]&&canonical(parts[id])!==canonical(body))throw new Error('Subtree collision');parts[id]=body;return{$production_ref:id};
 }
 const root=pack(raw),bundle={source_path:source,source_sha256:sha(bytes),source_bytes:bytes.length,canonical_sha256:sha(original),canonical_bytes:Buffer.byteLength(original),root,parts},encoded=canonical(bundle)+'\n';
 if(canonical(expand(bundle))!==original)throw new Error('Actual whole packet differs after factoring');
 if(process.argv.includes('--check')){if(fs.readFileSync(target,'utf8')!==encoded)throw new Error('Production fixture differs from actual export');}else fs.writeFileSync(target,encoded);
 console.log(JSON.stringify({source_sha256:bundle.source_sha256,source_bytes:bytes.length,factored_bytes:Buffer.byteLength(encoded),subtree_count:Object.keys(parts).length}));
}
module.exports={actual};
