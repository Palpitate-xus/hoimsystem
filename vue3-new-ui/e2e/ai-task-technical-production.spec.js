const { expectManagementEntry, selectManagementTab } = require('./fixtures/ai-management-navigation.cjs');
const {test,expect}=require('@playwright/test');
const {startCodingProductionServer}=require('./fixtures/coding-production-entry.cjs');
const fixture=require('./fixtures/task-technical-directory-main.json');
const usageFixture=require('./fixtures/usage-summary-main.json'),usageActual=usageFixture.packets.find(p=>p.response?.coverage.total===4).response;
const actual=fixture.packets.filter(packet=>packet.response?.page_size===30).at(-1).response;
let server;
test.beforeAll(async()=>{server=await startCodingProductionServer();});
test.afterAll(async({},info)=>{if(!server)return;try{expect(server.unhandled).toEqual([]);}finally{await server.close();await info.attach('technical-directory-production-static-cleanup',{body:JSON.stringify({scope:'production_mock current canonical dist; synthetic auth shell and exact actual Main/JWT technical page, no backend/proxy/model',origin:server.origin,closed:!server.listening,unhandled:server.unhandled,dist:server.manifest}),contentType:'application/json'});}});
async function open(page,role,{usageReply}={}){
 const state={calls:[],errors:[],external:[],assets:[]};page.__technicalProduction=state;page.on('pageerror',error=>state.errors.push(error.message));page.on('response',response=>{if(response.status()>=400&&!new URL(response.url()).pathname.startsWith('/api/'))state.assets.push(response.url());});
 await page.addInitScript(()=>localStorage.setItem('hoim-token','synthetic-technical-production'));
 await page.context().route('**/*',route=>{if(new URL(route.request().url()).origin===server.origin)return route.continue();state.external.push(route.request().url());return route.abort();});
 const known=[...new Map(actual.data.map(row=>[row.native_feature_key||row.feature_key,{key:row.native_feature_key||row.feature_key,name:row.feature_name}])).values()];
 const features=Array.from({length:80},(_,i)=>({number:i+1,key:known[i]?.key||`synthetic_feature_${i}`,name:known[i]?.name||`合成能力${i+1}`,category:'knowledge',priority:'P0',engine:'llm',scope:'hospital',default_roles:['super_admin'],allowed_roles:['super_admin'],enabled:false,validation_status:'unreviewed',validation_note:'',prompt_version:0,active_prompt_id:null,revision:0,provider_id:null,daily_limit:100,setup_check:{ready:false,issues:[{code:'MODEL_UNASSIGNED',message:'尚未选择模型服务'}],scope_note:'合成配置声明，不代表模型验证'}}));
 await page.route('**/api/**',async route=>{
  const req=route.request(),u=new URL(req.url()),path=u.pathname;state.calls.push({path,method:req.method(),query:Object.fromEntries(u.searchParams)});
  if(path==='/api/ai/admin/task-directory')return route.fulfill({json:actual});
  if(path==='/api/ai/admin/usage')return usageReply?usageReply(route):route.fulfill({json:usageActual});
  let data=[];
  if(path==='/api/userInfo')data={username:'合成技术管理员',permissions:[role],avatar:''};
  if(path==='/api/ai/admin/features')data=features;
  await route.fulfill({json:{code:200,msg:'success',data}});
 });
 await page.goto(server.origin+'/#/ai/manage');return state;
}
test('current production super administrator opens the source-free global directory',async({page})=>{
 const state=await open(page,'super_admin');await expect(page.locator('.summary-value').first()).toHaveText('80');await selectManagementTab(page, '全局技术任务');await expect(page.locator('.task-technical-directory .el-table__body-wrapper tr')).toHaveCount(actual.data.length);await page.getByRole('button',{name:'技术详情',exact:true}).first().click();await expect(page.getByRole('dialog')).toContainText('global_ai_task_technical_v1');await expect(page.getByRole('dialog')).toContainText('"input_tokens": null');
 expect(state.calls.filter(call=>call.path==='/api/ai/admin/task-directory')).toEqual([{path:'/api/ai/admin/task-directory',method:'GET',query:{page:'1',page_size:'30'}}]);expect(state.calls.some(call=>/\/ai\/admin\/runs\/|\/parts\//u.test(call.path))).toBe(false);expect(state.calls.filter(call=>call.path.startsWith('/api/ai/')).every(call=>call.method==='GET')).toBe(true);expect(state.errors).toEqual([]);expect(state.external).toEqual([]);expect(state.assets).toEqual([]);
});
test('ordinary production administrator cannot load global technical management',async({page})=>{
 const state=await open(page,'admin');await expect(page).toHaveURL(/#\/404/u);await expectManagementEntry(page, '全局技术任务', false);expect(state.calls.filter(call=>call.path.startsWith('/api/ai/admin'))).toEqual([]);expect(state.errors).toEqual([]);expect(state.external).toEqual([]);expect(state.assets).toEqual([]);
});
test.afterEach(async({page},info)=>{if(info.status!==info.expectedStatus)await info.attach('technical-production-diagnostic',{body:JSON.stringify({state:page.__technicalProduction,body:await page.locator('body').innerText().catch(()=>null)}),contentType:'application/json'});});

test('current production usage tab renders exact nullable Main aggregates without Source requests',async({page})=>{
 const state=await open(page,'super_admin');await expect(page.locator('.summary-value').first()).toHaveText('80');await selectManagementTab(page, '调用统计');const panel=page.locator('section[aria-label="AI调用统计"]');await expect(panel).toContainText('本次完整覆盖 4 项任务');await expect(panel).toContainText('已知7；另1项未知');await expect(panel).toContainText('未知（1项）');expect(state.calls.filter(c=>c.path==='/api/ai/admin/usage')).toEqual([{path:'/api/ai/admin/usage',method:'GET',query:{}}]);expect(state.calls.some(c=>/\/parts\/|\/admin\/runs\//u.test(c.path))).toBe(false);expect(state.calls.filter(c=>c.path.startsWith('/api/ai/')).every(c=>c.method==='GET')).toBe(true);expect(state.errors).toEqual([]);expect(state.assets).toEqual([]);expect(state.external).toEqual([]);
});
test('current production usage rejects invented zero on refresh and discards old statistics',async({page})=>{
 let n=0;const state=await open(page,'super_admin',{usageReply:route=>{const value=structuredClone(usageActual);if(++n>1)value.data.find(r=>r.feature_key==='charge_reconciliation').output_tokens=0;return route.fulfill({json:value});}});await expect(page.locator('.summary-value').first()).toHaveText('80');await selectManagementTab(page, '调用统计');const panel=page.locator('section[aria-label="AI调用统计"]');await expect(panel.locator('.el-table__body-wrapper tr')).toHaveCount(2);await page.getByRole('button',{name:'刷新调用统计',exact:true}).click();await expect(panel.getByRole('alert')).toHaveText('当前调用统计无法核验，旧统计已清除');await expect(panel.locator('.el-table__body-wrapper tr')).toHaveCount(0);expect(n).toBe(2);expect(state.errors).toEqual([]);expect(state.assets).toEqual([]);expect(state.external).toEqual([]);
});
