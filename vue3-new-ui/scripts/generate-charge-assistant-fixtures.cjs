const fs=require('node:fs'),path=require('node:path'),crypto=require('node:crypto'),zlib=require('node:zlib');
const root=path.resolve(__dirname,'..'),target=path.join(root,'e2e/fixtures/charge-assistant/actual.packed.json');
const check=process.argv.includes('--check');if(process.argv.slice(2).some(v=>v!=='--check'))throw new Error('Only --check accepted');
const hash=buffer=>crypto.createHash('sha256').update(buffer).digest('hex');
if(!check){
 const source=process.env.HOIM_CHARGE_FIXTURE_DIR||'/tmp/hoim-charge-assistant-final2-actual-packets';
 const profiles={};for(const kind of ['chat','responses']){const raw=fs.readFileSync(path.join(source,kind+'.json')),value=JSON.parse(raw),compressed=zlib.gzipSync(raw,{level:9});
  if(value.schema_version!=='charge_assistant_actual_main_v1'||value.provenance.provider_kind!==kind)throw new Error('Only actual exported same-case main task profiles accepted');
  profiles[kind]={sha256:hash(raw),bytes:raw.length,gzip_sha256:hash(compressed),gzip_bytes:compressed.length,gzip_base64:compressed.toString('base64')};
 }
 fs.mkdirSync(path.dirname(target),{recursive:true});fs.writeFileSync(target,JSON.stringify({schema_version:'charge_actual_gzip_fixtures_v1',provenance:'Lossless gzip of complete actual synthetic main JWT/ASGI export JSON, including all seven states and original raw frozen JSON strings; no hospital or real model data.',profiles})+'\n');
}
const packed=JSON.parse(fs.readFileSync(target,'utf8'));if(packed.schema_version!=='charge_actual_gzip_fixtures_v1')throw new Error('Unknown actual fixture wrapper');
for(const kind of ['chat','responses']){const item=packed.profiles[kind],compressed=Buffer.from(item.gzip_base64,'base64'),raw=zlib.gunzipSync(compressed);
 if(compressed.length!==item.gzip_bytes||hash(compressed)!==item.gzip_sha256||raw.length!==item.bytes||hash(raw)!==item.sha256)throw new Error('Compressed fixture does not preserve the exact original export bytes');
 const value=JSON.parse(raw);if(value.provenance.provider_kind!==kind||Object.keys(value.states).join(',')!=='queued,running,succeeded,failed,cancelled_zero,cancelled_pending,cancelled_paid')throw new Error('Actual task states incomplete');
 process.stdout.write(`${check?'Verified':'Generated'} actual ${kind}: ${raw.length} -> ${compressed.length} bytes, raw SHA256 ${item.sha256}\n`);
}
