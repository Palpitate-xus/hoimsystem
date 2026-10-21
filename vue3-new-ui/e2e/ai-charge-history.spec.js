const{test,expect}=require('@playwright/test'),{load}=require('./fixtures/load-charge-assistant.cjs'),{startChargeParentHarness}=require('./fixtures/charge-parent-harness.cjs');
let harness;test.beforeAll(async()=>{harness=await startChargeParentHarness({mode:'history'});});test.afterAll(async()=>{await harness?.close();});
async function setup(page,config={}){
 const packet=load(config.profile||'chat'),name=config.state||'succeeded',task=packet.states[name],row=config.row||packet.admin_history.data.find(row=>row.run_id===task.detail.data.run_id),errors=[],calls=[],held={},completed=[];
 const state={packet,task,row,errors,calls,held,completed,...config};
 page.on('pageerror',e=>errors.push(e.message));await page.context().route('**/*',route=>new URL(route.request().url()).origin===harness.origin?route.continue():route.abort());
 await page.route('**/api/**',async route=>{
  const req=route.request(),url=new URL(req.url()),path=url.pathname;calls.push({path,method:req.method(),query:Object.fromEntries(url.searchParams)});
  let response;if(path==='/api/ai/admin/runs')response={...packet.admin_history,data:[row],total:1};
  else if(path==='/api/ai/admin/runs/'+row.run_id)response={...task.trace,data:structuredClone(state.trace||task.trace.data)};
  else if(path==='/api/ai/runs/'+row.run_id)response={...task.detail,data:structuredClone(state.full||task.detail.data)};
  else{errors.push('Unhandled isolated '+req.method()+' '+path);await route.fulfill({status:599,json:{code:599,msg:'Missing explicit synthetic route'}});return;}
  const key=state.hold?.(path);if(key)await new Promise(resolve=>held[key]=resolve);
  const failed=state.failure?.(path);try{await route.fulfill(failed?{status:failed,json:{code:failed,msg:'合成当前授权或来源不可用'}}:{json:response});}finally{if(key)completed.push(key);}
 });
 await page.goto(harness.origin);await page.waitForFunction(()=>!!window.__chargeParentProbe);
 await page.evaluate(({features,role})=>{const p=window.__chargeParentProbe;p.store.commit('user/permissions',[role]);Object.assign(p.scope,{features,ready:true});},{features:[packet.feature],role:config.role||'super_admin'});
 if(config.role!=='admin')await expect(page.getByRole('button',{name:'执行溯源',exact:true})).toBeVisible();return state;
}
async function inspect(page){await page.getByRole('button',{name:'执行溯源',exact:true}).click();}
async function accepted(page){await expect(page.getByLabel('完整住院账目证据与待核实问题',{exact:true})).toBeVisible();await expect(page.getByLabel('本件账目可见哈希范围')).toContainText('已逐字核对',{timeout:15000});}
async function cleared(page){await expect(page.getByRole('dialog',{name:'AI 任务执行溯源',exact:true})).not.toBeVisible();expect(await page.evaluate(()=>{const s=window.__chargeParentProbe.target.$.setupState;return[s.detail,s.chargeRun,s.evidence];})).toEqual([null,null,null]);}
for(const profile of ['chat','responses'])test(`${profile}: Super history pairs actual full detail and original JSON trace before exposing questions`,async({page})=>{
 const s=await setup(page,{profile});await inspect(page);await accepted(page);await page.getByRole('button',{name:'展开Super原始任务字节',exact:true}).click();await expect(page.getByLabel('Super原始任务JSON字节')).toContainText('input_json');await page.getByRole('tab',{name:'调用时 Prompt',exact:true}).click();await expect(page.getByRole('dialog',{name:'AI 任务执行溯源'})).toContainText(s.task.trace.data.frozen_request.task_prompt);await page.getByRole('tab',{name:'人工反馈',exact:true}).click();await expect(page.getByRole('dialog',{name:'AI 任务执行溯源'})).toContainText('<img');expect(await page.locator('img[src=x]').count()).toBe(0);expect(s.calls.filter(c=>c.path==='/api/ai/runs/'+s.row.run_id)).toHaveLength(1);expect(s.errors).toEqual([]);
});
for(const state of ['failed','cancelled_zero','cancelled_paid'])test(`history ${state} preserves original unknown and known zero token counts`,async({page})=>{
 const s=await setup(page,{state}),u=s.task.detail.data.usage_receipt;await expect(page.locator('.el-table__body-wrapper').first()).toContainText([u.input_tokens,u.output_tokens].map(v=>v===null?'未报告':String(v)).join(' / '));await inspect(page);await accepted(page);expect(s.errors).toEqual([]);
});
for(const mutation of ['foreign_run','foreign_feature','foreign_full','missing_native_proof','raw_change','foreign_case'])test(`history rejects ${mutation} without displaying frozen input`,async({page})=>{
 const p=load('chat'),trace=structuredClone(p.states.succeeded.trace.data),full=structuredClone(p.states.succeeded.detail.data);
 if(mutation==='foreign_run')trace.run_id=p.states.failed.trace.data.run_id;
 if(mutation==='foreign_feature')trace.feature_key='patient_summary';
 if(mutation==='foreign_full')full.run_id=p.states.failed.detail.data.run_id;
 if(mutation==='missing_native_proof'){delete trace.charge_artifact;delete trace.charge_findings;}
 if(mutation==='raw_change')trace.raw_frozen_json.input_json+=' ';
 if(mutation==='foreign_case')trace.charge_case_id=trace.run_id;
 await setup(page,{trace,full});await inspect(page);await expect(page.getByText('原任务或完整冻结来源及固定结果无法核对，暂不展示',{exact:true})).toBeVisible();expect(await page.getByLabel('本件账目可见哈希范围').count()).toBe(0);expect(await page.getByText('固定系统 Prompt',{exact:true}).count()).toBe(0);
});
for(const status of [403,409])test(`current detail ${status} clears trace and both full snapshots`,async({page})=>{
 await setup(page,{failure:path=>path.startsWith('/api/ai/runs/')?status:null});await inspect(page);await expect(page.getByText('当前完整任务或审计权限无法重新核对，旧资料已清除',{exact:true})).toBeVisible();await cleared(page);
});
for(const change of ['token','username','permissions','active','deactivate','unmount','filter'])test(`history ${change} clears accepted source and private raw text`,async({page})=>{
 await setup(page);await inspect(page);await accepted(page);await page.getByRole('button',{name:'展开完整院内账目原件',exact:true}).click();await expect(page.getByLabel('完整院内冻结账目原件')).toBeVisible();
 await page.evaluate(change=>{const p=window.__chargeParentProbe;if(change==='permissions')p.store.commit('user/permissions',['admin']);else if(change==='token'||change==='username')p.store.commit('user/'+change,'changed');else if(change==='deactivate')p.scope.mounted=false;else if(change==='unmount')p.scope.destroyed=true;else if(change==='filter')p.target.$.setupState.filters.patient_id=2;else p.scope.active=false;},change);
 await expect(page.getByLabel('完整院内冻结账目原件')).toHaveCount(0);if(!['unmount','deactivate'].includes(change))await cleared(page);
});
test('closing trace during a pending full task read rejects the late body',async({page})=>{
 const s=await setup(page,{hold:path=>path.startsWith('/api/ai/runs/')?'detail':null});await inspect(page);await expect.poll(()=>!!s.held.detail).toBe(true);await page.getByRole('dialog',{name:'AI 任务执行溯源'}).getByRole('button',{name:'Close this dialog',exact:true}).click();s.held.detail();await expect.poll(()=>s.completed.includes('detail')).toBe(true);await cleared(page);
});
test('closing trace while real WebCrypto is pending clears before transition and rejects digest completion',async({page})=>{
 await setup(page);await page.evaluate(()=>{const p=window.__chargeParentProbe,original=crypto.subtle.digest.bind(crypto.subtle);p.started=false;p.release=null;crypto.subtle.digest=async(...args)=>{if(!p.started){p.started=true;await new Promise(resolve=>p.release=resolve);}return original(...args);};});await inspect(page);await expect.poll(()=>page.evaluate(()=>window.__chargeParentProbe.started)).toBe(true);await page.getByRole('dialog',{name:'AI 任务执行溯源'}).getByRole('button',{name:'Close this dialog',exact:true}).click();await page.evaluate(()=>window.__chargeParentProbe.release());await cleared(page);
});
test('ordinary admin never loads Super history endpoints',async({page})=>{const s=await setup(page,{role:'admin'});await expect(page.getByRole('button',{name:'查询任务',exact:true})).toHaveCount(0);expect(s.calls).toEqual([]);expect(s.errors).toEqual([]);});
test('legacy stored zero metadata remains unreported without a native receipt',async({page})=>{const p=load('chat'),row={...p.admin_history.data.find(r=>r.run_id===p.states.succeeded.detail.data.run_id),input_tokens:0,output_tokens:0};delete row.charge_case_id;delete row.usage_receipt;delete row.usage_receipt_status;await setup(page,{row});await expect(page.locator('.el-table__body-wrapper').first()).toContainText('未报告');await expect(page.locator('.el-table__body-wrapper').first()).not.toContainText('0 / 0');});
