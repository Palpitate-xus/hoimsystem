const { expectManagementEntry, selectManagementTab } = require('./fixtures/ai-management-navigation.cjs');
const {test,expect}=require('@playwright/test');
const {startDrugLabelRootHarness}=require('./fixtures/drug-label-root-harness.cjs');
const {load}=require('./fixtures/load-drug-label-assistant-main.cjs');
let harness;test.beforeAll(async()=>{harness=await startDrugLabelRootHarness();});test.afterAll(async()=>{await harness?.close();});test.afterEach(async({page})=>{expect(page.__drugLabelManagementState?.errors||[]).toEqual([]);});
async function open(page,{roles=['super_admin'],token='synthetic-governance-session'}={}){
 const p=load(),state={p,calls:[],errors:[]};page.__drugLabelManagementState=state;page.on('pageerror',e=>state.errors.push(e.message));
 await page.context().route('**/*',r=>new URL(r.request().url()).origin===harness.origin?r.continue():r.abort());await page.addInitScript(v=>{window.__drugLabelRootInitial=v;},{mode:'manage',roles,token});
 await page.route('**/api/**',async route=>{const r=route.request(),u=new URL(r.url());state.calls.push({method:r.method(),path:u.pathname,query:Object.fromEntries(u.searchParams)});let response;
 if(u.pathname==='/api/ai/admin/features')response={code:200,data:[p.feature]};
 else if(['/api/ai/admin/providers','/api/ai/admin/knowledge','/api/ai/admin/grants','/api/ai/admin/audit'].includes(u.pathname))response={code:200,data:[]};
 else if(u.pathname==='/api/ai/admin/usage')response={code:200,data:[]};
 else if(u.pathname==='/api/ai/drug-label-sources/options')response=p.options_super;
 else if(u.pathname==='/api/ai/drug-label-sources/catalog')response=p.catalog;
 else if(u.pathname==='/api/ai/drug-label-sources'){expect(u.searchParams.get('audit_only')).toBe('true');response=p.directory_super_audit;}
 else{state.errors.push('Unhandled '+r.method()+' '+u.pathname);response={code:599};}
 await route.fulfill({json:response});});
 await page.goto(harness.origin);await page.waitForFunction(()=>!!window.__drugLabelRootProbe.manage);return state;
}
test('current Super governance mounts only after explicit tab and separates current management from frozen read',async({page})=>{const s=await open(page);expect(s.calls.filter(c=>c.path.startsWith('/api/ai/drug-label-sources'))).toEqual([]);await selectManagementTab(page, '说明书原文与独立签署治理');await expect(page.getByText('明确只读冻结说明书来源',{exact:true})).toBeVisible();await expect.poll(()=>s.calls.filter(c=>c.path==='/api/ai/drug-label-sources/options').length).toBe(1);expect(s.calls.filter(c=>c.path==='/api/ai/drug-label-sources')).toEqual([]);await page.getByText('明确只读冻结说明书来源',{exact:true}).click();await expect.poll(()=>s.calls.filter(c=>c.path==='/api/ai/drug-label-sources').length).toBe(1);await expect(page.getByLabel('说明书来源完整元数据目录',{exact:true})).toBeVisible();await page.evaluate(()=>window.__drugLabelRootProbe.store.commit('user/permissions',['pharmacist']));await expectManagementEntry(page, '说明书原文与独立签署治理', false);await expect(page.getByLabel('说明书来源完整元数据目录',{exact:true})).toHaveCount(0);});
for(const session of [{roles:['admin']},{roles:'super_admin'},{roles:['super_admin'],token:''}])test('invalid governance session '+JSON.stringify(session)+' sends no protected source query',async({page})=>{const s=await open(page,session);await expectManagementEntry(page, '说明书原文与独立签署治理', false);expect(s.calls.filter(c=>c.path.startsWith('/api/ai/drug-label-sources'))).toEqual([]);});
