const{expect}=require('@playwright/test');
const base='/api/ai/charge-reconciliation';
const fields=['case_snapshot_id','patient_id','admission_id','schema_version','created_at','created_by','collection_digest','content_hash','status','revision','reviewed_at','revoked_at','source_id'];
const metadata=row=>({...Object.fromEntries(fields.map(k=>[k,row[k]])),detail_required:true});
async function routeChargeSources(page,packet,{row=packet.published,auditOnly=false}={}){
 const calls=[],errors=[],unhandled=[],fail=new Map(),respond=new Map(),held=new Map();let currentRow=row;
 page.on('pageerror',e=>errors.push(String(e)));
 await page.route('**/api/**',async route=>{const req=route.request(),url=new URL(req.url()),key=req.method()+' '+url.pathname;calls.push({key,query:Object.fromEntries(url.searchParams),body:req.postData()?req.postDataJSON():null});
  if(held.has(key)){const gate=held.get(key);gate.started=true;await gate.promise;}
  if(fail.has(key)){const status=fail.get(key);fail.delete(key);await route.fulfill({status,contentType:'application/json',body:JSON.stringify({code:status,msg:'合成当前授权或完整集合不可用'})});return;}
  let data;if(respond.has(key)){const value=respond.get(key);data=typeof value==='function'?await value(req,url):value;}
  else if(key==='GET '+base+'/options'){data=packet.options.data;if(!url.searchParams.has('patient_id'))data={...data,patient_id:null,admission_id:null,can_record:false};}
  else if(key==='GET '+base+'/cases')data={items:[metadata(currentRow)],total:1,page:1,page_size:20};
  else if(key==='GET '+base+'/cases/'+currentRow.case_snapshot_id)data=url.searchParams.get('audit_only')==='true'?(currentRow.case_snapshot_id===packet.published.case_snapshot_id&&currentRow.status==='published'?packet.published_super:currentRow):currentRow;
  else if(key==='POST '+base+'/cases/preview')data=packet.preview;
  else if(key==='POST '+base+'/cases'){currentRow=packet.draft;data=packet.draft;}
  else if(key==='POST '+base+'/cases/'+currentRow.case_snapshot_id+'/review'){const decision=req.postDataJSON().decision;currentRow=decision==='publish'?packet.published:packet.rejected_redacted;data=decision==='publish'?packet.published_super:packet.rejected_super;}
  else if(key==='POST '+base+'/cases/'+currentRow.case_snapshot_id+'/revoke'){currentRow=packet.revoked_redacted;data=packet.revoked_super;}
  else{unhandled.push(key);await route.fulfill({status:599,contentType:'application/json',body:JSON.stringify({code:599,msg:'未明确模拟的请求'})});return;}
  await route.fulfill({status:200,contentType:'application/json',body:JSON.stringify({code:200,msg:'success',data})});
 });
 return{calls,errors,unhandled,fail,respond,setRow(row){currentRow=row;},hold(key){let release;const entry={started:false,promise:new Promise(r=>{release=r;})};held.set(key,entry);return{get started(){return entry.started;},release(){held.delete(key);release();}};}};
}
async function openChargeSources(page,harness,packet,{row=packet.published,auditOnly=false,initialReferences={},bound=true}={}){
 const network=await routeChargeSources(page,packet,{row,auditOnly});await page.goto(harness.origin);await expect.poll(()=>page.evaluate(()=>!!window.__chargeSourceProbe)).toBe(true);
 await page.evaluate(({scope,auditOnly,initialReferences,bound})=>Object.assign(window.__chargeSourceProbe.scope,{patientId:bound?scope.patient_id:null,admissionId:bound?scope.admission_id:null,auditOnly,initialReferences}),{scope:packet.create_request.request,auditOnly,initialReferences,bound});return network;
}
async function inspectCharge(page){await page.getByRole('button',{name:'核对完整账目原件',exact:true}).click();await expect(page.getByRole('article',{name:'已核对住院账目原件'})).toBeVisible();}
async function chooseCharge(page){await inspectCharge(page);await page.getByRole('button',{name:'选择本件完整账目',exact:true}).click();}
async function lastChargeEvent(page,type){return page.evaluate(type=>window.__chargeSourceProbe.events.filter(e=>e.type===type).at(-1)?.value,type);}
async function holdChargeDigest(page){await page.evaluate(()=>{const p=window.__chargeSourceProbe,original=crypto.subtle.digest.bind(crypto.subtle);p.digestStarted=false;p.releaseDigest=null;crypto.subtle.digest=async(...args)=>{if(!p.digestStarted){p.digestStarted=true;await new Promise(r=>p.releaseDigest=r);}return original(...args);};});}
module.exports={base,metadata,routeChargeSources,openChargeSources,inspectCharge,chooseCharge,lastChargeEvent,holdChargeDigest};
