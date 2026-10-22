const {test,expect}=require('@playwright/test');
const F=require('./fixtures/research-variable-task/actual-states.json');
const {startResearchVariableAssistantHarness}=require('./fixtures/research-variable-assistant-harness.cjs');
const feature=F.features.data.find(row=>row.key==='research_extraction'),batch=F.selection.research_variable_batch_id;
let harness;test.beforeAll(async()=>{harness=await startResearchVariableAssistantHarness();});test.afterAll(async()=>{await harness?.close();});
const wrapped=value=>({code:200,msg:'success',data:value});
async function setup(page,{initial={},packet=F.states.succeeded_partial,hold=null,queue=F.states.queued.detail,getPacket=null,denied=()=>false}={}){
 const calls=[],errors=[];page.on('pageerror',error=>errors.push(error.message));
 await page.addInitScript(value=>{window.__researchVariableAssistantInitial=value;},{feature,initialInput:F.selection,...initial});
 await page.context().route('**/*',route=>new URL(route.request().url()).origin===harness.origin?route.continue():route.abort());
 await page.route('**/api/**',async route=>{
  const request=route.request(),url=new URL(request.url()),path=url.pathname.replace(/^\/api/u,'');calls.push({method:request.method(),path,search:url.searchParams.toString(),body:request.postData()});if(hold)await hold(path,request.method());if(denied(path))return route.fulfill({status:403,json:{detail:'current_source_permission_lost'}});
  if(path==='/ai/research-variables/context')return route.fulfill({json:F.preview});
  if(path===`/ai/research-variables/batches/${batch}/parts/source`)return route.fulfill({json:F.source_parts.source});
  if(path===`/ai/research-variables/batches/${batch}/parts/snapshot`)return route.fulfill({json:F.source_parts.snapshot});
  if(path==='/ai/runs'&&request.method()==='POST')return route.fulfill({json:wrapped(queue)});
  if(path==='/ai/runs'&&request.method()==='GET')return route.fulfill({json:F.history});
  const current=getPacket?getPacket():packet;
  if(path===`/ai/runs/${current.detail.run_id}`)return route.fulfill({json:wrapped(current.detail)});
  for(const[name,value]of Object.entries(current.parts))if(path===`/ai/runs/${current.detail.run_id}/research-variables/${name}`)return route.fulfill({json:value});
  if(path===`/ai/runs/${current.detail.run_id}/feedback`)return route.fulfill({json:F.feedback});
  if(path===`/ai/runs/${F.states.cancelled_pending.detail.run_id}/cancel`)return route.fulfill({json:F.cancel_inflight_receipt});
  return route.fulfill({status:599,json:{detail:'unmocked exact API'}});
 });
 await page.goto(harness.origin);await page.waitForFunction(()=>!!window.__researchVariableAssistantProbe);return {calls,errors};
}
async function inspect(page){await page.getByTestId('variable-inspect').click();await expect(page.getByTestId('variable-preview')).toBeVisible();}
async function generated(page){await inspect(page);await page.getByTestId('variable-submit').click();await expect(page.getByRole('region',{name:'科研变量逐字草稿核对'})).toBeVisible();}
test('actual ordinary preview → queue receipt → full pieces → literal Findings and explicit feedback never call Super Trace',async({page})=>{
 const {calls,errors}=await setup(page);await expect(page.getByTestId('variable-question')).toHaveValue(F.selection.question.replace(/\r\n/gu,'\n'));expect(calls).toEqual([]);
 await generated(page);await expect(page.getByText('逐字候选',{exact:false}).first()).toBeVisible();await page.getByTestId('variable-feedback-comment').fill('人工核对，仍未审核矩阵');await page.getByTestId('variable-feedback').click();await expect(page.getByText('人工复核已记录；未生成已审核矩阵、导出或临床写入。',{exact:true})).toBeVisible();
 const posts=calls.filter(x=>x.method==='POST');expect(posts.map(x=>x.path)).toEqual(['/ai/research-variables/context','/ai/runs',`/ai/runs/${F.states.succeeded_partial.detail.run_id}/feedback`]);expect(JSON.parse(posts[1].body)).toEqual({feature_key:'research_extraction',input:F.selection,preview:false});expect(calls.some(x=>x.path.includes('/admin/'))).toBe(false);expect(errors).toEqual([]);
});
test('same actual Run polls queued → running → success without resubmitting or losing the child during unmount cleanup',async({page})=>{
 let current=F.states.queued;const {calls,errors}=await setup(page,{getPacket:()=>current});await generated(page);await expect(page.getByTestId('variable-cancel')).toBeVisible();current=F.states.running;await expect.poll(()=>calls.filter(x=>x.path===`/ai/runs/${current.detail.run_id}`).length).toBeGreaterThan(1);current=F.states.succeeded_partial;await expect(page.getByTestId('variable-feedback')).toBeVisible();expect(calls.filter(x=>x.path==='/ai/runs'&&x.method==='POST')).toHaveLength(1);expect(errors).toEqual([]);
});
for(const [name,packet]of Object.entries(F.states).filter(([name])=>['succeeded_partial','failed_paid','cancelled_paid','cancelled_uncalled'].includes(name)))test('actual history '+name+' requires a fresh same-ID complete proof and preserves nullable counts',async({page})=>{
 const {calls,errors}=await setup(page,{packet});await page.getByTestId('variable-history').click();await page.getByRole('button',{name:new RegExp(packet.detail.run_id,'u')}).click();await expect(page.getByRole('region',{name:'科研变量逐字草稿核对'})).toBeVisible();expect(calls.some(x=>x.path.endsWith('/research-variables/scope'))).toBe(true);expect(calls.some(x=>x.path.includes('/admin/'))).toBe(false);expect(errors).toEqual([]);
});
for(const initial of [{roles:'admin'},{roles:['nurse']},{roles:['admin',3]},{token:''},{username:''},{patientId:1},{encounterRef:'admission:1'},{initialInput:{research_variable_batch_id:null}},{initialInput:{...F.selection,text:'private source'}},{featureKey:'operations_qa'},{feature:{...feature,input_mode:'generic'}}])test('illegal authority or scope '+JSON.stringify(initial)+' makes zero API requests',async({page})=>{
 const {calls,errors}=await setup(page,{initial});await expect(page.getByTestId('variable-inspect')).toHaveCount(0);expect(calls).toEqual([]);expect(errors).toEqual([]);
});
for(const change of ['token','role','username','active','config','question','batch','close','deactivate'])test('held context POST cannot restore private pieces after '+change,async({page})=>{
 let release;const held=new Promise(resolve=>{release=resolve;});const {calls,errors}=await setup(page,{hold:async path=>{if(path.endsWith('/context'))await held;}});await page.getByTestId('variable-inspect').click();await expect.poll(()=>calls.length).toBe(1);
 if(change==='question')await page.getByTestId('variable-question').fill('different question');else if(change==='batch')await page.getByTestId('variable-batch').fill('00000000-0000-0000-0000-000000000001');else if(change==='close')await page.getByTestId('variable-close').click();else await page.evaluate(change=>{const{scope,store}=window.__researchVariableAssistantProbe;if(change==='token')store.commit('user/token','replacement');if(change==='role')store.commit('user/permissions',['super_admin']);if(change==='username')store.commit('user/username','other-user');if(change==='active')scope.active=false;if(change==='config')scope.feature={...scope.feature,revision:scope.feature.revision+1};if(change==='deactivate')scope.mounted=false;},change);
 release();await expect(page.getByTestId('variable-preview')).toHaveCount(0);await expect(page.getByTestId('variable-private-evidence')).toHaveCount(0);expect(calls.filter(x=>x.path.includes('/parts/'))).toEqual([]);expect(errors).toEqual([]);
});
test('initial question is seeded once for the same session, then token/config changes clear both input and private preview',async({page})=>{
 const {calls,errors}=await setup(page);await inspect(page);await page.evaluate(()=>{const p=window.__researchVariableAssistantProbe;p.store.commit('user/token','replacement');p.scope.feature={...p.scope.feature,revision:2};});await expect(page.getByTestId('variable-question')).toHaveValue('');await expect(page.getByTestId('variable-batch')).toHaveValue('');await expect(page.getByTestId('variable-preview')).toHaveCount(0);expect(calls).toHaveLength(3);expect(errors).toEqual([]);
});
test('token change while feature is null cannot later seed the old initial question when configuration arrives',async({page})=>{
 const {calls,errors}=await setup(page,{initial:{feature:null}});await page.evaluate(feature=>{const p=window.__researchVariableAssistantProbe;p.store.commit('user/token','replacement');p.scope.feature=feature;},feature);await expect(page.getByTestId('variable-question')).toHaveValue('');await expect(page.getByTestId('variable-batch')).toHaveValue('');expect(calls).toEqual([]);expect(errors).toEqual([]);
});
test('same-session first configuration may seed an explicitly supplied initial batch and original question',async({page})=>{
 const {calls,errors}=await setup(page,{initial:{feature:null}});await page.evaluate(feature=>{window.__researchVariableAssistantProbe.scope.feature=feature;},feature);await expect(page.getByTestId('variable-question')).toHaveValue(F.selection.question.replace(/\r\n/gu,'\n'));await expect(page.getByTestId('variable-batch')).toHaveValue(batch);expect(calls).toEqual([]);expect(errors).toEqual([]);
});
for(const question of ['',null,'\u0085\ufeff\r\n　'])test('explicit initial question '+JSON.stringify(question)+' is posted without trimming or converting null/empty',async({page})=>{
 const {calls,errors}=await setup(page,{initial:{initialInput:{research_variable_batch_id:batch,question}}});await page.getByTestId('variable-inspect').click();await expect.poll(()=>calls.length).toBe(3);expect(JSON.parse(calls[0].body)).toEqual({research_variable_batch_id:batch,question});await expect(page.getByTestId('variable-preview')).toHaveCount(0);expect(errors).toEqual([]);
});
test('closing the verified Findings stops polling without a cached result restoring itself',async({page})=>{
 const {calls,errors}=await setup(page);await generated(page);await page.getByRole('button',{name:'关闭并清除科研变量内容',exact:true}).click();await expect(page.getByRole('region',{name:'科研变量逐字草稿核对'})).toHaveCount(0);expect(calls.filter(x=>x.path==='/ai/runs'&&x.method==='POST')).toHaveLength(1);expect(errors).toEqual([]);
});
test('current Source denial on refresh clears the earlier preview as well as the Task body',async({page})=>{
 let deny=false;const {errors}=await setup(page,{denied:path=>deny&&path===`/ai/runs/${F.states.succeeded_partial.detail.run_id}`});await generated(page);deny=true;await page.getByTestId('variable-refresh').click();await expect(page.getByText('完整任务与原批次、问题或实际回执无法核对，请明确重新读取；未回退为通用结果。',{exact:true})).toBeVisible();await expect(page.getByTestId('variable-preview')).toHaveCount(0);await expect(page.getByRole('region',{name:'科研变量逐字草稿核对'})).toHaveCount(0);await expect(page.getByTestId('variable-question')).toHaveValue('');expect(errors).toEqual([]);
});
test('a late complete Run GET cannot start private pieces after the authenticated session changes',async({page})=>{
 let release;const held=new Promise(resolve=>{release=resolve;});const packet=F.states.succeeded_partial,{calls,errors}=await setup(page,{hold:async path=>{if(path===`/ai/runs/${packet.detail.run_id}`)await held;}});await inspect(page);await page.getByTestId('variable-submit').click();await expect.poll(()=>calls.some(x=>x.path===`/ai/runs/${packet.detail.run_id}`)).toBe(true);await page.evaluate(()=>window.__researchVariableAssistantProbe.store.commit('user/token','new-session'));release();await expect(page.getByTestId('variable-preview')).toHaveCount(0);await expect(page.getByRole('region',{name:'科研变量逐字草稿核对'})).toHaveCount(0);expect(calls.filter(x=>x.path.includes('/research-variables/')&&!x.path.includes('/batches/')&&!x.path.endsWith('/context'))).toEqual([]);expect(errors).toEqual([]);
});
test('held real source digest cannot restore the original preview after an explicit close',async({page})=>{
 const {calls,errors}=await setup(page);await page.evaluate(()=>{const original=crypto.subtle.digest.bind(crypto.subtle);window.__variableDigestReached=false;window.__variableDigestHold=new Promise(resolve=>{window.__variableDigestRelease=resolve;});let first=true;crypto.subtle.digest=async(...args)=>{if(first){first=false;window.__variableDigestReached=true;await window.__variableDigestHold;}return original(...args);};});await page.getByTestId('variable-inspect').click();await page.waitForFunction(()=>window.__variableDigestReached);await page.getByTestId('variable-close').click();await page.evaluate(()=>window.__variableDigestRelease());await expect(page.getByTestId('variable-preview')).toHaveCount(0);await page.getByTestId('variable-reopen').click();await expect(page.getByTestId('variable-question')).toHaveValue('');await expect(page.getByTestId('variable-preview')).toHaveCount(0);expect(calls.filter(x=>x.method==='POST'&&x.path==='/ai/runs')).toEqual([]);expect(errors).toEqual([]);
});
