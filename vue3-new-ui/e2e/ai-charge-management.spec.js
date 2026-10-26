const { expectManagementEntry, selectManagementTab } = require('./fixtures/ai-management-navigation.cjs');
const source=require('./fixtures/charge-sources/actual.json'),{metadata}=require('./fixtures/charge-source-ui.cjs');
const{test,expect}=require('@playwright/test'),{load}=require('./fixtures/load-charge-assistant.cjs'),{startChargeParentHarness}=require('./fixtures/charge-parent-harness.cjs');
let harness;test.beforeAll(async()=>{harness=await startChargeParentHarness({mode:'management'});});test.afterAll(async()=>{await harness?.close();});
async function setup(page,role='super_admin'){
 const p=load('chat'),calls=[],errors=[];page.on('pageerror',e=>errors.push(e.message));
 await page.context().route('**/*',route=>new URL(route.request().url()).origin===harness.origin?route.continue():route.abort());
 await page.route('**/api/**',async route=>{const req=route.request(),u=new URL(req.url()),path=u.pathname;calls.push({path,method:req.method(),query:Object.fromEntries(u.searchParams)});let response={code:200,data:[]};
  if(path==='/api/ai/admin/features')response=p.features;
  else if(path==='/api/ai/charge-reconciliation/options')response={...source.options,data:{...source.options.data,patient_id:null,admission_id:null,can_record:false}};
  else if(path==='/api/ai/charge-reconciliation/cases')response={code:200,data:{items:[metadata(source.published_super)],total:1,page:1,page_size:20}};
  else if(path==='/api/ai/charge-reconciliation/cases/'+source.published_super.case_snapshot_id)response={code:200,data:source.published_super};
  else if(!['/api/ai/admin/providers','/api/ai/admin/knowledge','/api/ai/admin/grants','/api/ai/admin/audit','/api/ai/admin/usage'].includes(path)){errors.push('Unhandled isolated '+req.method()+' '+path);await route.fulfill({status:599,json:{code:599,msg:'Missing explicit synthetic route'}});return;}
  await route.fulfill({json:response});
 });
 await page.goto(harness.origin);await page.waitForFunction(()=>!!window.__chargeParentProbe);await page.evaluate(role=>{const p=window.__chargeParentProbe;p.store.commit('user/permissions',[role]);p.scope.ready=true;},role);return{p,calls,errors};
}
test('Super manager opens full source governance lazily and clears private original on role loss',async({page})=>{
 const s=await setup(page);await expectManagementEntry(page, '完整住院账目来源治理', true);expect(s.calls.filter(c=>c.path.includes('/charge-reconciliation/'))).toEqual([]);await selectManagementTab(page, '完整住院账目来源治理');await page.getByRole('button',{name:'核对完整账目原件',exact:true}).click();await expect(page.getByRole('article',{name:'已核对住院账目原件'})).toBeVisible();await page.getByRole('button',{name:'展开院内完整原件',exact:true}).click();await expect(page.getByLabel('授权院内完整账目正文')).toBeVisible();expect(s.calls.filter(c=>c.path.endsWith('/cases/'+source.published_super.case_snapshot_id)).map(c=>c.query)).toEqual([{audit_only:'true'}]);expect(s.calls.every(c=>c.method==='GET')).toBe(true);await page.evaluate(()=>window.__chargeParentProbe.store.commit('user/permissions',['admin']));await expect(page.getByLabel('授权院内完整账目正文')).toHaveCount(0);await expectManagementEntry(page, '完整住院账目来源治理', false);expect(s.errors).toEqual([]);
});
test('ordinary admin has no complete charge governance tab or private source request',async({page})=>{const s=await setup(page,'admin');await expectManagementEntry(page, '能力与启用', true);await expectManagementEntry(page, '完整住院账目来源治理', false);expect(s.calls.filter(c=>c.path.includes('/charge-reconciliation/'))).toEqual([]);expect(s.errors).toEqual([]);});
