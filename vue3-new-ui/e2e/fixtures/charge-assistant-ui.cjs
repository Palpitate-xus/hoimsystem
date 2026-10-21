const{expect}=require('@playwright/test'),{load}=require('./load-charge-assistant.cjs');
async function setupChargeAssistant(page,harness,{profile='chat',initial=true,role='cashier',state='succeeded'}={}){
 const packet=load(profile),calls=[],errors=[],unhandled=[],hold=new Map(),fail=new Map(),respond=new Map();let runState=state;
 page.on('pageerror',e=>errors.push(String(e)));await page.route('**/api/**',async route=>{const req=route.request(),url=new URL(req.url()),key=req.method()+' '+url.pathname;calls.push({key,query:Object.fromEntries(url.searchParams),body:req.postData()?req.postDataJSON():null});if(hold.has(key)){const gate=hold.get(key);gate.started=true;await gate.promise;}if(fail.has(key)){const status=fail.get(key);fail.delete(key);await route.fulfill({status,contentType:'application/json',body:JSON.stringify({code:status,msg:'合成当前完整账目或授权已失效'})});return;}let body;
  if(respond.has(key)){const value=respond.get(key);body=typeof value==='function'?await value(req,url):value;}
  else if(key==='GET /api/ai/charge-reconciliation/options')body=packet.source.options;
  else if(key==='GET /api/ai/charge-reconciliation/cases')body=packet.source.ordinary_directory;
  else if(key==='GET /api/ai/charge-reconciliation/cases/'+packet.request.input.charge_case_id)body=packet.source.ordinary;
  else if(key==='POST /api/ai/context')body=packet.preview;
  else if(key==='POST /api/ai/runs')body=packet.states.queued.ack;
  else if(key==='GET /api/ai/runs')body=packet.ordinary_history;
  else if(key.startsWith('GET /api/ai/runs/')){const id=url.pathname.split('/').at(-1),entry=Object.values(packet.states).find(v=>v.detail.data.run_id===id);body=packet.states[runState].detail.data.run_id===id?packet.states[runState].detail:entry?.detail;}
  else if(key.startsWith('POST /api/ai/runs/')&&key.endsWith('/cancel')){runState='cancelled_paid';body=packet.inflight_cancel_ack;}
  else if(key.startsWith('POST /api/ai/runs/')&&key.endsWith('/feedback'))body=packet.feedback_ack;
  if(!body){unhandled.push(key);body={code:599,msg:'未明确模拟的业务请求'};}
  await route.fulfill({status:body.code===599?599:200,contentType:'application/json',body:JSON.stringify(body)});
 });
 await page.goto(harness.origin);await expect.poll(()=>page.evaluate(()=>!!window.__chargeAssistantProbe)).toBe(true);await page.evaluate(({feature,initialInput,patientId,encounterRef,role})=>{const p=window.__chargeAssistantProbe;p.store.commit('user/permissions',[role]);Object.assign(p.scope,{feature,patientId,encounterRef,initialInput});},{feature:packet.feature,initialInput:initial?packet.request.input:{},patientId:packet.request.patient_id,encounterRef:packet.request.encounter_ref,role});
 return{packet,calls,errors,unhandled,fail,respond,setState(v){runState=v;},hold(key){let release;const entry={started:false,promise:new Promise(r=>{release=r;})};hold.set(key,entry);return{get started(){return entry.started;},release(){hold.delete(key);release();}};}};
}
async function chargeReady(page){await expect(page.getByRole('button',{name:'提交待人工核对任务',exact:true})).toBeEnabled();}
async function submitCharge(page){await chargeReady(page);await page.getByRole('button',{name:'提交待人工核对任务',exact:true}).click();await expect(page.getByLabel('完整冻结五类账目计数')).toBeVisible();}
module.exports={setupChargeAssistant,chargeReady,submitCharge};
