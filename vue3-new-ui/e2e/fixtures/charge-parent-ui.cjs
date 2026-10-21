const{expect}=require('@playwright/test'),{load}=require('./load-charge-assistant.cjs');
async function setupChargeParent(page,harness,config={}){
 const packet=load(config.profile||'chat'),calls=[],errors=[],writes=[],held={},completed=[],generic={key:'patient_summary',number:1,name:'患者全景摘要',scope:'patient',engine:'llm',enabled:true,inputs:['实际记录'],deliverables:['合成摘要'],allowed_roles:['admin','super_admin']},state={packet,calls,errors,writes,held,completed,...config};
 page.on('pageerror',e=>errors.push(e.message));await page.context().route('**/*',route=>new URL(route.request().url()).origin===harness.origin?route.continue():route.abort());
 await page.route('**/api/**',async route=>{
  const req=route.request(),u=new URL(req.url()),path=u.pathname,method=req.method();calls.push({path,method,query:Object.fromEntries(u.searchParams),body:req.postData()?req.postDataJSON():null});if(method!=='GET')writes.push(calls.at(-1));
  let response;
  if(path==='/api/ai/features')response={code:200,data:state.features||[packet.feature,generic]};
  else if(path==='/api/ai/patients'||path==='/api/ai/encounters')response={code:200,data:[]};
  else if(path==='/api/ai/charge-reconciliation/options')response=packet.source.options;
  else if(path==='/api/ai/charge-reconciliation/cases')response=packet.source.ordinary_directory;
  else if(path==='/api/ai/charge-reconciliation/cases/'+packet.request.input.charge_case_id)response=packet.source.ordinary;
  else if(path==='/api/ai/context')response=packet.preview;
  else if(path==='/api/ai/runs'&&method==='POST')response=packet.states.queued.ack;
  else if(path==='/api/ai/runs')response=packet.ordinary_history;
  else if(path==='/api/ai/runs/'+packet.states.succeeded.detail.data.run_id)response=packet.states.succeeded.detail;
  else{errors.push('Unhandled isolated '+method+' '+path);await route.fulfill({status:599,json:{code:599,msg:'Missing explicit synthetic route'}});return;}
  const name=state.hold?.(path);if(name)await new Promise(resolve=>held[name]=resolve);try{await route.fulfill({json:response});}finally{if(name)completed.push(name);}
 });
 await page.goto(harness.origin);await page.waitForFunction(()=>!!window.__chargeParentProbe);
 await page.evaluate(({packet,initialInput,patientId,encounterRef,initialFeature})=>{const p=window.__chargeParentProbe;p.store.commit('user/permissions',['admin']);Object.assign(p.scope,{featureKeys:[],initialFeature,initialInput,patientId,encounterRef,ready:true});},{packet:null,initialInput:config.initialInput??packet.request.input,patientId:Object.hasOwn(config,'patientId')?config.patientId:packet.request.patient_id,encounterRef:Object.hasOwn(config,'encounterRef')?config.encounterRef:packet.request.encounter_ref,initialFeature:config.initialFeature||'charge_reconciliation'});
 return state;
}
async function readyChargeParent(page){await expect(page.getByRole('button',{name:'提交待人工核对任务',exact:true})).toBeEnabled({timeout:15000});}
module.exports={setupChargeParent,readyChargeParent};
