const {test,expect}=require('@playwright/test');
const fixture=require('./fixtures/document-change-result/actual.json');
const {startDocumentChangeAssistantHarness}=require('./fixtures/document-change-assistant-harness.cjs');
const feature=fixture.live.features.data.find(f=>f.key==='guideline_change_review'),scopeId=fixture.live.scope.data.snapshot.scope_id;
let harness;test.beforeAll(async()=>{harness=await startDocumentChangeAssistantHarness();});test.afterAll(async()=>{await harness?.close();});
async function setup(page,{state='succeeded',initial={},mutate=null,hold=null}={}){
 const calls=[],v=fixture.states[state];let release;
 await page.addInitScript(value=>window.__documentChangeAssistantInitial=value,{feature,initialInput:{question:fixture.requests.create.input.question},...initial});
 await page.route('**/api/**',async route=>{const r=route.request(),u=new URL(r.url()),path=u.pathname,method=r.method();calls.push({path,method,query:Object.fromEntries(u.searchParams),body:r.postDataJSON()});let response;
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
 await page.goto(harness.origin);await page.waitForFunction(()=>!!window.__documentChangeAssistantProbe);return {calls,get release(){return release;}};
}
async function choose(page){const row=page.getByRole('row').filter({hasText:scopeId});await row.getByRole('button',{name:'读取完整件并选择',exact:true}).click();await expect(page.getByLabel('已核对完整双原文范围')).toBeVisible();await page.getByText('明确以超级管理员试运行',{exact:true}).click();await expect(page.getByRole('button',{name:'生成未核实核对问题',exact:true})).toBeEnabled();}
for(const state of ['queued','running','succeeded','failed','cancelled'])test(`actual ${state} short receipt expands same run into all independently verified split pieces`,async({page})=>{
 const errors=[];page.on('pageerror',e=>errors.push(e.message));const {calls}=await setup(page,{state});await choose(page);await page.getByRole('button',{name:'生成未核实核对问题',exact:true}).click();await expect(page.getByText('已比对当前范围与完整冻结原件。',{exact:true})).toBeVisible();expect(calls.filter(x=>x.method==='POST'&&x.path==='/api/ai/runs')).toHaveLength(1);expect(calls.find(x=>x.method==='POST'&&x.path==='/api/ai/runs').body).toEqual({feature_key:'guideline_change_review',input:fixture.requests.create.input,preview:true});if(state==='succeeded')await expect(page.getByText('请人工核对原文适用性？',{exact:true})).toBeVisible();else await expect(page.getByText(/本状态没有已接受的问题正文/)).toBeVisible();expect(errors).toEqual([]);
});
test('actual short preview binds whole public source and human scope, close clears evidence without a submit',async({page})=>{
 const {calls}=await setup(page);await choose(page);await page.getByRole('button',{name:'预览双原文与有限范围',exact:true}).click();await expect(page.getByText('只有完整公开双原文投影与该问题发送给模型；私有目标原件保留院内。',{exact:true})).toBeVisible();await page.getByRole('button',{name:'展开完整双原文证据',exact:true}).click();await expect(page.locator('.el-dialog pre')).toHaveCount(2);await page.locator('.el-dialog__headerbtn').click();await expect(page.locator('.el-dialog pre')).toHaveCount(0);expect(calls.filter(c=>c.path==='/api/ai/runs'&&c.method==='POST')).toHaveLength(0);
});
for(const mutation of ['receipt_digest','full_id','trace_id','private_hash','foreign_findings'])test(`task refuses ${mutation} and never renders unproved body`,async({page})=>{
 const v=fixture.states.succeeded;const {calls}=await setup(page,{mutate:({path,method,response})=>{if(mutation==='receipt_digest'&&method==='POST'&&path==='/api/ai/runs')response.data.context_digest='f'.repeat(64);if(mutation==='full_id'&&path===`/api/ai/runs/${v.detail.data.run_id}`)response.data.run_id=fixture.states.failed.detail.data.run_id;if(mutation==='trace_id'&&path===`/api/ai/admin/runs/${v.detail.data.run_id}`)response.data.run_id=fixture.states.failed.detail.data.run_id;if(mutation==='private_hash'&&path.endsWith('/document-change/scope'))response.data.scope_snapshot.inventory.targets[0].columns.steps='tampered';if(mutation==='foreign_findings'&&path===`/api/ai/runs/${v.detail.data.run_id}`)response.data.nursing_findings={limitations:['FOREIGN_SENTINEL']};return response;}});await choose(page);await page.getByRole('button',{name:'生成未核实核对问题',exact:true}).click();await expect(page.getByText(/完整任务、原件、冻结Prompt或逐字证明未能核对/)).toBeVisible();await expect(page.getByText('请人工核对原文适用性？',{exact:true})).toHaveCount(0);await expect(page.getByText('FOREIGN_SENTINEL',{exact:true})).toHaveCount(0);expect(calls.filter(c=>c.method==='POST'&&c.path==='/api/ai/runs')).toHaveLength(1);
});
test('history uses immutable selected Scope filter, then fetches full run, trace and split proofs before display',async({page})=>{
 const {calls}=await setup(page);await choose(page);await page.getByRole('button',{name:'读取此范围任务历史',exact:true}).click();const id=fixture.states.succeeded.detail.data.run_id;await page.getByRole('button',{name:'打开原任务 '+id,exact:true}).click();await expect(page.getByText('请人工核对原文适用性？',{exact:true})).toBeVisible();expect(calls.find(c=>c.method==='GET'&&c.path==='/api/ai/runs').query).toEqual({feature_key:'guideline_change_review',document_change_scope_id:scopeId});expect(calls.some(c=>c.path.endsWith('/document-change/result'))).toBe(true);expect(calls.some(c=>c.method==='POST'&&c.path==='/api/ai/runs')).toBe(false);
});
for(const mutation of ['token','roles','username','inactive','deactivate','close'])test(`accepted private task clears on ${mutation} without restoring initial question or Scope`,async({page})=>{
 await setup(page);await choose(page);await page.getByRole('button',{name:'生成未核实核对问题',exact:true}).click();await expect(page.getByText('请人工核对原文适用性？',{exact:true})).toBeVisible();if(mutation==='close')await page.getByRole('button',{name:'关闭并清除双原文任务',exact:true}).click();else await page.evaluate(m=>{const p=window.__documentChangeAssistantProbe;if(m==='token')p.store.commit('user/token','changed-token');if(m==='roles')p.store.commit('user/permissions',['admin']);if(m==='username')p.store.commit('user/username','changed-user');if(m==='inactive')p.scope.active=false;if(m==='deactivate')p.scope.mounted=false;},mutation);await expect(page.getByText('请人工核对原文适用性？',{exact:true})).toHaveCount(0);expect(await page.evaluate(()=>window.__documentChangeAssistantProbe.scope.target?.$.setupState.question||'')).toBe('');
});
for(const initial of [{featureKey:'patient_summary',initialInput:{document_change_scope_id:scopeId}},{feature:{...feature,input_mode:'llm'}},{patientId:1},{encounterRef:'foreign'},{initialInput:{document_change_scope_id:null}},{initialInput:{document_change_scope_id:scopeId,patient_id:1}},{roles:'super_admin'},{token:''}])test(`invalid mode, scope or identity produces zero task or Source requests: ${JSON.stringify(initial)}`,async({page})=>{
 const {calls}=await setup(page,{initial});await expect(page.getByRole('button',{name:'生成未核实核对问题',exact:true})).toHaveCount(0);expect(calls).toEqual([]);
});
for(const phase of ['post','detail','trace'])test(`held ${phase} reply cannot restore private task after session replacement`,async({page})=>{
 const id=fixture.states.succeeded.detail.data.run_id,config={hold:({path,method})=>phase==='post'?method==='POST'&&path==='/api/ai/runs':phase==='detail'?method==='GET'&&path===`/api/ai/runs/${id}`:method==='GET'&&path===`/api/ai/admin/runs/${id}`};const state=await setup(page,config);await choose(page);await page.getByRole('button',{name:'生成未核实核对问题',exact:true}).click();await expect.poll(()=>typeof state.release).toBe('function');await page.evaluate(()=>window.__documentChangeAssistantProbe.store.commit('user/token','replacement-session'));state.release();await expect(page.getByText('请人工核对原文适用性？',{exact:true})).toHaveCount(0);expect(await page.evaluate(()=>window.__documentChangeAssistantProbe.scope.target.$.setupState.bundle)).toBeNull();
});
test('late first feature configuration cannot reseed old private initial question after authentication changes',async({page})=>{
 await setup(page,{initial:{feature:null,initialInput:{question:'PRIVATE_INITIAL_SENTINEL',document_change_scope_id:scopeId}}});await page.evaluate(()=>window.__documentChangeAssistantProbe.store.commit('user/token','new-before-feature'));await page.evaluate(feature=>window.__documentChangeAssistantProbe.scope.feature=feature,feature);await expect(page.getByLabel('双原文可选问题',{exact:true})).toHaveValue('');expect(await page.evaluate(()=>window.__documentChangeAssistantProbe.scope.target.$.setupState.selection)).toBeNull();
});
test('real queued-to-cancelled progress between GET and trace uses bounded reads without posting again',async({page})=>{
 let reads=0;const id=fixture.states.cancelled.detail.data.run_id,{calls}=await setup(page,{state:'cancelled',mutate:({path,method,response})=>method==='GET'&&path===`/api/ai/runs/${id}`&&reads++===0?structuredClone(fixture.states.queued.detail):response});await choose(page);await page.getByRole('button',{name:'生成未核实核对问题',exact:true}).click();await expect(page.getByText('已证明未调用',{exact:true})).toBeVisible();expect(reads).toBe(2);expect(calls.filter(c=>c.method==='POST'&&c.path==='/api/ai/runs')).toHaveLength(1);
});
test('human feedback is posted only on an explicit click and leaves targets and knowledge untouched',async({page})=>{
 const {calls}=await setup(page);await choose(page);await page.getByRole('button',{name:'生成未核实核对问题',exact:true}).click();await expect(page.getByText('请人工核对原文适用性？',{exact:true})).toBeVisible();expect(calls.filter(c=>c.path.endsWith('/feedback'))).toHaveLength(0);await page.getByRole('button',{name:'明确保存人工反馈',exact:true}).click();await expect(page.getByText('已明确保存人工反馈；未确认临床影响，也未修改或发布规则。',{exact:true})).toBeVisible();expect(calls.find(c=>c.path.endsWith('/feedback')).body).toEqual({outcome:'accepted',comment:''});expect(calls.some(c=>c.method==='POST'&&/document-changes|knowledge|clinicalPathway/u.test(c.path))).toBe(false);
});
