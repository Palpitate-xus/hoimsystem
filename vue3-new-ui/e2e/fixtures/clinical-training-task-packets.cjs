const fs=require('node:fs'),path=require('node:path'),zlib=require('node:zlib'),crypto=require('node:crypto');
const packed=JSON.parse(fs.readFileSync(path.join(__dirname,'clinical-training','task-main.packed.json'),'utf8')),raw=zlib.gunzipSync(Buffer.from(packed.gzip_base64,'base64'));
if(packed.schema_version!=='clinical_training_actual_task_http_gzip_v1'||raw.length!==packed.original_bytes||crypto.createHash('sha256').update(raw).digest('hex')!==packed.original_sha256)throw new Error('Actual same-case Task packet changed');
const source=JSON.parse(new TextDecoder('utf-8',{fatal:true}).decode(raw));
if(source.scope!=='One actual Main/JWT case and one new actual Main practice submission; real shared claim/worker with injected HTTP, seven actual native task snapshots, no cross-case packet splicing or real model/clinical validation.')throw new Error('Unexpected actual packet scope');
const data=r=>{const v=JSON.parse(r.body);return v&&Object.hasOwn(v,'data')?v.data:v;};
const part=r=>({raw:r.body,value:JSON.parse(r.body),wire:{parts_wire:r.wire_headers['x-ai-parts-wire']??null}});
const groups=Object.fromEntries(Object.entries(source.groups).map(([name,g])=>{const rows=g.packets.map(i=>source.packets[i]);if(rows.length!==5||!rows.every(r=>r.status===200)||data(rows[0]).run_id!==g.run_id||JSON.stringify(data(rows[0]))!==JSON.stringify(g.metadata))throw new Error('Actual group metadata/index mismatch');const parts=Object.fromEntries(['task','source','binding','result'].map((name,i)=>{if(!rows[i+1].path.endsWith('/'+name)||!rows[i+1].path.includes(g.run_id))throw new Error('Mixed actual run parts');return[name,part(rows[i+1])];}));return[name,{metadata:data(rows[0]),parts,rows}];}));
module.exports={packed,source,data,part,groups};
