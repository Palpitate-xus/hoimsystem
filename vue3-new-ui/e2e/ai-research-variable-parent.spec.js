const {test,expect}=require('@playwright/test');
const F=require('./fixtures/research-variable-task/actual-states.json');
const {startResearchVariableParentHarness}=require('./fixtures/research-variable-parent-harness.cjs');
let harness;test.beforeAll(async()=>{harness=await startResearchVariableParentHarness();});test.afterAll(async()=>{await harness?.close();});
const packet=F.states.succeeded_partial,batch=F.selection.research_variable_batch_id;
async function open(page,initial={},mutateFeatures=value=>value){
 const errors=[],calls=[];page.on('pageerror',error=>errors.push(error.message));await page.addInitScript(value=>{window.__researchVariableAssistantInitial=value;},{initialInput:F.selection,...initial});
 await page.context().route('**/*',route=>new URL(route.request().url()).origin===harness.origin?route.continue():route.abort());
 await page.route('**/api/**',async route=>{
  const path=new URL(route.request().url()).pathname.replace(/^\/api/u,''),method=route.request().method();calls.push({method,path});
  if(path==='/ai/features')return route.fulfill({json:mutateFeatures(structuredClone(F.features))});
  if(path===`/ai/research-variables/batches/${batch}`)return route.fulfill({json:{code:200,msg:'success',data:F.source_parts.source.data.metadata}});
  if(path==='/ai/research-variables/context')return route.fulfill({json:F.preview});
  if(path===`/ai/research-variables/batches/${batch}/parts/source`)return route.fulfill({json:F.source_parts.source});
  if(path===`/ai/research-variables/batches/${batch}/parts/snapshot`)return route.fulfill({json:F.source_parts.snapshot});
  if(path==='/ai/runs'&&method==='POST')return route.fulfill({json:{code:200,msg:'success',data:F.states.queued.detail}});
  if(path===`/ai/runs/${packet.detail.run_id}`)return route.fulfill({json:{code:200,msg:'success',data:packet.detail}});
  for(const[name,value]of Object.entries(packet.parts))if(path===`/ai/runs/${packet.detail.run_id}/research-variables/${name}`)return route.fulfill({json:value});
  return route.fulfill({status:599,json:{detail:'unmocked generic request'}});
 });
 await page.goto(harness.origin);await page.waitForFunction(()=>!!window.__researchVariableAssistantProbe?.assistant);return {calls,errors};
}
async function noGeneric(page){await expect(page.getByRole('button',{name:'生成辅助建议',exact:true})).toHaveCount(0);await expect(page.getByText('补充 JSON（可选）',{exact:true})).toHaveCount(0);await expect(page.getByPlaceholder('搜索有访问权限的患者',{exact:true})).toHaveCount(0);}
async function ready(page){await page.getByRole('button',{name:'核对传入批次',exact:true}).click();await expect(page.getByRole('button',{name:'清除本次选择',exact:true})).toBeVisible();await page.getByTestId('variable-inspect').click();await expect(page.getByTestId('variable-preview')).toBeVisible();await page.getByTestId('variable-submit').click();await expect(page.getByRole('region',{name:'科研变量逐字草稿核对'})).toBeVisible();}
test('real shared Parent delegates76 to the actual complete-proof child and never generic patient/JSON/service routes',async({page})=>{
 const {calls,errors}=await open(page);await noGeneric(page);await ready(page);await noGeneric(page);expect(calls.filter(x=>x.method==='POST').map(x=>x.path)).toEqual(['/ai/research-variables/context','/ai/runs']);expect(calls.some(x=>/service-options|patients|operational-context/u.test(x.path))).toBe(false);expect(errors).toEqual([]);
});
for(const id of [batch,null])test('wrong feature plus explicit Batch '+String(id)+' remains dedicated with zero task or generic calls',async({page})=>{
 const {calls,errors}=await open(page,{initialFeature:'operations_qa',initialInput:{research_variable_batch_id:id}});await expect(page.getByTestId('research-variable-assistant')).toBeVisible();await noGeneric(page);await expect(page.getByTestId('variable-inspect')).toHaveCount(0);expect(calls).toEqual([{method:'GET',path:'/ai/features'}]);expect(errors).toEqual([]);
});
for(const change of ['feature','removed_mode','foreign_mode','patient','encounter','extra_input','null_batch'])test('real Parent clears private76 proof and never falls back on '+change,async({page})=>{
 const {calls,errors}=await open(page);await ready(page);const before=calls.length;
 await page.evaluate(change=>{const p=window.__researchVariableAssistantProbe,s=p.assistant.$.setupState;if(change==='feature')s.featureKey='operations_qa';if(change==='removed_mode')delete s.features.find(x=>x.key==='research_extraction').input_mode;if(change==='foreign_mode')s.features.find(x=>x.key==='research_extraction').input_mode='generic';if(change==='patient')p.scope.patientId=1;if(change==='encounter')p.scope.encounterRef='admission:1';if(change==='extra_input')p.scope.initialInput={...p.scope.initialInput,home_id:1};if(change==='null_batch')p.scope.initialInput={research_variable_batch_id:null};},change);
 await expect(page.getByTestId('variable-preview')).toHaveCount(0);await expect(page.getByRole('region',{name:'科研变量逐字草稿核对'})).toHaveCount(0);await noGeneric(page);expect(calls.slice(before)).toEqual([]);expect(errors).toEqual([]);
});
test('switching76 to71 preserves the first dedicated lifecycle instead of mounting both children',async({page})=>{
 const {calls,errors}=await open(page);await ready(page);const before=calls.length;await page.evaluate(()=>{window.__researchVariableAssistantProbe.assistant.$.setupState.featureKey='guideline_ingestion';});await expect(page.getByTestId('research-variable-assistant')).toBeVisible();await expect(page.getByText('当前科研变量提取配置不可用，请联系管理员。',{exact:true})).toBeVisible();await noGeneric(page);expect(calls.slice(before)).toEqual([]);expect(errors).toEqual([]);
});
test('initial foreign patient scope is rejected before any Source/context/task read',async({page})=>{
 const {calls,errors}=await open(page,{patientId:1});await expect(page.getByTestId('research-variable-assistant')).toBeVisible();await expect(page.getByTestId('variable-inspect')).toHaveCount(0);await noGeneric(page);expect(calls).toEqual([{method:'GET',path:'/ai/features'}]);expect(errors).toEqual([]);
});
