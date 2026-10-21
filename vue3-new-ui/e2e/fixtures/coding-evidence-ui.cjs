const{expect}=require('@playwright/test');
async function routeCodingEvidence(page,packet){
 const calls=[],fail=new Map(),hold=new Map(),respond=new Map(),unhandled=[];
 await page.route('**/api/**',async route=>{
  const req=route.request(),url=new URL(req.url()),key=req.method()+' '+url.pathname;calls.push({key,query:Object.fromEntries(url.searchParams),body:req.postData()?req.postDataJSON():null});
  if(hold.has(key)){const gate=hold.get(key);gate.started=true;await gate.promise;}
  if(fail.has(key)){const status=fail.get(key);fail.delete(key);await route.fulfill({status,contentType:'application/json',body:JSON.stringify({code:status,msg:'合成当前授权或原件不可用'})});return;}
  if(respond.has(key)){const response=respond.get(key);const data=typeof response==='function'?await response(req,url):response;await route.fulfill({status:200,contentType:'application/json',body:JSON.stringify({code:200,msg:'success',data})});return;}
  let data;
  if(key==='GET /api/ai/coding-evidence/options')data=packet.options;
  else if(key==='GET /api/ai/coding-evidence/homes')data=packet.homes;
  else if(key==='GET /api/ai/coding-evidence/rules')data=packet.rules;
  else if(key==='GET /api/ai/coding-evidence/cases')data=url.searchParams.get('audit_only')==='true'?packet.audit_directory:packet.directory;
  else if(key==='GET /api/ai/coding-evidence/packages')data=url.searchParams.get('audit_only')==='true'?packet.package_audit_directory:packet.package_directory;
  else if(key==='GET /api/ai/coding-evidence/cases/'+packet.published.case_snapshot_id)data=url.searchParams.get('audit_only')==='true'?packet.published_super:packet.published;
  else if(key==='GET /api/ai/coding-evidence/cases/'+packet.reject_draft.case_snapshot_id)data=url.searchParams.get('audit_only')==='true'?packet.rejected_audit:packet.rejected_ordinary;
  else if(key==='GET /api/ai/coding-evidence/packages/'+packet.package_published.package_id)data=url.searchParams.get('audit_only')==='true'?packet.package_published_audit:packet.package_published;
  else if(key==='POST /api/ai/coding-evidence/cases/preview')data=packet.preview;
  else if(key==='POST /api/ai/coding-evidence/cases')data=packet.draft;
  else if(key==='POST /api/ai/coding-evidence/packages')data=packet.package_draft;
  else{unhandled.push(key);await route.fulfill({status:599,contentType:'application/json',body:JSON.stringify({code:599,msg:'未明确模拟的请求'})});return;}
  await route.fulfill({status:200,contentType:'application/json',body:JSON.stringify({code:200,msg:'success',data})});
 });
 return{calls,fail,respond,unhandled,hold(key){let release;const entry={started:false,promise:new Promise(resolve=>{release=resolve;})};hold.set(key,entry);return{get started(){return entry.started;},release(){hold.delete(key);release();}};}};
}
async function openCoding(page,harness,packet,{role='doctor',bound=true,auditOnly=false,initialReferences=null}={}){
 const network=await routeCodingEvidence(page,packet),errors=[];network.respond.set('GET /api/ai/coding-evidence/options',role==='super_admin'?packet.super_options:packet.options);page.on('pageerror',e=>errors.push(String(e)));await page.goto(harness.origin);await expect.poll(()=>page.evaluate(()=>!!window.__codingProbe)).toBe(true);
 await page.evaluate(({scope,role,auditOnly,initialReferences,bound})=>{const p=window.__codingProbe;p.store.commit('user/permissions',[role]);Object.assign(p.scope,{patientId:scope.patient_id,admissionId:scope.admission_id,homeId:bound?scope.home_id:null,auditOnly,initialReferences});},{scope:packet.scope,role,auditOnly,initialReferences,bound});
 return{...network,errors};
}
async function inspectPublished(page,packet){const row=page.locator('tr').filter({hasText:packet.published.case_snapshot_id});await row.getByRole('button',{name:'核对完整原件',exact:true}).click();await expect(page.getByRole('article',{name:'已核对编码依据完整原件'})).toBeVisible();}
async function choosePublished(page,packet){await inspectPublished(page,packet);await page.getByRole('button',{name:'选择本条受审编码快照',exact:true}).click();}
module.exports={routeCodingEvidence,openCoding,inspectPublished,choosePublished};
