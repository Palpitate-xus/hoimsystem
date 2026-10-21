const assert=require('node:assert/strict'),fixture=require('./document-extraction-assistant/actual.json'),clone=v=>JSON.parse(JSON.stringify(v));
async function setupDocumentExtractionAssistant(page,config={}){
 const f=fixture[config.kind||'chat'],success=f.states.succeeded,oid=success.detail.data.document_original_id,main=success.detail.data.run_id,failed=f.states.failed.detail.data.run_id,cancelled=f.states.cancelled.detail.data.run_id;
 const context={calls:[],errors:[],unexpected:[],reads:{},cancelled:false};page.on('pageerror',e=>context.errors.push(String(e)));
 function packet(id,type){const key=id+'/'+type,index=context.reads[key]||0;context.reads[key]=index+1;if(id===main)return config.flow==='progress'?[f.states.queued,f.states.running,success][Math.min(index,2)]:success;if(id===failed)return f.states.failed;if(id===cancelled)return context.cancelled?f.states.cancelled:config.flow==='cancel'?f.before_cancel:f.states.cancelled;return null;}
 await page.route('**/api/**',async route=>{const req=route.request(),url=new URL(req.url()),path=url.pathname.replace(/^\/api\//u,''),method=req.method(),data=method==='POST'?req.postDataJSON():null;context.calls.push({method,path,query:Object.fromEntries(url.searchParams),data});let value,expected;
 if(method==='GET'){
  if(path==='ai/features'){value=clone(f.features.data);if(config.featuresMutate)value=config.featuresMutate(value);}
  else if(path==='ai/admin/document-evidence/originals')value=f.original_directory.data;
  else if(path==='ai/admin/document-evidence/originals/'+oid)value=success.detail.data.document_original;
  else if(path==='ai/runs'){assert.equal(url.searchParams.get('feature_key'),'guideline_ingestion');assert.equal(url.searchParams.get('document_original_id'),oid);value=f.history.ordinary.data;}
  else {const match=/^ai\/(admin\/)?runs\/([a-f0-9-]+)$/u.exec(path);if(match){const p=packet(match[2],match[1]?'trace':'detail');if(p)value=p[match[1]?'trace':'detail'].data;}}
 }else if(method==='POST'){
  if(path==='ai/document-extraction/context'){expected=f.request.input;value=f.preview.data;}
  else if(path==='ai/runs'){expected={...f.request,preview:false};value=(config.flow==='failed'?f.states.failed:config.flow==='cancel'?f.states.cancelled:f.states.queued).receipt.data;}
  else if(path==='ai/runs/'+main+'/document-candidates'){expected=success.save_request;value=success.saved_candidate.data;}
  else if(path==='ai/runs/'+main+'/feedback'){expected=f.feedback_request;value=f.feedback_ack;}
  else if(path==='ai/runs/'+cancelled+'/cancel'){context.cancelled=true;value=f.cancel_ack;}
 }
 if(value===undefined){context.unexpected.push({method,path});return route.fulfill({status:404,json:{detail:'No actual samecase response for this request'}});}
 if(expected)try{assert.deepEqual(data,expected);}catch(error){context.errors.push(String(error));return route.fulfill({status:422,json:{detail:'Expected exact samecase body'}});}
 value=clone(value);if(config.beforeResponse)await config.beforeResponse({method,path,value,context});const status=config.status?.({method,path,context});if(status)return route.fulfill({status,json:{detail:'Synthetic current authorization/source/config conflict'}});if(config.mutate)value=await config.mutate(value,{method,path,context});
 if(method==='POST'&&(path.endsWith('/feedback')||path.endsWith('/cancel')))return route.fulfill({json:value});return route.fulfill({json:{code:200,msg:'success',data:value}});
 });page.__documentAssistantContext=context;return context;
}
module.exports={fixture,setupDocumentExtractionAssistant};
