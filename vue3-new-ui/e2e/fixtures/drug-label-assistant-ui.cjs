const assert=require('node:assert/strict');
const {load}=require('./load-drug-label-assistant-main.cjs');
const {load:loadSql}=require('./load-drug-label-tasks.cjs');
const success=data=>({code:200,msg:'success',data});
async function openDrugLabelAssistant(page,harness,{kind='chat',scope={},profile='main',role='pharmacist',initial=true}={}){
 const p=load(kind),sql=loadSql(kind),first=profile==='sql'?sql.states.succeeded.detail:p.full.data,source=profile==='main'&&role==='super_admin'?p.source_super.data:first.drug_label_findings.drug_label_source_record,id=first.drug_label_source_binding_id;
 const state={p,sql,id,source,first,calls:[],errors:[],hold:null,held:[],deny:null,mutate:null,details:profile==='sql'?[sql.states.queued.detail,sql.states.running.detail,sql.states.succeeded.detail]:[role==='super_admin'?p.super_full.data:p.full.data],history:profile==='sql'?Object.entries(sql.states).filter(([k])=>['succeeded','failed_partial_usage','cancelled_zero','cancelled_pending'].includes(k)).map(([,v])=>v.summary):p.history.data};
 state.release=()=>{state.hold=null;for(const fn of state.held.splice(0))fn();};
 state.sourceGets=()=>state.calls.filter(c=>c.method==='GET'&&c.path==='/api/ai/drug-label-sources/'+id);
 await page.addInitScript(({feature,input,role,scope})=>{window.__drugLabelTaskRole=role;window.__drugLabelTaskScope={feature,initialInput:input,...scope};},{feature:p.feature,input:initial?first.drug_label_findings.input:{},role,scope});
 page.on('pageerror',error=>state.errors.push(String(error)));
 await page.route('**/api/ai/**',async route=>{
  const r=route.request(),u=new URL(r.url()),call={method:r.method(),path:u.pathname,query:Object.fromEntries(u.searchParams),body:r.method()==='POST'&&r.postData()?r.postDataJSON():null,token:r.headers().accesstoken,content:r.headers()['content-type']};state.calls.push(call);
  let response,status=200;
  try{
   if(state.deny&&state.deny(call))status=state.deny.status||403;
   else if(call.path==='/api/ai/drug-label-sources/options')response=role==='super_admin'?p.options_super:p.options;
   else if(call.path==='/api/ai/drug-label-sources/catalog')response=p.catalog;
   else if(call.path==='/api/ai/drug-label-sources'&&call.method==='GET')response=p.directory;
   else if(call.path==='/api/ai/drug-label-sources/'+id){assert.equal(call.query.audit_only,'false');response=success(source);}
   else if(call.path==='/api/ai/drug-label/context'){assert.deepEqual(call.body,first.drug_label_findings.input);response=p.preview;}
   else if(call.path==='/api/ai/runs'&&call.method==='POST'){assert.deepEqual(call.body,{feature_key:'drug_label_extraction',input:first.drug_label_findings.input,preview:false});response=profile==='sql'?success(sql.states.queued.summary):p.queued;}
   else if(call.path==='/api/ai/runs'&&call.method==='GET'){assert.deepEqual(call.query,{feature_key:'drug_label_extraction',drug_label_source_binding_id:id});response=success(state.history);}
   else if(call.path.startsWith('/api/ai/admin/runs/'))response=p.trace;
   else if(call.path.match(/^\/api\/ai\/runs\/[^/]+$/)&&call.method==='GET'){
    const runId=call.path.split('/').pop();let v=state.details.length>1?state.details.shift():state.details[0];assert.equal(v.run_id,runId);response=success(v);
   }else if(call.path.endsWith('/feedback')){assert(['accepted','modified','rejected'].includes(call.body.outcome));response=success({run_id:call.path.split('/').at(-2),outcome:call.body.outcome,comment:call.body.comment});}
   else if(call.path.endsWith('/cancel'))response=success({run_id:call.path.split('/').at(-2),status:'cancelled'});
   else{state.errors.push('Unhandled '+call.method+' '+call.path);status=404;}
  }catch(error){state.errors.push(String(error));status=422;}
  if(state.mutate)response=await state.mutate(response,call);
  if(state.hold?.(call))await new Promise(resolve=>state.held.push(resolve));
  await route.fulfill({status,contentType:'application/json',body:JSON.stringify(status===200?response:{code:status,msg:'synthetic current boundary unavailable',data:null})});
 });
 await page.goto(harness.origin);await page.waitForFunction(()=>!!window.__drugLabelTaskProbe);return state;
}
async function selectSource(page){await page.getByRole('button',{name:'重新核对明确来源',exact:true}).click();await page.getByLabel('说明书本次来源已核对').waitFor();}
async function choose(page,label,text){const input=page.getByRole('combobox',{name:label,exact:true});await input.press('ArrowDown');const id=await input.getAttribute('aria-controls');await page.locator('[id="'+id+'"]').getByRole('option',{name:text,exact:true}).click();}
module.exports={openDrugLabelAssistant,selectSource,choose};
