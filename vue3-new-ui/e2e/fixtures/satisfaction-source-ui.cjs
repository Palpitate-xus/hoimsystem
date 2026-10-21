const{expect}=require('@playwright/test');
async function routeSatisfaction(page,p,{role='admin',state='published',reject=false}={}){
 const calls=[],unexpected=[],hold=new Map(),fail=new Map(),respond=new Map(),config={role,state,reject};
 const base='/api/ai/satisfaction-sources',primary=p.published.case_id,secondary=p.reject_draft.case_id;
 await page.route('**/api/**',async route=>{
  const request=route.request(),url=new URL(request.url()),key=request.method()+' '+url.pathname;calls.push({key,params:[...url.searchParams],body:request.postData()?request.postDataJSON():null});
  if(hold.has(key)){const value=hold.get(key);hold.delete(key);value.started=true;await value.promise;if(value.status){await route.fulfill({status:value.status,contentType:'application/json',body:JSON.stringify({code:value.status,msg:'隔离合成旧请求失效'})});return;}}
  if(fail.has(key)){const status=fail.get(key);fail.delete(key);await route.fulfill({status,contentType:'application/json',body:JSON.stringify({code:status,msg:'隔离合成当前原件或权限已失效'})});return;}
  if(respond.has(key)){const value=respond.get(key);await route.fulfill({status:200,contentType:'application/json',body:JSON.stringify({code:200,msg:'success',data:typeof value==='function'?await value(request,url):value})});return;}
  let data;
  if(key==='GET '+base+'/options')data=p[config.role==='super_admin'?'super_options':config.role==='director'?'director_options':'admin_options'];
  else if(key==='GET '+base+'/doctors')data=config.role==='director'?p.director_doctors:p.doctors;
  else if(key==='GET '+base+'/cases'){
   const audit=url.searchParams.get('audit_only')==='true';
   if(!audit&&!p.scope.doctor_ids.every(id=>url.searchParams.getAll('doctor_ids').includes(String(id)))){unexpected.push('doctor_ids query not repeated exactly');await route.fulfill({status:422,body:'{}'});return;}
   data=config.reject?(config.state==='draft'?p.reject_draft_directory:p.rejected_directory):config.state==='precreate'?(audit?p.precreate_audit_directory:p.precreate_directory):config.state==='draft'?(audit?p.draft_audit_directory:p.draft_directory):config.state==='revoked'?(audit?p.revoked_audit_directory:p.revoked_directory):(audit?p.audit_directory:p.directory);
  }else if(key==='GET '+base+'/cases/'+primary){const audit=url.searchParams.get('audit_only')==='true';data=config.state==='draft'?(audit?p.super_draft:p.draft):config.state==='revoked'?(audit?p.revoked_audit:p.revoked_ordinary):(audit?p.published_super:config.role==='super_admin'?p.published_super_ordinary:p.published);}
  else if(key==='GET '+base+'/cases/'+secondary){const audit=url.searchParams.get('audit_only')==='true';data=config.state==='draft'?(audit?p.reject_super_draft:p.reject_draft):(audit?p.rejected_audit:p.rejected_ordinary);}
  else if(key==='POST '+base+'/cases/preview')data=p.preview;
  else if(key==='POST '+base+'/cases'){data=p.draft;config.state='draft';}
  else if(key==='POST '+base+'/cases/'+primary+'/review'){data=p.published_super;config.state='published';}
  else if(key==='POST '+base+'/cases/'+secondary+'/review'){data=p.rejected_audit;config.state='rejected';}
  else if(key==='POST '+base+'/cases/'+primary+'/revoke'){data=p.revoked_audit;config.state='revoked';}
  else{unexpected.push(key);await route.fulfill({status:599,contentType:'application/json',body:JSON.stringify({code:599,msg:'未明确拦截的合成API'})});return;}
  await route.fulfill({status:200,contentType:'application/json',body:JSON.stringify({code:200,msg:'success',data})});
 });
 return{calls,unexpected,config,fail,respond,hold(key){let release;const value={started:false,promise:new Promise(r=>{release=r;})};hold.set(key,value);return{get started(){return value.started;},release(status=null){value.status=status;release();}};}};
}
async function openSatisfaction(page,harness,p,options={}){const network=await routeSatisfaction(page,p,options),errors=[];if(options.setup)options.setup(network);page.on('pageerror',e=>errors.push(String(e)));await page.goto(harness.origin);await expect.poll(()=>page.evaluate(()=>!!window.__satisfactionProbe)).toBe(true);if(options.beforeActivate)await options.beforeActivate(page,network);await page.evaluate(({role,auditOnly,initialReferences})=>{const v=window.__satisfactionProbe;v.store.commit('user/permissions',[role]);v.scope.auditOnly=auditOnly;v.scope.initialReferences=initialReferences;},{role:options.role||'admin',auditOnly:options.auditOnly||false,initialReferences:options.initialReferences||null});return{...network,errors};}
async function chooseScope(page,p){await expect(page.getByRole('combobox',{name:'明确评价范围'})).toBeVisible();await page.locator('.el-select').filter({has:page.getByRole('combobox',{name:'明确评价范围'})}).locator('.el-select__wrapper').click();await page.getByRole('option',{name:'显式有限医生集合',exact:true}).click();await page.locator('.el-select').filter({has:page.getByRole('combobox',{name:'实际医生集合'})}).locator('.el-select__wrapper').click();const d=p.doctors.items.find(r=>r.doctor_id===p.scope.doctor_ids[0]);await page.getByRole('option',{name:`${d.name} · 医生 ${d.doctor_id}`,exact:true}).click();await page.keyboard.press('Escape');await page.locator('input[type=date]').nth(0).fill(p.scope.date_from);await page.locator('input[type=date]').nth(1).fill(p.scope.date_to);}
async function inspectCase(page,id){const row=page.locator('tr').filter({hasText:id});await row.getByRole('button',{name:'核对安全原件',exact:true}).click();await expect(page.getByRole('article',{name:'已核对完整评价证据'})).toBeVisible();}
async function holdSatisfactionCrypto(page){await page.evaluate(()=>{const p=window.__satisfactionProbe,original=crypto.subtle.digest.bind(crypto.subtle);let release,armed=true;const promise=new Promise(r=>{release=r;});p.cryptoGate={started:false,release};crypto.subtle.digest=async(...args)=>{if(armed){armed=false;p.cryptoGate.started=true;await promise;}return original(...args);};});return{started:()=>page.evaluate(()=>window.__satisfactionProbe.cryptoGate.started),release:()=>page.evaluate(()=>window.__satisfactionProbe.cryptoGate.release())};}
module.exports={routeSatisfaction,openSatisfaction,chooseScope,inspectCase,holdSatisfactionCrypto};
