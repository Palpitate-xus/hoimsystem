const {test,expect}=require('@playwright/test');
const F=require('./fixtures/research-variable-task/actual-states.json');
const {startResearchVariableTaskHarness}=require('./fixtures/research-variable-task-harness.cjs');
let harness;
test.beforeAll(async()=>{harness=await startResearchVariableTaskHarness();});
test.afterAll(async()=>{await harness?.close();});
async function open(page){
 const errors=[];page.on('pageerror',error=>errors.push(error.message));
 await page.context().route('**/*',route=>new URL(route.request().url()).origin===harness.origin?route.continue():route.abort());
 await page.goto(harness.origin);await page.waitForFunction(()=>!!window.__researchVariableFlow);return errors;
}
const wrapped=value=>({code:200,msg:'success',data:value});
async function serve(page,packet,{detail=packet.detail,trace=packet.trace,hold=null}={}){
 const calls=[];await page.route('**/api/ai/**',async route=>{
  const path=new URL(route.request().url()).pathname.replace(/^\/api/u,'');calls.push({method:route.request().method(),path,body:route.request().postData()});
  if(hold)await hold(path);
  if(path==='/ai/research-variables/context')return route.fulfill({json:F.preview});
  if(path===`/ai/research-variables/batches/${F.selection.research_variable_batch_id}/parts/source`)return route.fulfill({json:F.source_parts.source});
  if(path===`/ai/research-variables/batches/${F.selection.research_variable_batch_id}/parts/snapshot`)return route.fulfill({json:F.source_parts.snapshot});
  if(path===`/ai/runs/${packet.detail.run_id}`)return route.fulfill({json:wrapped(detail)});
  if(path===`/ai/admin/runs/${packet.detail.run_id}`)return route.fulfill({json:wrapped(trace)});
  for(const[name,value]of Object.entries(packet.parts))if(path.endsWith('/research-variables/'+name))return route.fulfill({json:value});
  if(path==='/ai/runs'&&route.request().method()==='GET')return route.fulfill({json:F.history});
  return route.fulfill({status:599,json:{detail:'unmocked exact path'}});
 });return calls;
}
test('actual preview binds both independent full originals, all Scope patients, question and exact metadata',async({page})=>{
 const errors=await open(page);expect(await page.evaluate(async fixture=>{
  const value=await window.__researchVariableFlow.verifyResearchVariablePreview(fixture.preview.data,fixture.source_parts.source.data,fixture.source_parts.snapshot.data,{selection:fixture.selection});
  return value&&{level:value.level,batch:value.bindingReference.batch_id,source:value.source.source_id};
 },F)).toEqual({level:'complete_current_originals_and_server_recorded_purpose_anchors',batch:F.selection.research_variable_batch_id,source:F.preview.data.research_variable_binding.source_id});expect(errors).toEqual([]);
});
for(const mutation of ['question','eligible','technical_metadata','private_hash','purpose_omission','foreign_source','future_clock','model_preview','source_url','extra'])test('preview proof refuses '+mutation+' without showing any part',async({page})=>{
 const errors=await open(page);expect(await page.evaluate(async({fixture,mutation})=>{
  const p=structuredClone(fixture.preview.data),s=structuredClone(fixture.source_parts.source.data),o=structuredClone(fixture.source_parts.snapshot.data);
  if(mutation==='question')p.context.question+='changed';if(mutation==='eligible')s.current_validation.eligible=false;if(mutation==='technical_metadata')s.metadata.technical_only=true;if(mutation==='private_hash')p.research_variable_binding.private_scope_hash='0'.repeat(64);if(mutation==='purpose_omission')p.research_variable_binding.request_authorization.patient_authorizations.pop();if(mutation==='foreign_source')s.value.source_id='foreign';if(mutation==='future_clock')p.context.snapshot_time='0001-01-01T00:00:00.000000Z';if(mutation==='model_preview')p.model_preview.included=true;if(mutation==='source_url')p.parts.source='https://external.invalid/private';if(mutation==='extra')p.patient_id=1;
  return window.__researchVariableFlow.verifyResearchVariablePreview(p,s,o,{selection:fixture.selection});
 },{fixture:F,mutation})).toBeNull();expect(errors).toEqual([]);
});
test('actual preview request loads exact local piece routes and keeps the original question bytes',async({page})=>{
 const errors=await open(page),calls=await serve(page,F.states.succeeded_partial);
 expect(await page.evaluate(async selection=>!!await window.__researchVariableFlow.readVerifiedResearchVariablePreview(selection),F.selection)).toBe(true);
 expect(calls.map(x=>x.path).sort()).toEqual(['/ai/research-variables/context',`/ai/research-variables/batches/${F.selection.research_variable_batch_id}/parts/source`,`/ai/research-variables/batches/${F.selection.research_variable_batch_id}/parts/snapshot`].sort());
 expect(JSON.parse(calls.find(x=>x.method==='POST').body)).toEqual(F.selection);expect(errors).toEqual([]);
});
for(const[name,packet]of Object.entries(F.states))test('actual '+name+' loads full current pieces before the business view can expose a result',async({page})=>{
 const errors=await open(page),calls=await serve(page,packet);
 const result=await page.evaluate(async({id,batch,selection})=>{const value=await window.__researchVariableFlow.readVerifiedResearchVariableTask(id,{batchId:batch,selection});return value&&{status:value.run.status,receipt:value.run.usage_receipt,trace:value.trace};},{id:packet.detail.run_id,batch:packet.detail.research_variable_batch_id,selection:F.selection});
 expect(result).toEqual({status:packet.detail.status,receipt:packet.detail.usage_receipt,trace:null});expect(calls.filter(x=>x.path.includes('/admin/'))).toEqual([]);expect(calls.some(x=>x.path.endsWith('/result'))).toBe(packet.detail.status==='succeeded');expect(errors).toEqual([]);
});
test('explicit Super trace independently closes raw JSON and original configuration after ordinary current pieces',async({page})=>{
 const errors=await open(page),packet=F.states.succeeded_partial,calls=await serve(page,packet);
 expect(await page.evaluate(async({id,batch})=>(await window.__researchVariableFlow.readVerifiedResearchVariableTask(id,{batchId:batch,withTrace:true})).checked.level,{id:packet.detail.run_id,batch:packet.detail.research_variable_batch_id})).toBe('literal_source_and_raw_frozen_task');
 expect(calls.filter(x=>x.path.includes('/admin/')).map(x=>x.path)).toEqual([`/ai/admin/runs/${packet.detail.run_id}`]);expect(errors).toEqual([]);
});
for(const mutation of ['id','digest','provider','prompt','question'])test('complete GET cannot replace the original receipt '+mutation+' anchor',async({page})=>{
 const errors=await open(page),packet=F.states.succeeded_partial,detail=structuredClone(packet.detail);
 if(mutation==='id')detail.run_id='00000000-0000-0000-0000-000000000001';if(mutation==='digest')detail.context_digest='0'.repeat(64);if(mutation==='provider')detail.provider_revision++;if(mutation==='prompt')detail.prompt_version++;
 const calls=await serve(page,packet,{detail});expect(await page.evaluate(async({packet,selection,mutation})=>{
  try{await window.__researchVariableFlow.readVerifiedResearchVariableTask(packet.detail.run_id,{batchId:packet.detail.research_variable_batch_id,receipt:packet.detail,selection:mutation==='question'?{...selection,question:'changed'}:selection});return false;}catch{return true;}
 },{packet,selection:F.selection,mutation})).toBe(true);expect(calls.filter(x=>x.path.includes('/research-variables/'))).toEqual([]);expect(errors).toEqual([]);
});
test('queued receipt may advance to succeeded while preserving the same Task, source and question',async({page})=>{
 const errors=await open(page),packet=F.states.succeeded_partial;await serve(page,packet);
 expect(await page.evaluate(async({packet,receipt,selection})=>!!await window.__researchVariableFlow.readVerifiedResearchVariableTask(packet.detail.run_id,{batchId:packet.detail.research_variable_batch_id,receipt,selection}),{packet,receipt:F.states.queued.detail,selection:F.selection})).toBe(true);expect(errors).toEqual([]);
});
test('late preview response after invalidation does not start any private piece request',async({page})=>{
 const errors=await open(page);let release;const held=new Promise(resolve=>{release=resolve;}),calls=await serve(page,F.states.queued,{hold:async path=>{if(path.endsWith('/context'))await held;}});
 await page.evaluate(selection=>{window.__flowCurrent=true;window.__lateFlow=window.__researchVariableFlow.readVerifiedResearchVariablePreview(selection,{current:()=>window.__flowCurrent});},F.selection);
 await expect.poll(()=>calls.length).toBe(1);await page.evaluate(()=>{window.__flowCurrent=false;});release();expect(await page.evaluate(()=>window.__lateFlow)).toBeNull();expect(calls.map(x=>x.path)).toEqual(['/ai/research-variables/context']);expect(errors).toEqual([]);
});
test('actual native history stays Batch scoped and exposes no generic summary before opening full pieces',async({page})=>{
 const errors=await open(page),calls=await serve(page,F.states.queued);expect(await page.evaluate(async id=>(await window.__researchVariableFlow.readResearchVariableHistory(id)).map(x=>x.run_id),F.selection.research_variable_batch_id)).toEqual(F.history.data.map(x=>x.run_id));
 expect(calls.map(x=>x.path)).toEqual(['/ai/runs']);expect(errors).toEqual([]);
});
