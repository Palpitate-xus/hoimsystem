const {test,expect}=require('@playwright/test');
const {startDrugLabelRootHarness}=require('./fixtures/drug-label-root-harness.cjs');
const {load}=require('./fixtures/load-drug-label-assistant-main.cjs');
let harness;test.beforeAll(async()=>{harness=await startDrugLabelRootHarness();});test.afterAll(async()=>{await harness?.close();});test.afterEach(async({page})=>{expect(page.__drugLabelParentState?.errors||[]).toEqual([]);});
async function open(page,{kind='chat',role='pharmacist',initial={}}={}){
 const p=load(kind),state={p,calls:[],errors:[]},other={...p.feature,key:'patient_summary',number:1,name:'合成其他功能',input_mode:'text',scope:'patient'};page.__drugLabelParentState=state;page.on('pageerror',e=>state.errors.push(e.message));
 await page.context().route('**/*',r=>new URL(r.request().url()).origin===harness.origin?r.continue():r.abort());
 await page.addInitScript(v=>{window.__drugLabelRootInitial=v;},{mode:'parent',roles:[role],featureKeys:['drug_label_extraction',other.key],initialFeature:'drug_label_extraction',initialInput:p.input,...initial});
 await page.route('**/api/**',async route=>{const r=route.request(),u=new URL(r.url());state.calls.push({method:r.method(),path:u.pathname,body:r.method()==='POST'&&r.postData()?r.postDataJSON():null});let response;
 if(u.pathname==='/api/ai/features')response={code:200,data:[p.feature,other]};
 else if(u.pathname==='/api/ai/drug-label-sources/options')response=role==='super_admin'?p.options_super:p.options;
 else if(u.pathname==='/api/ai/drug-label-sources/catalog')response=p.catalog;
 else if(u.pathname==='/api/ai/drug-label-sources')response=p.directory;
 else if(u.pathname==='/api/ai/drug-label-sources/'+p.input.drug_label_source_binding_id)response=role==='super_admin'?p.source_super:p.source;
 else if(u.pathname==='/api/ai/drug-label/context')response=p.preview;
 else if(u.pathname==='/api/ai/runs'&&r.method()==='POST')response=p.queued;
 else if(u.pathname==='/api/ai/runs/'+p.full.data.run_id)response=role==='super_admin'?p.super_full:p.full;
 else if(u.pathname==='/api/ai/admin/runs/'+p.full.data.run_id)response=p.trace;
 else{state.errors.push('Unhandled '+r.method()+' '+u.pathname);response={code:599};}
 await route.fulfill({json:response});});
 await page.goto(harness.origin);await page.waitForFunction(()=>!!window.__drugLabelRootProbe.parent);return state;
}
async function noGeneric(page){await expect(page.getByRole('button',{name:'生成辅助建议',exact:true})).toHaveCount(0);await expect(page.getByText('补充资料或问题',{exact:true})).toHaveCount(0);await expect(page.getByPlaceholder('搜索有访问权限的患者',{exact:true})).toHaveCount(0);}
async function submit(page){await page.getByRole('button',{name:'重新核对明确来源',exact:true}).click();await expect(page.getByRole('button',{name:'提交未核实说明书字段抽取',exact:true})).toBeEnabled();await page.getByRole('button',{name:'提交未核实说明书字段抽取',exact:true}).click();await expect(page.getByLabel('说明书模型摘要')).toBeVisible({timeout:15000});}
for(const kind of ['chat','responses'])test('actual shared Parent '+kind+' selects only complete leaflet task flow and exact original question',async({page})=>{const s=await open(page,{kind});await noGeneric(page);await submit(page);await noGeneric(page);expect(s.calls.filter(c=>c.method==='POST')).toEqual([{method:'POST',path:'/api/ai/runs',body:{feature_key:'drug_label_extraction',input:s.p.input,preview:false}}]);});
for(const marker of [null,'00000000-0000-0000-0000-000000000000'])test('explicit leaflet reference '+marker+' with another selected feature never falls back',async({page})=>{const s=await open(page,{initial:{initialFeature:'patient_summary',initialInput:{drug_label_source_binding_id:marker}}});await noGeneric(page);await expect(page.getByText('此面板仅处理第73项说明书逐字抽取；输入模式不符时不会降级为通用问答。',{exact:true})).toBeVisible();expect(s.calls.map(c=>c.path)).toEqual(['/api/ai/features']);});
for(const change of ['feature','mode','patient','foreign_input','sku'])test('shared Parent clears accepted leaflet result on '+change+' without a generic request',async({page})=>{const s=await open(page);await submit(page);const count=s.calls.length;await page.evaluate(change=>{const p=window.__drugLabelRootProbe,s=p.parent.$.setupState;if(change==='feature')s.featureKey='patient_summary';if(change==='mode')delete s.features.find(v=>v.key==='drug_label_extraction').input_mode;if(change==='patient')p.scope.patientId=1;if(change==='foreign_input')p.scope.initialInput={...p.scope.initialInput,document_original_id:'00000000-0000-0000-0000-000000000000'};if(change==='sku')p.scope.pharmaceuticalId=99999;},change);await expect(page.getByLabel('说明书模型摘要')).toHaveCount(0);await noGeneric(page);await page.evaluate(()=>new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r))));expect(s.calls.slice(count)).toEqual([]);});
