const{expect}=require('@playwright/test'),{load}=require('./load-charge-assistant.cjs');
async function setupBillingEntry(page,{harness=null,mode='inpatient'}={}){
 const p=load('chat'),calls=[],writes=[],authenticationReads=[],unhandled=[],errors=[],name=p.source.ordinary.data.snapshot.collection.patient_binding.name;
 page.on('pageerror',e=>errors.push(e.message));await page.addInitScript(()=>localStorage.setItem('hoim-token','synthetic-native-billing-entry'));
 if(harness)await page.context().route('**/*',route=>new URL(route.request().url()).origin===harness.origin?route.continue():route.abort());
 await page.route('**/api/**',async route=>{
  const req=route.request(),u=new URL(req.url()),path=u.pathname,method=req.method();calls.push({path,method,query:Object.fromEntries(u.searchParams),body:req.postData()?req.postDataJSON():null});if(path==='/api/userInfo'&&method==='POST')authenticationReads.push(calls.at(-1));else if(method!=='GET')writes.push(calls.at(-1));
  let response={code:200,msg:'Explicit synthetic entry reply',data:[]};
  if(path==='/api/userInfo'&&method==='POST')response.data={username:'合成收费入口用户',permissions:['admin'],avatar:''};
  else if(path==='/api/admission/getInpatientList')response.data=[{admission_id:p.request.encounter_ref,patient_id:p.request.patient_id,patient_name:name,bed_no:'01'}];
  else if(path==='/api/inpatientCharge/getList')response.data=p.source.ordinary.data.snapshot.collection.charges;
  else if(path==='/api/inpatientCharge/getDailyBill')response.data={total_amount:0,deposit_amount:0,balance:0,unsettled_amount:0,daily_list:[]};
  else if(path==='/api/chargeManagement/getList')response.data=[{id:'synthetic-outpatient-charge',patient_id:1,registration_uuid:'synthetic-outpatient-visit',patient_name:'合成门诊收费患者',amount:'20.00',status:2}];
  else if(path==='/api/ai/features')response={code:200,data:[p.feature]};
  else if(path==='/api/ai/charge-reconciliation/options')response=p.source.options;
  else if(path==='/api/ai/charge-reconciliation/cases')response=p.source.ordinary_directory;
  else if(path==='/api/ai/charge-reconciliation/cases/'+p.request.input.charge_case_id)response=p.source.ordinary;
  else if(path==='/api/ai/runs'&&method==='POST')response=p.states.queued.ack;
  else if(path==='/api/ai/runs/'+p.states.succeeded.detail.data.run_id)response=p.states.succeeded.detail;
  else if(path.startsWith('/api/ai/')||method!=='GET'){unhandled.push(method+' '+path);await route.fulfill({status:599,json:{code:599,msg:'Missing explicit synthetic AI or write route'}});return;}
  await route.fulfill({json:response});
 });
 await page.goto(harness?harness.origin:mode==='inpatient'?'/#/inpatient/inpatientCharge':'/#/charge/chargeList');
 if(harness){await page.waitForFunction(()=>!!window.__chargeBusinessProbe);await page.evaluate(()=>{const p=window.__chargeBusinessProbe;p.store.commit('user/permissions',['admin']);p.scope.ready=true;});}
 return{packet:p,name,calls,writes,authenticationReads,unhandled,errors};
}
async function checkInpatientBillingEntry(page,options={}){
 const s=await setupBillingEntry(page,{...options,mode:'inpatient'});await page.getByRole('cell',{name:s.name,exact:true}).click();await page.getByRole('button',{name:'AI 收费核对',exact:true}).click();const drawer=page.getByRole('dialog',{name:'AI 住院账目与执行核对',exact:true});
 await drawer.getByRole('button',{name:'核对完整账目原件',exact:true}).click();await expect(drawer.getByRole('article',{name:'已核对住院账目原件'})).toBeVisible();await drawer.getByRole('button',{name:'选择本件完整账目',exact:true}).click();await drawer.getByLabel('完整账目可选问题',{exact:true}).fill(s.packet.request.input.question);await expect(drawer.getByRole('button',{name:'提交待人工核对任务',exact:true})).toBeEnabled();await drawer.getByRole('button',{name:'提交待人工核对任务',exact:true}).click();await expect(drawer.getByLabel('本件账目任务状态')).toContainText('已接收部分模型问题',{timeout:15000});await expect(drawer.getByLabel('完整冻结五类账目计数')).toContainText('收费原行65条');await expect(drawer.getByLabel('部分模型问题覆盖范围')).toContainText('覆盖范围不完整');
 expect(s.writes.filter(c=>c.path==='/api/ai/runs').map(c=>c.body)).toEqual([s.packet.request]);expect(s.writes.filter(c=>!c.path.startsWith('/api/ai/'))).toEqual([]);expect(s.unhandled).toEqual([]);expect(s.errors).toEqual([]);
}
async function checkOutpatientBillingEntry(page,options={}){const s=await setupBillingEntry(page,{...options,mode:'outpatient'});await expect(page.getByText('AI 完整账目核对请从住院收费记录进入',{exact:true})).toBeVisible();await expect(page.getByRole('button',{name:'AI 账务核对',exact:true})).toHaveCount(0);expect(s.calls.filter(c=>c.path.startsWith('/api/ai/'))).toEqual([]);expect(s.writes).toEqual([]);expect(s.unhandled).toEqual([]);expect(s.errors).toEqual([]);}
module.exports={setupBillingEntry,checkInpatientBillingEntry,checkOutpatientBillingEntry};
