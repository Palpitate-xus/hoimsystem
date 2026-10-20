const {test,expect}=require('@playwright/test');
const {startSupplyHarness}=require('./fixtures/supply-result-harness.cjs');
const meta=require('./fixtures/supply-native/capabilities.json');
let harness;
test.beforeAll(async()=>{harness=await startSupplyHarness();});
test.afterAll(async()=>{await harness?.close();});
function provider(){return{provider_id:1,revision:2,name:'合成已保存物资服务',model:'supply:'+'f'.repeat(64),kind:'specialist',supported_features:['supply_forecast']};}
async function setup(page,{hold=false,role='super_admin',mutate=null}={}){
 const state={writes:[],errors:[],release:null};page.on('pageerror',e=>state.errors.push(e.message));
 await page.context().route('**/*',r=>new URL(r.request().url()).origin===harness.origin?r.continue():r.abort());
 await page.route('**/api/**',async route=>{
  const req=route.request();state.writes.push({path:new URL(req.url()).pathname,method:req.method(),body:req.postDataJSON()});
  const row=provider(),data={provider_id:1,provider_revision:2,configured_model:row.model,compatible:false,issues:['登记模型与实际声明不同，须核对后保存'],capabilities:structuredClone(meta),scope_note:'仅元数据核对；合成隔离API，不运行推理。'};
  if(hold)await new Promise(resolve=>state.release=resolve);
  if(mutate)mutate(data);
  await route.fulfill({json:{code:200,data}});
 });
 await page.goto(harness.origin);await page.waitForFunction(()=>!!window.__supplyProbe);
 await page.evaluate(({role,row})=>{const p=window.__supplyProbe;p.store.commit('user/permissions',[role]);p.scope.providers=[row];p.scope.target={...row,session:p.store.state.user.accessToken};},{role,row:provider()});
 return state;
}
test('actual metadata checks saved integer ID and revision and only fills pending editor',async({page})=>{
 const state=await setup(page);
 await expect(page.getByText(meta.model_version,{exact:true})).toBeVisible();
 expect(state.writes).toEqual([{path:'/api/ai/admin/providers/1/supply-capabilities',method:'POST',body:{expected_revision:2}}]);
 await page.getByRole('button',{name:'填写实际模型，待保存',exact:true}).click();
 const event=await page.evaluate(()=>window.__supplyProbe.events.find(e=>e.type==='edit-model'));
 expect(event.value).toEqual({provider_id:1,revision:2,configured_model:provider().model,model:meta.model_version,session:'synthetic-supply-session'});
 expect(state.writes).toHaveLength(1);expect(state.errors).toEqual([]);
});
for(const id of [0,-1,1.5,'1',true,2147483648])test('API rejects nonpositive/coerced provider ID '+String(id),async({page})=>{
 await page.goto(harness.origin);await page.waitForFunction(()=>!!window.__supplyProbe);
 expect(await page.evaluate(id=>{try{window.__supplyProbe.provider.checkSupplyProvider(id,2);return false;}catch{return true;}},id)).toBe(true);
});
for(const mode of ['revision','core','recipe','boolean','compatibility','extra'])test('rejects inconsistent metadata receipt '+mode,async({page})=>{
 const state=await setup(page,{mutate:v=>{if(mode==='revision')v.provider_revision=3;else if(mode==='core')v.capabilities.core_sha256.supply_server='f'.repeat(64);else if(mode==='recipe')v.capabilities.recipe.forecast_clamp=true;else if(mode==='boolean')v.capabilities.forecast_only=1;else if(mode==='compatibility'){v.compatible=true;v.issues=[];}else v.private_source={patient:'private'};}});
 await expect(page.getByRole('alert').filter({hasText:'核对回执'})).toBeVisible();
 await expect(page.getByRole('button',{name:'填写实际模型，待保存',exact:true})).toHaveCount(0);expect(state.errors).toEqual([]);
});
for(const change of ['token','role','provider_revision','deactivate'])test('late metadata cannot restore after '+change,async({page})=>{
 const state=await setup(page,{hold:true});await expect.poll(()=>state.writes.length).toBe(1);
 await page.evaluate(change=>{const p=window.__supplyProbe;if(change==='token')p.store.commit('user/token','other-session');else if(change==='role')p.store.commit('user/permissions',['admin']);else if(change==='provider_revision')p.scope.providers[0].revision++;else p.scope.mounted=false;},change);
 state.release();await page.waitForTimeout(80);
 await expect(page.getByText(meta.model_version,{exact:true})).toHaveCount(0);
 expect(await page.evaluate(()=>window.__supplyProbe.events.filter(e=>e.type==='edit-model'))).toEqual([]);expect(state.errors).toEqual([]);
});
test('ordinary admin cannot start metadata check',async({page})=>{const state=await setup(page,{role:'admin'});await page.waitForTimeout(60);expect(state.writes).toEqual([]);await expect(page.getByRole('dialog')).toHaveCount(0);});
