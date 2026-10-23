const {test,expect}=require('@playwright/test');
const fixture=require('./fixtures/task-technical-directory-main.json');
const {startTaskTechnicalHarness}=require('./fixtures/task-technical-directory-harness.cjs');
const actual=fixture.packets.filter(packet=>packet.response?.page_size===30).at(-1).response;
let harness;
test.beforeAll(async()=>{test.setTimeout(90000);harness=await startTaskTechnicalHarness();});
test.afterAll(async({},info)=>{if(!harness)return;try{expect(harness.unhandled).toEqual([]);}finally{await harness.close();await info.attach('technical-directory-isolated-cleanup',{body:JSON.stringify({scope:'isolated_mock actual compiled SFC/API, synthetic store and actual Main packets',closed:!harness.listening,removed:!require('node:fs').existsSync(harness.directory),unhandled:harness.unhandled}),contentType:'application/json'});}});
async function open(page,{roles=['super_admin'],token='synthetic-technical-token',username='synthetic-super',reply=null,hold=null}={}){
 const calls=[],errors=[];page.on('pageerror',error=>errors.push(error.message));
 await page.context().route('**/*',route=>new URL(route.request().url()).origin===harness.origin?route.continue():route.abort());
 await page.route('**/api/**',async route=>{
  const url=new URL(route.request().url()),call={path:url.pathname,method:route.request().method(),query:Object.fromEntries(url.searchParams)};calls.push(call);
  if(hold)await hold(calls.length);
  if(reply)return reply(route,calls.length);
  const packet=structuredClone(actual),q=call.query;
  packet.data=packet.data.filter(row=>(!q.feature_key||(row.native_feature_key||row.feature_key)===q.feature_key)&&(!q.status||row.status===q.status)&&(!q.requested_by||row.requested_by===Number(q.requested_by)));
  packet.total=packet.data.length;packet.page=Number(q.page||1);packet.page_size=Number(q.page_size||30);packet.data=packet.data.slice((packet.page-1)*packet.page_size,packet.page*packet.page_size);
  await route.fulfill({json:packet});
 });
 await page.goto(harness.origin);
 await page.evaluate(({roles,token,username,features})=>{const p=window.__technicalTaskProbe;p.store.commit('user/permissions',roles);p.store.commit('user/token',token);p.store.commit('user/username',username);p.scope.features=features;p.scope.ready=true;},{roles,token,username,features:[...new Map(actual.data.map(row=>[row.feature_key,{key:row.feature_key,name:row.feature_name}])).values()]});
 return{calls,errors};
}
test('actual Main technical records render and details make no Source request',async({page})=>{
 const {calls,errors}=await open(page);await expect(page.locator('.task-technical-directory .el-table__body-wrapper tr')).toHaveCount(actual.data.length);
 await page.getByRole('button',{name:'技术详情',exact:true}).first().click();const dialog=page.getByRole('dialog');await expect(dialog).toContainText('global_ai_task_technical_v1');await expect(dialog).toContainText('"input_tokens": null');
 expect(calls).toHaveLength(1);expect(calls[0].path).toBe('/api/ai/admin/task-directory');expect(calls[0].query).toEqual({page:'1',page_size:'30'});expect(errors).toEqual([]);
});
test('filters send only explicit technical fields and keep native feature selection',async({page})=>{
 const {calls,errors}=await open(page);const row=actual.data.find(row=>row.native_domains.includes('research_variables'));
 await expect(page.getByText(row.run_id,{exact:true})).toBeVisible();await page.locator('.el-select__wrapper').first().click();await page.getByRole('option',{name:row.feature_name,exact:true}).click();await page.locator('.el-input-number input').fill(String(row.requested_by));await page.getByRole('button',{name:'查询技术任务',exact:true}).click();
 await expect.poll(()=>calls.length).toBe(2);expect(calls[1].query).toEqual({page:'1',page_size:'30',feature_key:row.native_feature_key,requested_by:String(row.requested_by)});await expect(page.getByText(row.run_id,{exact:true})).toBeVisible();expect(errors).toEqual([]);
});
test('actual service pagination reaches page two and refresh keeps the selected page',async({page})=>{
 const pages=fixture.service_pages.filter(item=>!item.query.outcome).map(item=>item.response);
 const {calls,errors}=await open(page,{reply:route=>{const number=Number(new URL(route.request().url()).searchParams.get('page')||1);return route.fulfill({json:pages[number-1]});}});
 await expect(page.locator('.task-technical-directory .el-table__body-wrapper tr')).toHaveCount(30);await page.locator('.el-pagination .btn-next').click();await expect(page.getByText(pages[1].data[0].run_id,{exact:true})).toBeVisible();await expect(page.getByText(pages[0].data[0].run_id,{exact:true})).toHaveCount(0);expect(calls[1].query.page).toBe('2');
 await page.getByRole('button',{name:'刷新技术任务',exact:true}).click();await expect.poll(()=>calls.length).toBe(3);expect(calls[2].query.page).toBe('2');await expect(page.getByText(pages[1].data[0].run_id,{exact:true})).toBeVisible();await page.locator('.el-pagination .btn-next').click();await expect(page.locator('.task-technical-directory .el-table__body-wrapper tr')).toHaveCount(7);expect(calls[3].query.page).toBe('3');expect(errors).toEqual([]);
});
test('Source-shaped extra data is rejected and clears an earlier complete page',async({page})=>{
 const {errors}=await open(page,{reply:async(route,count)=>{const packet=structuredClone(actual);if(count>1)packet.data[0].patient_id=777;await route.fulfill({json:packet});}});
 await expect(page.getByText(actual.data[0].run_id,{exact:true})).toBeVisible();await page.getByRole('button',{name:'刷新技术任务',exact:true}).click();await expect(page.getByText(actual.data[0].run_id,{exact:true})).toHaveCount(0);await expect(page.getByText('当前技术目录无法核验，旧记录已清除',{exact:true})).toBeVisible();expect(errors).toEqual([]);
});
for(const axis of ['role','token','username'])test(`held reply cannot restore records after ${axis} loss`,async({page})=>{
 let release;const held=new Promise(resolve=>{release=resolve;});const {calls,errors}=await open(page,{hold:()=>held});await expect.poll(()=>calls.length).toBe(1);
 await page.evaluate(axis=>{const s=window.__technicalTaskProbe.store;s.commit('user/'+(axis==='role'?'permissions':axis),axis==='role'?['admin']:'');},axis);release();await expect(page.locator('.task-technical-directory')).toHaveCount(0);await expect(page.getByText(actual.data[0].run_id,{exact:true})).toHaveCount(0);expect(errors).toEqual([]);
});
for(const options of [{roles:['admin']},{roles:['super_admin',3]},{token:'   '},{username:'   '}])test(`invalid initial authority sends no request ${JSON.stringify(options)}`,async({page})=>{
 const {calls,errors}=await open(page,options);await expect(page.locator('.task-technical-directory')).toHaveCount(0);expect(calls).toEqual([]);expect(errors).toEqual([]);
});
test('role change removes an open technical dialog and all old records',async({page})=>{
 const {errors}=await open(page);await page.getByRole('button',{name:'技术详情',exact:true}).first().click();await expect(page.getByRole('dialog')).toBeVisible();await page.evaluate(()=>window.__technicalTaskProbe.store.commit('user/permissions',['pharmacist']));await expect(page.getByRole('dialog')).toHaveCount(0);await expect(page.getByText(actual.data[0].run_id,{exact:true})).toHaveCount(0);expect(errors).toEqual([]);
});
test('a denied refresh discards the old complete directory',async({page})=>{
 const {errors}=await open(page,{reply:(route,count)=>route.fulfill(count===1?{json:actual}:{status:403,json:{detail:'Forbidden'}})});await expect(page.getByText(actual.data[0].run_id,{exact:true})).toBeVisible();await page.getByRole('button',{name:'刷新技术任务',exact:true}).click();await expect(page.getByText(actual.data[0].run_id,{exact:true})).toHaveCount(0);expect(errors).toEqual([]);
});
test('KeepAlive reentry reloads and unmount rejects a held refresh',async({page})=>{
 let release;const held=new Promise(resolve=>{release=resolve;});const {calls,errors}=await open(page,{hold:count=>count===3?held:Promise.resolve()});await expect(page.getByText(actual.data[0].run_id,{exact:true})).toBeVisible();await page.evaluate(()=>{window.__technicalTaskProbe.scope.mounted=false;});await expect(page.getByText(actual.data[0].run_id,{exact:true})).toHaveCount(0);await page.evaluate(()=>{window.__technicalTaskProbe.scope.mounted=true;});await expect.poll(()=>calls.length).toBe(2);await expect(page.getByText(actual.data[0].run_id,{exact:true})).toBeVisible();await page.getByRole('button',{name:'刷新技术任务',exact:true}).click();await expect.poll(()=>calls.length).toBe(3);await page.evaluate(()=>{window.__technicalTaskProbe.scope.destroyed=true;});release();await expect(page.getByText(actual.data[0].run_id,{exact:true})).toHaveCount(0);expect(errors).toEqual([]);
});
