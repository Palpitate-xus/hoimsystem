const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),crypto=require('node:crypto');
const {parse}=require('@babel/parser');
const root=path.resolve(__dirname,'..'),fixture=require('../e2e/fixtures/task-technical-directory-main.json');
const pages=fixture.packets.filter(packet=>packet.response&&packet.response.page_size===30).map(packet=>packet.response);
const clone=value=>structuredClone(value);
function api(request){
 let source=fs.readFileSync(path.join(root,'src/api/ai/taskDirectory.js'),'utf8'),ast=parse(source,{sourceType:'module'});
 const ranges=ast.program.body.flatMap(node=>node.type==='ImportDeclaration'?[[node.start,node.end]]:node.type==='ExportNamedDeclaration'?[[node.start,node.declaration.start]]:[]);
 for(const [start,end]of ranges.sort((a,b)=>b[0]-a[0]))source=source.slice(0,start)+source.slice(end);
 return new Function('request',source+'\nreturn {technicalTaskValid,readTechnicalTasks};')(request);
}

test('actual Main generic/76/77 packets remain bound to current backend and keep original source traces denied',()=>{
 for(const [name,hash]of Object.entries(fixture.backend_bindings))assert.equal(crypto.createHash('sha256').update(fs.readFileSync(path.join(root,'..',name))).digest('hex'),hash,name);
 assert.deepEqual(fixture.packets.filter(packet=>packet.status).map(packet=>packet.status),[403,403]);
 const kinds=new Set(pages.flatMap(page=>page.data.flatMap(row=>row.native_domains)));
 assert(kinds.has('research_variables')&&kinds.has('rca'));
 const {technicalTaskValid}=api(()=>{throw Error('No transport expected');});
 for(const page of pages)for(const row of page.data)assert(technicalTaskValid(row),row.run_id);
});

test('actual closed Main pages are admitted as independently owned metadata',async()=>{
 for(const original of pages){
  const packet=clone(original),calls=[],{readTechnicalTasks}=api(async request=>{calls.push(request);return packet;});
  const result=await readTechnicalTasks({page:original.page,page_size:30},{current:()=>true});
  assert.deepEqual(result,original);assert.equal(calls[0].url,'ai/admin/task-directory');assert.equal(calls[0].method,'get');
  packet.data[0].feature_name='mutated after admission';assert.deepEqual(result,original);
 }
});

test('actual67-task service pages retain full totals and disjoint first three pages',async()=>{
 const ids=[];
 for(const item of fixture.service_pages){
  const original=item.response,{readTechnicalTasks}=api(async()=>clone(original));
  const result=await readTechnicalTasks({page:original.page,page_size:30},{current:()=>true});assert.deepEqual(result,original);
  if(!item.query.outcome){assert.equal(result.total,67);ids.push(...result.data.map(row=>row.run_id));}
 }
 assert.equal(ids.length,67);assert.equal(new Set(ids).size,67);
});

test('Source fields, physical zero counts and broken native identities cannot enter the technical view',()=>{
 const base=pages.at(-1).data.find(row=>row.native_domains.length===1),{technicalTaskValid}=api(()=>{});
 const mutations=[row=>{row.patient_id=1;},row=>{row.result={private:'source'};},row=>{row.frozen_request={private:'source'};},row=>{row.input_tokens=0;},row=>{row.output_tokens=0;},row=>{delete row.usage_verification;},row=>{row.native_domains=[];},row=>{row.native_domains.push(row.native_domains[0]);},row=>{row.native_feature_key='operations_qa';},row=>{row.feature_matches_native_contract=!row.feature_matches_native_contract;},row=>{row.requested_by=true;},row=>{row.provider_revision='1';},row=>{row.feedback_count=-1;},row=>{row.schema_version='unknown';}];
 for(const mutate of mutations){const row=clone(base);mutate(row);assert.equal(technicalTaskValid(row),false);}
});

test('duplicate, truncated and cross-page envelopes reject rather than manufacture completeness',async()=>{
 const original=pages.at(-1),mutations=[page=>{page.patient_id=1;},page=>{page.page=2;},page=>{page.page_size=100;},page=>{page.total++;},page=>{page.data.pop();},page=>{page.data[1]=clone(page.data[0]);},page=>{page.total='4';}];
 for(const mutate of mutations){const packet=clone(original);mutate(packet);const {readTechnicalTasks}=api(async()=>packet);await assert.rejects(readTechnicalTasks({page:1,page_size:30},{current:()=>true}),/闭集或分页/u);}
});

test('lost authority rejects both before transport and after a held complete reply',async()=>{
 let calls=0,current=false,resolve;
 const {readTechnicalTasks}=api(()=>{calls++;return new Promise(done=>{resolve=done;});});
 assert.equal(await readTechnicalTasks({page:1,page_size:30},{current:()=>current}),null);assert.equal(calls,0);
 current=true;const held=readTechnicalTasks({page:1,page_size:30},{current:()=>current});current=false;resolve(clone(pages.at(-1)));
 assert.equal(await held,null);assert.equal(calls,1);
});
