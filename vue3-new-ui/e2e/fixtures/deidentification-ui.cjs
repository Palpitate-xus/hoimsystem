const{expect}=require('@playwright/test'),{actual}=require('./deidentification-packets.cjs');
const packet=actual(),p=Object.fromEntries(Object.entries(packet.packets).map(([k,v])=>[k,v.data||v]));
async function setupDeidentification(page,harness,{role='admin',auditOnly=false,scope=packet.scope_request,source='case_published',hold=null,fail=null,directory='directory_published'}={}){
 const state={reads:[],writes:[],errors:[],held:[],source,review:role==='super_admin'?'review_draft_super':'review_draft',release:role==='super_admin'?'release_draft_super':'release_draft',closed:false};page.on('pageerror',e=>state.errors.push(e.message));
 await page.route('**/api/**',async route=>{const req=route.request(),url=new URL(req.url()),path=url.pathname.replace('/api/ai/deidentification/',''),method=req.method();const log={method,path: url.pathname+url.search,body:req.postData()?JSON.parse(req.postData()):null,authorization:req.headers().authorization};(method==='GET'||path==='fields'||path==='cases/directory'?state.reads:state.writes).push(log);
  if(fail?.(log)){await route.fulfill({status:403,contentType:'application/json',body:JSON.stringify({detail:'合成当前授权已撤回'})});return;}
  if(hold?.(log)){await new Promise(resolve=>state.held.push(resolve));}
  let key;
  if(path==='fields')key='fields';else if(path==='cases/directory')key=directory;else if(path==='cases/preview')key='preview';else if(path==='cases'&&method==='POST'){state.source='case_draft';key='case_draft';}
  else if(path===`cases/${p.case_published.case_id}`&&method==='GET')key=url.searchParams.get('audit_only')==='true'?(state.source==='case_patient_permission_lost_super'?state.source:state.source==='case_revoked'?'case_revoked_super':state.source==='case_draft'?'case_draft_super':state.source):state.source;
  else if(path==='reviews'&&method==='POST'){state.review='review_draft';key=state.review;}
  else if(path.startsWith('reviews/')&&path.endsWith('/residual-review')){state.review='review_residual';key=state.review;}
  else if(path.startsWith('reviews/')&&path.endsWith('/review')){state.review='review_published';key=state.review;}
  else if(path.startsWith('reviews/')&&method==='GET')key=state.review;
  else if(path==='releases'&&method==='POST'){state.release='release_draft';key=state.release;}
  else if(path.startsWith('releases/')&&path.endsWith('/authority-review')){state.release='release_authority';key=state.release;}
  else if(path.startsWith('releases/')&&path.endsWith('/review')){state.release='release_published';key=state.release;}
  else if(path.startsWith('releases/')&&path.endsWith('/download')){await route.fulfill({status:200,contentType:'application/json',headers:{'Cache-Control':'no-store','X-Artifact-SHA256':packet.raw_http_responses.download.headers['x-artifact-sha256']},body:packet.raw_http_responses.download.body_utf8});return;}
  else if(path.startsWith('releases/')&&method==='GET')key=state.release;
  if(!key){state.errors.push('Unhandled '+method+' '+path);await route.fulfill({status:404,body:'{}'});return;}
  await route.fulfill({status:200,contentType:'application/json',body:packet.raw_http_responses[key].body_utf8});
 });
 await page.goto(harness.origin);await expect.poll(()=>page.evaluate(()=>!!window.__deidentificationProbe)).toBe(true);
 await page.evaluate(({role,auditOnly,scope})=>{const p=window.__deidentificationProbe;p.store.commit('user/permissions',[role]);p.scope.auditOnly=auditOnly;p.scope.patientId=scope?.patient_id??null;p.scope.scope=scope===null?null:Object.fromEntries(Object.entries(scope).filter(([k])=>k!=='patient_id'));},{role,auditOnly,scope});
 return state;
}
async function select(page,label,option){await page.locator(`[aria-label="${label}"]`).first().locator('xpath=ancestor::div[contains(concat(" ",normalize-space(@class)," ")," el-select ")][1]').click();await page.getByRole('option',{name:option,exact:true}).click();}
async function inspectSource(page){await page.getByRole('button',{name:'刷新完整技术目录',exact:true}).click();await page.getByRole('row').filter({hasText:p.case_published.case_id}).getByRole('button',{name:'显式读取本件完整来源'}).click();await expect(page.getByRole('dialog')).toBeVisible();}
async function inspectChild(page,kind,id){await select(page,'明确已有原件类型',kind==='review'?'人工编辑及残余风险复核':'单件导出放行');await page.getByLabel('明确已有原件标识',{exact:true}).fill(id);await page.getByRole('button',{name:'显式读取明确复核或放行件',exact:true}).click();await expect(page.getByRole('dialog')).toBeVisible();}
module.exports={setupDeidentification,inspectSource,inspectChild,select,packet,p};
