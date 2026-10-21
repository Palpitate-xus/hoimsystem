const assert=require('node:assert/strict');
const f=require('./drug-label-sources/actual.json');
const clone=v=>JSON.parse(JSON.stringify(v));
async function openDrugLabel(page,harness,{family='published',phase='draft',role='super_admin',scope={},mutate=null}={}){
 const state={family,phase,role,calls:[],errors:[],mutate,held:[],hold:null,deny:null};
 const selected=()=>f.states[state.family],sku=f.catalog.items[0].identity.pharmaceutical_id;
 state.row=({audit=false}={})=>{const v=selected();if(audit)return state.phase==='revoked'?v.revoked_super_frozen:state.phase==='withdrawn'?v.withdrawn_super_frozen:v.super_frozen;const superAdmin=state.role==='super_admin';return state.phase==='draft'?v[superAdmin?'draft_super':'draft_pharmacist']:state.phase==='signed'?v[superAdmin?'signed_super':'signed']:state.phase==='reviewed'?v[superAdmin?'reviewed_super':'ordinary_reviewed']:null;};
 state.directory=()=>state.phase==='initial'?f.initial_directory:selected()[({draft:'draft',signed:'signed',reviewed:'reviewed',revoked:'revoked',withdrawn:'withdrawn'})[state.phase]+'_directory'];
 await page.addInitScript(({role,scope})=>{window.__drugLabelRole=role;window.__drugLabelScope=scope;},{role,scope});
 page.on('pageerror',e=>state.errors.push(String(e)));
 await page.route('**/api/ai/**',async route=>{
  const r=route.request(),url=new URL(r.url()),path=url.pathname,call={method:r.method(),path,query:Object.fromEntries(url.searchParams),body:r.method()==='POST'?r.postDataJSON():null,token:r.headers().accesstoken,content:r.headers()['content-type']};state.calls.push(call);
  let data,status=200;
  try{
   const v=selected(),id=v.draft_super.snapshot.source_binding_id,base='/api/ai/drug-label-sources';
   if(state.deny&&state.deny(call))status=state.deny.status||403;
   else if(path===base+'/options')data=f[state.role==='super_admin'?'super_options':'pharmacist_options'];
   else if(path===base+'/catalog')data=Number(url.searchParams.get('page_size'))===1?f.catalog:f.catalog_full;
   else if(path===base&&r.method()==='GET'){
    data=clone(state.directory());if(url.searchParams.get('audit_only')==='true'){data=clone(f.admin_directory);}else if(url.searchParams.has('pharmaceutical_id')&&Number(url.searchParams.get('pharmaceutical_id'))!==sku){data={items:[],next_cursor:null,complete:true,audit_only:false};}
   }else if(path===base&&r.method()==='POST'){assert.deepEqual(call.body,v.create_request);data=v.draft_super;state.phase='draft';}
   else if(path===base+'/'+id&&r.method()==='GET'){data=state.row({audit:url.searchParams.get('audit_only')==='true'});if(!data)status=409;}
   else if(path===base+'/'+id+'/professional-review'){assert.deepEqual(call.body,v.signature_request);data=v.signed;state.phase='signed';}
   else if(path===base+'/'+id+'/review'){assert.deepEqual(call.body,v.technical_review_request);data=v.reviewed_super;state.phase='reviewed';}
   else if(path===base+'/'+id+'/revoke'){assert.deepEqual(call.body,v.source_revoke_request);data=v.source_revoked;state.phase='revoked';}
   else if(path===base+'/'+id+'/professional-review/revoke'){assert.deepEqual(call.body,v.signature_revoke_request);data=v.signature_revoked;state.phase='withdrawn';}
   else if(path==='/api/ai/admin/document-evidence/originals')data=f.original_directory;
   else if(path==='/api/ai/admin/document-evidence/originals/'+f.original_parent.snapshot.original_id)data=f.original_detail;
   else {state.errors.push('Unhandled '+r.method()+' '+path);status=404;}
  }catch(error){state.errors.push(String(error));status=422;}
  if(data&&state.mutate)data=await state.mutate(clone(data),call);
  if(state.hold?.(call))await new Promise(resolve=>state.held.push(resolve));
  await route.fulfill({status,contentType:'application/json',body:JSON.stringify({code:status,msg:status===200?'success':'synthetic unavailable',data:status===200?data:null})});
 });
 state.release=()=>{state.hold=null;for(const resolve of state.held.splice(0))resolve();};
 await page.goto(harness.origin);await page.waitForFunction(()=>!!window.__drugLabelProbe);
 return state;
}
async function choose(page,label,text){const input=page.getByRole('combobox',{name:label,exact:true});await input.press('ArrowDown');const id=await input.getAttribute('aria-controls');await page.locator('[id=\"'+id+'\"]').getByRole('option',{name:text,exact:true}).click();}
async function inspect(page,family='published'){const id=f.states[family].draft_super.snapshot.source_binding_id;await page.getByRole('row').filter({hasText:id}).getByRole('button',{name:'读取本件完整依据',exact:true}).click();await page.getByRole('dialog',{name:'说明书原件与独立签署核对',exact:true}).waitFor();}
async function holdCrypto(page){await page.evaluate(()=>{const original=crypto.subtle.digest.bind(crypto.subtle);window.__drugCrypto=[];crypto.subtle.digest=(...args)=>new Promise(resolve=>window.__drugCrypto.push(()=>original(...args).then(resolve)));window.__drugReleaseCrypto=()=>{crypto.subtle.digest=original;for(const done of window.__drugCrypto.splice(0))done();};});}
module.exports={openDrugLabel,choose,inspect,holdCrypto,fixture:f,sku:f.catalog.items[0].identity.pharmaceutical_id};
