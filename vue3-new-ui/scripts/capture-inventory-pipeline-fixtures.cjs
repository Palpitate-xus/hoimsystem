const fs=require('node:fs'),path=require('node:path'),crypto=require('node:crypto');
// Extraction only: every value comes from real synthetic SQLite/JWT worker exports.
// This never edits a score, status, private original, publication flag or native proof.
const [completePath,unknownPath]=process.argv.slice(2);
if(!completePath||!unknownPath||process.argv.length!==4)throw new Error('Pass the two actual synthetic state-export JSON paths');
const root=path.resolve(__dirname,'..'),directory=path.join(root,'e2e/fixtures/inventory-pipeline');
const digest=value=>crypto.createHash('sha256').update(value).digest('hex'),inputs=[completePath,unknownPath].map(file=>({path:file,bytes:fs.readFileSync(file)}));
const [complete,unknown]=inputs.map(x=>JSON.parse(x.bytes));
if(complete.synthetic_only!==true||unknown.synthetic_only!==true||complete.controlled_business_clock!==true||unknown.controlled_business_clock!==true)throw new Error('Actual controlled synthetic export flags required');
for(const state of ['queued','running','succeeded','failed','cancelled'])if(complete.full_by_status[state].data.status!==state)throw new Error('Actual terminal/state packet required');
if(complete.full_by_status.succeeded.data.result.inventory_analysis.best_among_declared_candidates!==true||unknown.detail.data.result.inventory_analysis.best_among_declared_candidates!==false||unknown.detail.data.result.inventory_analysis.unknown_count!==2)throw new Error('Original computed proof differs from expected export scope');
fs.mkdirSync(directory,{recursive:true});
const artifacts=[];
for(const[name,value]of[['actual-states.json',complete],['actual-unknown.json',unknown]]){const text=JSON.stringify(value)+'\n';fs.writeFileSync(path.join(directory,name),text);artifacts.push({name,bytes:Buffer.byteLength(text),sha256:digest(text)});}
const manifest={scope:'Real synthetic SQLite/JWT API, governed Source and Scenario, durable worker/native ASGI; failed uses explicit mocked503. Browser tests intercept these exact packets and are isolated mocks, never real model HTTP or hospital evidence.',originals:inputs.map(x=>({path:x.path,bytes:x.bytes.length,sha256:digest(x.bytes)})),artifacts};
fs.writeFileSync(path.join(directory,'manifest.json'),JSON.stringify(manifest)+'\n');
process.stdout.write(JSON.stringify(manifest,null,2)+'\n');
