const{test,expect}=require('@playwright/test');
const{beforeSourceHarness}=require('./fixtures/source-harness-setup.cjs');
const{startChargeParentHarness}=require('./fixtures/charge-parent-harness.cjs');
let h;beforeSourceHarness(test,async()=>{h=await startChargeParentHarness({mode:'parent'})});test.afterAll(async()=>h?.close());
const id='11111111-1111-4111-8111-111111111111';
const feature={key:'synthetic_llm_error',number:1,name:'合成文本任务',scope:'input',engine:'llm',enabled:true,inputs:[],deliverables:[],allowed_roles:['super_admin'],validation_status:'validated'};
async function open(page,{post='ok',getStatus=200,state='running',terminalMessage=''}={}){
 const s={writes:0,reads:0,history:0,post,getStatus,state,errors:[]};page.on('pageerror',e=>s.errors.push(e.message));
 await page.route('**/api/**',async route=>{const q=route.request(),path=new URL(q.url()).pathname;let data;
  if(path==='/api/ai/features')data=[feature];
  else if(path==='/api/ai/runs'&&q.method()==='POST'){s.writes++;if(s.post==='lost')return route.abort('failed');data=run('queued');}
  else if(path==='/api/ai/runs'){s.history++;data=[];}
  else if(path==='/api/ai/runs/'+id){s.reads++;if(s.getStatus!==200)return route.fulfill({status:s.getStatus,headers:{'retry-after':'0'},json:{detail:s.getStatus===403?'当前权限不足。':'服务维护中，请稍后查询。'}});data=run(s.state);}
  else throw Error('Unexpected API '+path);
  await route.fulfill({json:{code:200,data}});
 });
 function run(status){return{run_id:id,feature_key:feature.key,feature_name:feature.name,status,patient_id:null,encounter_ref:null,preview:0,prompt_version:1,provider_revision:1,tool_findings:{},result:status==='succeeded'?{summary:'本次已恢复的合成结果',sections:[],warnings:[],missing_data:[]}:null,error_code:status==='failed'?'PROVIDER_HTTP_ERROR':null,error_message:status==='failed'?terminalMessage:null};}
 await page.goto(h.origin);await page.evaluate(feature=>Object.assign(window.__chargeParentProbe.scope,{featureKeys:[feature.key],initialFeature:feature.key,initialInput:{},ready:true}),feature);
 await expect(page.getByRole('button',{name:'生成辅助建议',exact:true})).toBeEnabled();return s;
}
test('a failed status query pauses visibly and resumes the same task using only GET',async({page})=>{
 const s=await open(page,{getStatus:503});await page.getByRole('button',{name:'生成辅助建议',exact:true}).click();
 await expect(page.getByText('状态查询暂停：服务维护中，请稍后查询。',{exact:true})).toBeVisible();
 await expect(page.getByText('任务已保存，正在等待处理或生成结果。',{exact:true})).toHaveCount(0);
 const reads=s.reads;await page.waitForTimeout(2200);expect(s.reads).toBe(reads);expect(s.writes).toBe(1);
 s.getStatus=200;s.state='succeeded';await page.getByRole('button',{name:'继续查询任务状态',exact:true}).click();
 await expect(page.getByText('本次已恢复的合成结果',{exact:true})).toBeVisible();await expect(page.getByRole('region',{name:'AI请求提示'})).toHaveCount(0);expect(s.writes).toBe(1);expect(s.errors).toEqual([]);
});
test('an unknown POST receipt blocks identical manual retries and opens read-only task records',async({page})=>{
 const s=await open(page,{post:'lost'});await page.getByRole('button',{name:'生成辅助建议',exact:true}).click();
 await expect(page.getByText('提交结果尚未确认，请先查看任务记录；相同资料暂不重复提交。',{exact:true})).toBeVisible();
 await page.getByRole('button',{name:'生成辅助建议',exact:true}).click();expect(s.writes).toBe(1);
 await page.getByRole('button',{name:'查看任务记录',exact:true}).click();await expect.poll(()=>s.history).toBeGreaterThan(0);
 await expect(page.getByText('当前范围暂无历史任务',{exact:true})).toBeVisible();expect(s.writes).toBe(1);expect(s.errors).toEqual([]);
});
test('a real terminal failure shows its readable cause with diagnostics instead of a success card',async({page})=>{
 const s=await open(page,{state:'failed',terminalMessage:'模型服务繁忙（HTTP 429，尝试 3/3），请稍后提交。'});await page.getByRole('button',{name:'生成辅助建议',exact:true}).click();
 await expect(page.getByText('模型服务繁忙（HTTP 429，尝试 3/3），请稍后提交。',{exact:true})).toBeVisible();
 await page.getByText('技术详情',{exact:true}).click();await expect(page.getByText('PROVIDER_HTTP_ERROR · HTTP 429 · 尝试 3/3',{exact:true})).toBeVisible();
 await expect(page.getByRole('button',{name:'复制草稿',exact:true})).toHaveCount(0);const reads=s.reads;await page.waitForTimeout(2200);expect(s.reads).toBe(reads);expect(s.writes).toBe(1);expect(s.errors).toEqual([]);
});
test('a forbidden query removes task content, preserves login and never repeats the POST',async({page})=>{
 const s=await open(page,{getStatus:403});await page.getByRole('button',{name:'生成辅助建议',exact:true}).click();
 await expect(page.getByText('当前账号没有此项操作权限，请联系管理员调整授权。',{exact:true})).toBeVisible();
 await expect(page.getByRole('region',{name:'AI任务结果'})).toHaveCount(0);expect(await page.evaluate(()=>window.__chargeParentProbe.store.state.user.accessToken)).toBe('synthetic-charge-parent-session');expect(s.writes).toBe(1);expect(s.reads).toBe(1);expect(s.errors).toEqual([]);
});
test('an expired query clears the old task and invokes the existing login-expiry path without POST replay',async({page})=>{
 const s=await open(page,{getStatus:401});await page.getByRole('button',{name:'生成辅助建议',exact:true}).click();
 await expect.poll(()=>page.evaluate(()=>window.__chargeParentProbe.store.state.user.accessToken)).toBe('');await expect(page.getByRole('region',{name:'AI任务结果'})).toHaveCount(0);expect(s.writes).toBe(1);expect(s.reads).toBe(1);
});
