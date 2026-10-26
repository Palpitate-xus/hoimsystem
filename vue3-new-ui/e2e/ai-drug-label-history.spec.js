const {openNativeDetails}=require('./fixtures/native-ui-details.cjs');
const {test,expect}=require('@playwright/test');
const {startDrugLabelRootHarness}=require('./fixtures/drug-label-root-harness.cjs');
const {load}=require('./fixtures/load-drug-label-main.cjs');
let harness;test.beforeAll(async()=>{harness=await startDrugLabelRootHarness();});test.afterAll(async()=>{await harness?.close();});
test.afterEach(async({page})=>{expect(page.__drugLabelRootState?.errors||[]).toEqual([]);});
async function open(page,{kind='chat',roles=['super_admin'],mode='history',mutateTrace,mutateFull,mutateRows,hold,deny,selected=false}={}){
 const packet=load(kind),state={packet,calls:[],errors:[],releases:{}};page.__drugLabelRootState=state;page.on('pageerror',e=>state.errors.push(e.message));
 await page.context().route('**/*',route=>new URL(route.request().url()).origin===harness.origin?route.continue():route.abort());
 await page.addInitScript(v=>{window.__drugLabelRootInitial=v;},{mode,roles,features:[packet.feature]});
 await page.route('**/api/**',async route=>{
  const req=route.request(),u=new URL(req.url()),id=packet.full.data.run_id;state.calls.push({method:req.method(),path:u.pathname,query:Object.fromEntries(u.searchParams)});let response,status=200;
  if(u.pathname==='/api/ai/admin/runs'){response=structuredClone(packet.admin_history);if(mutateRows)mutateRows(response.data);}
  else if(u.pathname==='/api/ai/admin/runs/'+id){response=structuredClone(packet.trace);if(mutateTrace)mutateTrace(response.data);if(hold==='trace')await new Promise(resolve=>state.releases.trace=resolve);}
  else if(u.pathname==='/api/ai/runs/'+id){response=structuredClone(packet.super_full);if(mutateFull)mutateFull(response.data);if(hold==='full')await new Promise(resolve=>state.releases.full=resolve);if(deny){status=deny;response={code:deny,msg:'Synthetic current authorization changed'};}}
  else{state.errors.push('Unhandled '+req.method()+' '+u.pathname);status=599;response={code:599};}
  await route.fulfill({status,json:response});
 });
 await page.goto(harness.origin);await page.waitForFunction(()=>!!window.__drugLabelRootProbe);
 if(selected)await page.evaluate(bindingId=>{const s=window.__drugLabelRootProbe.trace.$.setupState;s.filters.feature_key='drug_label_extraction';s.filters.drug_label_source_binding_id=bindingId;return s.load(true);},packet.input.drug_label_source_binding_id);
 return state;
}
async function inspect(page){await page.getByRole('button',{name:'执行溯源',exact:true}).first().click();}
async function accepted(page){await openNativeDetails(page,'说明书模型摘要',{timeout:15000});}
for(const kind of ['chat','responses'])test('actual Main '+kind+' history requires independent complete run and trace before literal fields',async({page})=>{
 const s=await open(page,{kind,selected:true});await inspect(page);await accepted(page);expect(s.calls.filter(c=>c.path==='/api/ai/runs/'+s.packet.full.data.run_id)).toHaveLength(1);
 await page.getByRole('button',{name:'查看第1项第1段引文',exact:true}).click();expect(await page.getByLabel('说明书字段逐字引文').evaluate(el=>el.textContent)).toBe(s.packet.full.data.result.drug_label_extraction.fields[0].spans[0].quote);
 await page.getByRole('dialog',{name:'本次原文逐字区间',exact:true}).getByLabel('Close this dialog').click();await page.getByRole('tab',{name:'说明书原始任务 JSON',exact:true}).click();await expect(page.getByText(s.packet.trace.data.raw_frozen_json.input_json,{exact:true})).toBeVisible();
});
for(const deny of [403,409])test('current complete run '+deny+' prevents a valid independent trace from exposing a result',async({page})=>{await open(page,{deny});await inspect(page);await expect(page.getByLabel('说明书模型摘要')).toHaveCount(0);await expect(page.getByText('当前完整任务或审计权限无法重新核对，旧资料已清除',{exact:true})).toBeVisible();});
for(const mutation of ['result','artifact','raw','run_id','feature'])test('history rejects independent '+mutation+' drift before any original or result display',async({page})=>{
 const s=await open(page,{mutateFull:r=>{if(mutation==='result')r.result.summary='UNVERIFIED_LEAFLET_SENTINEL';if(mutation==='artifact')r.drug_label_artifact.result_hash='0'.repeat(64);if(mutation==='run_id')r.run_id='00000000-0000-0000-0000-000000000000';},mutateTrace:r=>{if(mutation==='raw')r.raw_frozen_json.input_json+=' ';if(mutation==='feature')r.feature_key='patient_summary';}});await inspect(page);await expect(page.getByText('原任务或完整冻结来源及固定结果无法核对，暂不展示',{exact:true})).toBeVisible();await expect(page.getByLabel('说明书模型摘要')).toHaveCount(0);await expect(page.getByText('UNVERIFIED_LEAFLET_SENTINEL',{exact:true})).toHaveCount(0);expect(s.calls.some(c=>c.path==='/api/ai/runs/'+s.packet.full.data.run_id)).toBe(mutation!=='feature');
});
test('accepted native source-filter scope remains binding when all row and trace native tags are removed',async({page})=>{
 const strip=r=>{for(const k of ['drug_label_source_binding_id','drug_label_findings','drug_label_artifact','raw_frozen_json','frozen_request','evidence'])delete r[k];r.feature_key='patient_summary';r.result={summary:'UNVERIFIED_NATIVE_DOWNGRADE_SENTINEL',sections:[],warnings:[],missing_data:[]};};
 const s=await open(page,{selected:true,mutateRows:rows=>rows.forEach(strip),mutateTrace:strip});await inspect(page);await expect(page.getByText('原任务或完整冻结来源及固定结果无法核对，暂不展示',{exact:true})).toBeVisible();await expect(page.getByText('UNVERIFIED_NATIVE_DOWNGRADE_SENTINEL',{exact:true})).toHaveCount(0);expect(s.calls.filter(c=>c.path==='/api/ai/runs/'+s.packet.full.data.run_id)).toHaveLength(1);
});
for(const boundary of ['close','token','role','keepalive'])test('late complete run cannot restore a native trace after '+boundary,async({page})=>{
 const s=await open(page,{hold:'full'});await inspect(page);await expect.poll(()=>!!s.releases.full).toBe(true);await page.evaluate(boundary=>{const p=window.__drugLabelRootProbe;if(boundary==='close')p.trace.$.setupState.closeTrace();if(boundary==='token')p.store.commit('user/token','new-synthetic-session');if(boundary==='role')p.store.commit('user/permissions',['pharmacist']);if(boundary==='keepalive')p.scope.mounted=false;},boundary);s.releases.full();await page.evaluate(()=>new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r))));await expect(page.getByLabel('说明书模型摘要')).toHaveCount(0);await expect(page.getByLabel('任务完整说明书原文')).toHaveCount(0);
});
test('ordinary admin cannot send global leaflet history or trace requests',async({page})=>{const s=await open(page,{roles:['admin']});await expect(page.getByRole('button',{name:'执行溯源',exact:true})).toHaveCount(0);expect(s.calls).toEqual([]);});
test('every residual unique native marker including null fields prevents generic classification',async({page})=>{
 await open(page,{mode:'api'});const values=[{feature_key:'drug_label_extraction'},...['drug_label_source_binding_id','drug_label_findings','drug_label_artifact'].map(k=>({[k]:null})),{result:{drug_label_extraction:null}},{result:{schema_version:'drug_label_result_pointer_v1'}},{frozen_request:{payload:{context:{source_domain:'released_drug_label_original'}}}},{frozen_request:{payload:{context:{selected_sources:{drug_label_source_binding_id:null}}}}},{frozen_request:{payload:{context:{drug_label_binding:null}}}},{frozen_request:{payload:{input:{drug_label_source_binding_id:null}}}},{evidence:[{kind:'drug_label_source'}]},{evidence:[{source_id:'drug_label_source:synthetic'}]},{raw_frozen_json:{input_json:'{"payload":{"input":{"drug_label_source_binding_id":null}}}'}},{raw_frozen_json:{evidence_json:'[{"source_id":"drug_label_source:synthetic"}]'}},{raw_frozen_json:{input_json:'{"drug_label_source_binding_id":'}}];
 const result=await page.evaluate(values=>values.map(v=>window.__drugLabelRootProbe.historyApi.drugLabelRunHasNativeMarkers(v)),values);expect(result).toEqual(values.map(()=>true));
 expect(await page.evaluate(()=>[null,{}, {feature_key:'patient_summary'},{feature_key:'guideline_ingestion',document_original_id:'other'}].map(v=>window.__drugLabelRootProbe.historyApi.drugLabelRunHasNativeMarkers(v)))).toEqual([false,false,false,false]);
});
