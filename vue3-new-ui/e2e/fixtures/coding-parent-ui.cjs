const{expect}=require('@playwright/test'),actual=require('./coding-parent-actual.json');
const scope=actual.actual_scope,refs={coding_case_id:actual.live_case.data.case_snapshot_id};
async function setupCodingParent(page,harness,config={}){
 const state={mode:'assistant',role:'doctor',status:'succeeded',reads:[],writes:[],errors:[],releases:{},completed:[],...config};state.feature=structuredClone(actual.features.data.find(f=>f.key===(state.featureKey||'drg_evidence_review')));page.__codingParentState=state;page.on('pageerror',e=>state.errors.push(e.message));
 await page.context().route('**/*',route=>new URL(route.request().url()).origin===harness.origin?route.continue():route.abort());
 await page.route('**/api/**',async route=>{const req=route.request(),u=new URL(req.url()),p=u.pathname,m=req.method();let response;
 if(m==='GET'){
  state.reads.push({path:p,query:Object.fromEntries(u.searchParams)});
  if(p==='/api/ai/features')response={...actual.features,data:[state.feature]};
  else if(p==='/api/ai/patients')response=actual.patients;
  else if(p==='/api/ai/encounters')response=actual.encounters;
  else if(p==='/api/ai/coding-evidence/options')response=actual.options;
  else if(p==='/api/ai/coding-evidence/homes')response=actual.homes;
  else if(p==='/api/ai/coding-evidence/cases')response=actual.case_directory;
  else if(p==='/api/ai/coding-evidence/cases/'+refs.coding_case_id)response=actual.live_case;
  else if(p.startsWith('/api/ai/coding-evidence/cases/')){await route.fulfill({status:404,json:{code:404,msg:'Explicit synthetic other Case is unavailable'}});return;}
  else if(p==='/api/ai/coding-evidence/packages')response=actual.package_directory;
  else if(p==='/api/ai/runs')response=actual.history;
  else if(p==='/api/ai/admin/runs')response=actual.admin_history;
  else if(p.startsWith('/api/ai/admin/runs/'))response=state.audit?{code:200,data:state.audit}:actual.audit;
  else if(p.startsWith('/api/ai/runs/'))response=state.full?{code:200,data:state.full}:state.status==='running'?actual.running:actual.detail;
 }else{
  state.writes.push({path:p,body:req.postDataJSON()});
  if(p==='/api/ai/context')response=actual.preview;
  else if(p==='/api/ai/runs')response=actual.queued;
  else if(p.endsWith('/feedback'))response={code:200,data:{recorded:true}};
 }
 if(response===undefined){state.errors.push('Unhandled isolated '+m+' '+p);await route.fulfill({status:599,json:{code:599,msg:'Missing explicit synthetic route'}});return;}
 const value=structuredClone(response);if(state.mutate)value.data=state.mutate(value.data,p,m)||value.data;const held=state.hold?.(m,p,req);if(held)await new Promise(resolve=>state.releases[held]=resolve);const failed=state.failure?.(m,p,req);try{await route.fulfill(failed?{status:failed,json:{code:failed,msg:'Synthetic current authorization or original unavailable'}}:{json:value});}finally{if(held)state.completed.push(held);}
 });
 await page.goto(harness.origin);await page.waitForFunction(()=>!!window.__codingParentProbe);
 await page.evaluate(({mode,role,initialInput,feature,scope})=>{const p=window.__codingParentProbe;p.store.commit('user/permissions',[role]);Object.assign(p.scope,{mode,featureKeys:[feature.key],initialFeature:feature.key,patientId:scope.patient_id,encounterRef:scope.admission_id,initialInput,features:[feature],ready:true});},{mode:state.mode,role:state.role,initialInput:state.initialInput??{home_id:scope.home_id,...refs},feature:state.feature,scope});return state;
}
async function ready(page){await expect(page.getByRole('button',{name:'生成辅助建议',exact:true})).toBeEnabled({timeout:20000});}
async function showHistory(page){await ready(page);await page.getByText('最近任务',{exact:true}).click();await page.getByRole('button',{name:'查看',exact:true}).first().click();await expect(page.getByLabel('AI任务结果',{exact:true})).toBeVisible({timeout:15000});}
async function cleared(page,held=false){await expect(page.getByLabel('AI任务结果',{exact:true})).toHaveCount(0);await expect(page.getByRole('dialog',{name:'核查引用依据',exact:true})).toHaveCount(0);expect(await page.evaluate(held=>{const p=window.__codingParentProbe,a=(held?p.heldAssistant:p.assistant).$.setupState;return{run:a.run,context:a.contextData,evidence:a.evidence,evidenceDialog:a.evidenceDialog};},held)).toEqual({run:null,context:null,evidence:null,evidenceDialog:false});}
module.exports={setupCodingParent,ready,showHistory,cleared,actual,scope,refs};
