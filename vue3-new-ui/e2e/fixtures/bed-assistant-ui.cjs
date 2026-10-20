const {expect}=require('@playwright/test');
const frozen=require('./bed-synthetic/assistant-frozen.json'),brief=require('./bed-synthetic/assistant-queued-serializer.json'),H7=require('./bed-synthetic/pipeline-7.json'),H14=require('./bed-synthetic/pipeline-14.json'),options=require('./bed-synthetic/series-options.json');
const {choose,fill,metadata}=require('./bed-series-ui.cjs');
// These reconstructions are lossless field extraction, not regenerated proofs.
// The extractor compares every shared nested value with final2 before writing.
const packets=Object.fromEntries(Object.entries({7:H7,14:H14}).map(([h,p])=>[h,{run:{...frozen.by_horizon[h].run,bed_findings:p.findings,evidence:p.evidence,result:{...frozen.by_horizon[h].run.result,bed_analysis:p.analysis}},inspection:{...frozen.by_horizon[h].inspection,context:{...frozen.by_horizon[h].inspection.context,bed_source:p.findings.bed_source,bed_series:p.findings.bed_series}}}]));
const series={...frozen.series_metadata,snapshot:H7.findings.bed_series.snapshot,public_source:H7.findings.bed_source};
async function setupBedAssistant(page,harness,config={}){
 const state={role:'admin',inputMode:'bed',rows:[series],writes:[],reads:[],errors:[],releases:{},completed:[],history:frozen.history,...config};page.on('pageerror',e=>state.errors.push(e.message));
 await page.context().route('**/*',route=>new URL(route.request().url()).origin===harness.origin?route.continue():route.abort('blockedbyclient'));
 await page.route('**/api/**',async route=>{const req=route.request(),u=new URL(req.url()),path=u.pathname,method=req.method();let data;
  if(method==='GET'){
   state.reads.push({path,query:Object.fromEntries(u.searchParams)});
   if(path==='/api/ai/features')data=[{key:'bed_forecast',number:64,name:'病区床位预测',category:'operations',engine:'forecast',scope:'hospital',input_mode:state.inputMode,enabled:true,requires_operational_validation:true,validation_status:'validated',revision:1,provider_id:1,provider_revision:1,inputs:['完整受审原序列与明确预测期'],deliverables:['五目标独立固定预测与原量证明'],allowed_roles:['admin','director','super_admin']}];
   else if(path.endsWith('/bed-sources/options'))data=u.searchParams.has('department_id')?frozen.source_options:options.source_options;
   else if(path==='/api/ai/service-options')data={departments:options.source_options.departments,default_window:['2026-10-01','2026-10-20'],allow_hospital_scope:true};
   else if(path==='/api/ai/bed-series'){const rows=state.rows.filter(r=>(!u.searchParams.has('ward_id')||r.ward_id===Number(u.searchParams.get('ward_id')))&&(!u.searchParams.has('department_id')||r.department_id===Number(u.searchParams.get('department_id'))));data={items:rows.map(metadata),total:rows.length,page:Number(u.searchParams.get('page')||1),page_size:20};}
   else if(path.startsWith('/api/ai/bed-series/'))data=state.detail||state.rows.find(r=>path.endsWith(r.series_id));
   else if(path==='/api/ai/runs')data=state.history;
   else if(path.startsWith('/api/ai/runs/'))data=state.runOverride||Object.values(packets).find(p=>path.endsWith(p.run.run_id))?.run;
  }else{
   const body=req.postDataJSON();state.writes.push({path,body});
   if(path==='/api/ai/operational-context')data=state.inspection||packets[body.input?.horizon_days]?.inspection;
   else if(path==='/api/ai/runs')data=state.queued||brief.by_horizon[body.input?.horizon_days];
   else if(path.endsWith('/feedback'))data={recorded:true};
  }
  if(data===undefined){state.errors.push(`Unhandled isolated ${method} ${path}`);await route.fulfill({status:500,json:{code:500,msg:'Synthetic route missing'}});return;}
  const failure=state.failure?.(method,path,req),held=state.hold?.(method,path,req);if(held)await new Promise(resolve=>state.releases[held]=resolve);
  try{await route.fulfill(failure?{status:failure,json:{code:failure,msg:'Synthetic current authorization unavailable'}}:{json:{code:200,data:state.mutate?state.mutate(structuredClone(data),path,method)??data:data}});}finally{if(held)state.completed.push(held);}
 });
 await page.goto(harness.origin);await page.waitForFunction(()=>!!window.__bedAssistantProbe);await page.evaluate(({role,initialInput})=>{const p=window.__bedAssistantProbe;p.store.commit('user/permissions',[role]);p.scope.initialInput=initialInput||{};p.scope.ready=true;},{role:state.role,initialInput:state.initialInput});return state;
}
async function nativeScope(page,days=14){await choose(page,'床位预测期限',`完整${days}个业务日`);await choose(page,'床位预测科室','内科 · #1');await choose(page,'床位预测病区','合成病区 · #1');await page.getByRole('button',{name:'核对完整床位序列',exact:true}).first().click();const d=page.getByRole('dialog',{name:'完整床位序列冻结核对与治理',exact:true});await d.getByRole('button',{name:'选择此已发布床位序列',exact:true}).click();await expect(page.getByRole('button',{name:'生成辅助建议',exact:true})).toBeEnabled();await d.locator('.el-dialog__headerbtn').click();}
async function history(page,h=14){await page.getByText('最近任务',{exact:true}).click();const index=frozen.history.findIndex(r=>r.run_id===packets[h].run.run_id);await page.getByRole('button',{name:'查看',exact:true}).nth(index).click();await expect(page.getByLabel('AI任务结果',{exact:true})).toBeVisible();}
async function evidence(page){await page.getByRole('button',{name:'核对完整受审床位序列原件',exact:true}).click();await expect(page.getByRole('dialog',{name:'核查引用依据',exact:true})).toContainText('bed_series_private_v1');}
async function cleared(page,held=false){await expect(page.getByLabel('AI任务结果',{exact:true})).toHaveCount(0);await expect(page.getByRole('dialog',{name:'核查引用依据',exact:true})).toHaveCount(0);expect(await page.evaluate(held=>{const p=window.__bedAssistantProbe,s=(held?p.heldAssistant:p.assistant).$.setupState;return{run:s.run,context:s.contextData,evidence:s.evidence,dialog:s.evidenceDialog};},held)).toEqual({run:null,context:null,evidence:null,dialog:false});}
module.exports={setupBedAssistant,nativeScope,history,evidence,cleared,choose,fill,metadata,packets,series,frozen,brief};
