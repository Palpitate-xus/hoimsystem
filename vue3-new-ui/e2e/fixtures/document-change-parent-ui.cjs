const fixture=require('./document-change-result/actual.json');
const feature=fixture.live.features.data.find(f=>f.key==='guideline_change_review'),scopeId=fixture.live.scope.data.snapshot.scope_id;
async function setupDocumentChangeParent(page,origin,{state='succeeded',initial={},mutate=null,hold=null}={}){
 const calls=[],v=fixture.states[state];let release;
 await page.addInitScript(value=>window.__documentChangeAssistantInitial=value,{feature,initialInput:{question:fixture.requests.create.input.question},...initial});
 await page.route('**/api/**',async route=>{const r=route.request(),u=new URL(r.url()),path=u.pathname,method=r.method();calls.push({path,method,query:Object.fromEntries(u.searchParams),body:r.postDataJSON()});let response;
  if(method==='GET'&&path==='/api/ai/features')response=fixture.live.features;
  if(method==='GET'&&path==='/api/ai/admin/document-changes/scopes')response=fixture.live.scope_directory;
  if(method==='GET'&&path===`/api/ai/admin/document-changes/scopes/${scopeId}`)response=fixture.live.scope;
  if(method==='GET'&&path===`/api/ai/admin/document-changes/scopes/${scopeId}/public-source`)response=fixture.live.public_source;
  if(method==='POST'&&path==='/api/ai/document-change/context')response=fixture.preview;
  if(method==='POST'&&path==='/api/ai/runs')response=v.receipt;
  if(method==='GET'&&path==='/api/ai/runs')response=fixture.history;
  const id=v.detail.data.run_id;
  if(method==='GET'&&path===`/api/ai/runs/${id}`)response=v.detail;
  if(method==='GET'&&path===`/api/ai/admin/runs/${id}`)response=v.trace;
  for(const kind of ['source','scope','result'])if(method==='GET'&&path===`/api/ai/runs/${id}/document-change/${kind}`)response=v[kind]||v.result_unavailable;
  if(method==='POST'&&path===`/api/ai/runs/${id}/feedback`)response=fixture.feedback;
  if(method==='POST'&&path===`/api/ai/runs/${id}/cancel`)response=fixture.states.cancelled.cancellation;
  let status=response?.code||200;response=response?structuredClone(response):{code:599,msg:'未预期请求'};if(status===200&&!Object.hasOwn(response,'data'))status=200;
  if(mutate)response=await mutate({path,method,response,calls});
  if(hold?.({path,method}))await new Promise(resolve=>release=resolve);
  await route.fulfill({status:response.code===599?599:status,json:response});
 });
 await page.goto(origin);await page.waitForFunction(()=>!!window.__documentChangeAssistantProbe);return {calls,get release(){return release;}};
}

module.exports={fixture,feature,scopeId,setupDocumentChangeParent};
