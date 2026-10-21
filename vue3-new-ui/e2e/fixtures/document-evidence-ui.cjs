const assert=require('node:assert/strict');
const fixture=require('./document-evidence/actual.json');
const clone=v=>JSON.parse(JSON.stringify(v));
async function setupDocumentEvidence(page,config={}){
 const context={stage:config.stage||'publication_active',calls:[],errors:[],badBodies:[]},f=fixture,oid=f.original_published.snapshot.original_id,cid=f.candidate_approved.snapshot.candidate_id,pid=f.publication_active.snapshot.publication_id;
 const currentOriginal=()=>['stale','revoked'].includes(context.stage)?f.original_revoked:context.stage==='original_draft'?f.original_draft:f.original_published;
 const currentCandidate=()=>['stale','revoked'].includes(context.stage)?f.candidate_stale:context.stage==='candidate_draft'?f.candidate_draft:f.candidate_approved;
 const currentPublication=()=>context.stage==='revoked'?f.publication_revoked:context.stage==='stale'?f.publication_stale:f.publication_active;
 page.on('pageerror',error=>context.errors.push(String(error)));
 await page.route('**/api/ai/admin/document-evidence/**',async route=>{
  const req=route.request(),url=new URL(req.url()),path=url.pathname.split('/document-evidence')[1],method=req.method();context.calls.push({method,path,data:method==='POST'?req.postDataJSON():null});
  let value,expected;
  if(method==='GET'){
   if(path==='/options')value=f.options;
   else if(['/originals','/candidates','/publications'].includes(path))value=f.directories_by_state[context.stage][path.slice(1)];
   else if(path===`/originals/${oid}`)value=currentOriginal();
   else if(path===`/originals/${f.file_original_draft.snapshot.original_id}`)value=f.file_original_draft;
   else if(path===`/originals/${f.direct_ui_draft.snapshot.original_id}`)value=f.direct_ui_draft;
   else if(path===`/candidates/${cid}`)value=currentCandidate();
   else if(path===`/publications/${pid}`)value=currentPublication();
  }else if(method==='POST'){
   if(path==='/originals'){
    if(req.postDataJSON().content?.kind==='utf8_file'){expected=f.requests.file_create;value=f.file_original_draft;context.stage='file_draft';}
    else {expected=f.requests.direct_ui_create;value=f.direct_ui_draft;context.stage='direct_draft';}
   }else if(path===`/originals/${oid}/review`){expected=f.requests.original_review;value=f.original_published;context.stage='original_published';}
   else if(path===`/originals/${oid}/revoke`){expected=f.requests.original_revoke;value=f.original_revoked;context.stage='stale';}
   else if(path==='/candidates'){expected=f.requests.candidate_create;value=f.candidate_draft;context.stage='candidate_draft';}
   else if(path===`/candidates/${cid}/review`){expected=f.requests.candidate_review;value=f.candidate_approved;context.stage='candidate_approved';}
   else if(path===`/candidates/${cid}/publish`){expected=f.requests.publish;value=f.publication_active;context.stage='publication_active';}
   else if(path===`/publications/${pid}/revoke`){expected=f.requests.publication_revoke;value=f.publication_revoked;context.stage='revoked';}
   if(expected)try{assert.deepEqual(req.postDataJSON(),expected);}catch(error){context.badBodies.push(String(error));return route.fulfill({status:422,json:{detail:'isolated mock received a different exact request'}});}
  }
  if(value===undefined)return route.fulfill({status:404,json:{detail:'No actual fixture for this source request'}});
  value=clone(value);
  if(config.beforeResponse)await config.beforeResponse({method,path,context,value});
  if(config.status){const status=config.status({method,path,context});if(status)return route.fulfill({status,json:{detail:'synthetic current authorization or source conflict'}});}
  if(config.mutate)value=await config.mutate(value,{method,path,context});
  await route.fulfill({json:{code:200,msg:'success',data:value}});
 });
 return context;
}
module.exports={setupDocumentEvidence,fixture};
