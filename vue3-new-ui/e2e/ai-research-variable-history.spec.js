const {test,expect}=require('@playwright/test');
const F=require('./fixtures/research-variable-task/actual-states.json');
const {startResearchVariableHistoryHarness}=require('./fixtures/research-variable-history-harness.cjs');
let harness;test.beforeAll(async()=>{harness=await startResearchVariableHistoryHarness();});test.afterAll(async()=>{await harness?.close();});
const batch=F.selection.research_variable_batch_id;
async function open(page,{roles=['super_admin'],token='synthetic-variables-history',username='synthetic-super',mutateTrace=null,hold=null,mutateDirectory=null,overridePacket=null}={}){
 const calls=[],errors=[];page.on('pageerror',error=>errors.push(error.message));
 await page.context().route('**/*',route=>new URL(route.request().url()).origin===harness.origin?route.continue():route.abort());
 await page.route('**/api/**',async route=>{
  const path=new URL(route.request().url()).pathname.replace(/^\/api/u,''),query=Object.fromEntries(new URL(route.request().url()).searchParams);calls.push({path,method:route.request().method(),query});if(hold)await hold(path);
  if(path==='/ai/admin/runs'){const directory=structuredClone(F.admin_history);if(mutateDirectory)mutateDirectory(directory);return route.fulfill({json:directory});}
  for(const row of F.admin_history.data){
   let packet=Object.values(F.states).find(value=>value.detail.run_id===row.run_id&&value.detail.status===row.status&&value.detail.research_variable_artifact.usage_event_id===row.research_variable_artifact.usage_event_id);if(overridePacket)packet=overridePacket(packet);
   if(path===`/ai/admin/runs/${packet.detail.run_id}`){const trace=structuredClone(packet.trace);if(mutateTrace)mutateTrace(trace);return route.fulfill({json:{code:200,msg:'success',data:trace}});}
   for(const[name,value]of Object.entries(packet.parts))if(path===`/ai/admin/runs/${packet.detail.run_id}/research-variables/${name}`)return route.fulfill({json:value});
  }
  return route.fulfill({status:599,json:{detail:'unmocked exact history API'}});
 });
 await page.goto(harness.origin);await page.waitForFunction(()=>!!window.__researchVariableHistoryProbe);
 await page.evaluate(({roles,token,username,features})=>{const p=window.__researchVariableHistoryProbe;p.store.commit('user/permissions',roles);p.store.commit('user/token',token);p.store.commit('user/username',username);p.scope.features=features;p.scope.ready=true;},{roles,token,username,features:F.features.data});
 return {calls,errors};
}
async function inspect(page,packet){const index=F.admin_history.data.findIndex(row=>row.run_id===packet.detail.run_id);expect(index).toBeGreaterThanOrEqual(0);await page.getByRole('button',{name:'执行溯源',exact:true}).nth(index).click();}
for(const[name,packet]of Object.entries(F.states).filter(([name])=>['succeeded_partial','failed_paid','cancelled_paid','cancelled_uncalled'].includes(name)))test('actual Super History '+name+' requires full raw Trace and all independent bare pieces',async({page})=>{
 const {calls,errors}=await open(page);await inspect(page,packet);await expect(page.getByLabel('科研变量冻结审计')).toBeVisible();await expect(page.getByRole('region',{name:'科研变量逐字草稿核对'})).toBeVisible();await expect(page.getByLabel('科研变量任务状态')).toHaveText({succeeded:'草稿已接收，未审核',failed:'任务失败',cancelled:'已取消'}[packet.detail.status]);await expect(page.getByRole('button',{name:'明确保存人工复核',exact:true})).toHaveCount(0);expect(calls.some(x=>x.path.endsWith('/research-variables/scope'))).toBe(true);expect(calls.every(x=>x.method==='GET')).toBe(true);expect(calls.some(x=>/^\/ai\/runs\//u.test(x.path))).toBe(false);expect(errors).toEqual([]);
});
test('actual partial token reporting preserves known input and unknown output in the global directory',async({page})=>{
 const {errors}=await open(page);await expect(page.locator('tbody')).toContainText('11 / 未报告');await expect(page.locator('tbody')).toContainText('0 / 0');expect(errors).toEqual([]);
});
for(const change of ['raw_json','foreign','pointer','provider','source'])test('frozen '+change+' corruption never reaches a generic summary or raw Prompt',async({page})=>{
 const {errors}=await open(page,{mutateTrace:trace=>{if(change==='raw_json')trace.raw_frozen_json.input_json+=' ';if(change==='foreign')trace.run.nursing_findings={summary:'PRIVATE_FOREIGN_SENTINEL'};if(change==='pointer')trace.run.result_reference.result_hash='0'.repeat(64);if(change==='provider')trace.frozen_request.provider_snapshot.allows_patient_data=false;if(change==='source')trace.research_variable_artifact.source_hash='0'.repeat(64);}});await inspect(page,F.states.succeeded_partial);await expect(page.getByText('当前完整任务或审计权限无法重新核对，旧资料已清除',{exact:true})).toBeVisible();await expect(page.getByRole('region',{name:'科研变量逐字草稿核对'})).toHaveCount(0);await expect(page.locator('body')).not.toContainText('PRIVATE_FOREIGN_SENTINEL');expect(await page.evaluate(()=>window.__researchVariableHistoryProbe.trace.$.setupState.detail)).toBeNull();expect(errors).toEqual([]);
});
for(const auth of [{roles:'super_admin'},{roles:['super_admin',3]},{roles:['admin']},{token:' '},{username:''}])test('invalid global audit authority '+JSON.stringify(auth)+' makes zero requests',async({page})=>{
 const {calls,errors}=await open(page,auth);await expect(page.getByRole('button',{name:'执行溯源',exact:true})).toHaveCount(0);expect(calls).toEqual([]);expect(errors).toEqual([]);
});
test('native audit filtering uses the exact Batch UUID and rejects foreign patient scope before request',async({page})=>{
 const {calls,errors}=await open(page);await expect(page.getByRole('button',{name:'执行溯源',exact:true}).first()).toBeVisible();await page.evaluate(batch=>{const s=window.__researchVariableHistoryProbe.trace.$.setupState;s.filters.patient_id=1;s.filters.feature_key='research_extraction';s.filters.research_variable_batch_id=batch;s.load();},batch);await expect.poll(()=>calls.length).toBe(2);expect(calls[1].query).toEqual({feature_key:'research_extraction',research_variable_batch_id:batch,page:'1',page_size:'30'});await page.evaluate(()=>{const s=window.__researchVariableHistoryProbe.trace.$.setupState;s.filters.patient_id=1;s.load();});await expect(page.getByText('科研变量审计仅接受原批次及明确技术过滤，不接受患者或其他来源',{exact:true})).toBeVisible();expect(calls).toHaveLength(2);expect(errors).toEqual([]);
});
test('a malformed native directory cannot populate generic rows even with its own code200 wrapper',async({page})=>{
 let corrupt=false;const {calls,errors}=await open(page,{mutateDirectory:value=>{if(corrupt)value.data[0].feature_key='operations_qa';}});await expect(page.getByRole('button',{name:'执行溯源',exact:true}).first()).toBeVisible();corrupt=true;await page.evaluate(()=>{const s=window.__researchVariableHistoryProbe.trace.$.setupState;s.filters.feature_key='research_extraction';s.load();});await expect(page.getByText('当前任务目录或审计权限无法重新核对，旧资料已清除',{exact:true})).toBeVisible();await expect(page.getByRole('button',{name:'执行溯源',exact:true})).toHaveCount(0);expect(calls).toHaveLength(2);expect(errors).toEqual([]);
});
for(const change of ['token','filter','deactivate'])test('complete frozen proof clears on '+change+' and cannot be silently reused',async({page})=>{
 const {errors}=await open(page);await inspect(page,F.states.succeeded_partial);await expect(page.getByLabel('科研变量冻结审计')).toBeVisible();await page.evaluate(change=>{const p=window.__researchVariableHistoryProbe;p.retained=p.trace;if(change==='token')p.store.commit('user/token','replacement');if(change==='filter')p.trace.$.setupState.filters.research_variable_batch_id='00000000-0000-0000-0000-000000000001';if(change==='deactivate')p.scope.mounted=false;},change);await expect(page.getByRole('region',{name:'科研变量逐字草稿核对'})).toHaveCount(0);expect(await page.evaluate(()=>window.__researchVariableHistoryProbe.retained.$.setupState.variableBundle)).toBeNull();expect(errors).toEqual([]);
});
test('closing History while complete Trace GET is held prevents later part requests and restoration',async({page})=>{
 let release;const held=new Promise(resolve=>{release=resolve;}),packet=F.states.succeeded_partial;const {calls,errors}=await open(page,{hold:async path=>{if(path===`/ai/admin/runs/${packet.detail.run_id}`)await held;}});await inspect(page,packet);await expect.poll(()=>calls.some(x=>x.path===`/ai/admin/runs/${packet.detail.run_id}`)).toBe(true);await page.getByRole('dialog',{name:'AI 任务执行溯源',exact:true}).locator('.el-dialog__headerbtn').click();release();await expect(page.getByRole('region',{name:'科研变量逐字草稿核对'})).toHaveCount(0);expect(calls.filter(x=>x.path.includes('/research-variables/'))).toEqual([]);expect(errors).toEqual([]);
});
test('the explicit Findings close clears the global parent trace and all bare piece refs',async({page})=>{
 const {errors}=await open(page);await inspect(page,F.states.succeeded_partial);await expect(page.getByLabel('科研变量冻结审计')).toBeVisible();await page.getByRole('button',{name:'关闭并清除科研变量内容',exact:true}).click();await expect(page.getByRole('dialog',{name:'AI 任务执行溯源',exact:true})).toHaveCount(0);expect(await page.evaluate(()=>window.__researchVariableHistoryProbe.trace.$.setupState.variableBundle)).toBeNull();expect(errors).toEqual([]);
});
test('a terminal directory observation cannot be downgraded to the earlier actual queued Trace and all its old pieces',async({page})=>{
 const {errors}=await open(page,{overridePacket:packet=>packet.detail.run_id===F.states.succeeded_partial.detail.run_id?F.states.queued:packet});await inspect(page,F.states.succeeded_partial);await expect(page.getByText('当前完整任务或审计权限无法重新核对，旧资料已清除',{exact:true})).toBeVisible();await expect(page.getByRole('region',{name:'科研变量逐字草稿核对'})).toHaveCount(0);expect(errors).toEqual([]);
});
