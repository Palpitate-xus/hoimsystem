const assert=require('node:assert/strict'),fixture=require('./document-extraction-results/actual.json'),clone=v=>JSON.parse(JSON.stringify(v));
async function setupDocumentExtractionFindings(page,config={}){
 const packet=config.packet||fixture[config.kind||'chat'],run=packet.detail.data,context={calls:[],errors:[],unexpected:[]};page.on('pageerror',error=>context.errors.push(String(error)));
 await page.route('**/api/**',async route=>{const req=route.request(),url=new URL(req.url()),path=url.pathname.replace(/^\/api\//u,''),method=req.method();context.calls.push({method,path,data:method==='POST'?req.postDataJSON():null});let value;
 if(method==='GET'&&path===`ai/admin/runs/${run.run_id}`)value=packet.trace.data;
 if(method==='GET'&&path===`ai/admin/document-evidence/originals/${run.document_original_id}`)value=run.document_original;
 if(method==='POST'&&path===`ai/runs/${run.run_id}/document-candidates`){try{assert.deepEqual(req.postDataJSON(),packet.save_request);}catch(error){context.errors.push(String(error));return route.fulfill({status:422,json:{detail:'Expected exact actual ordinal request'}});}value=packet.saved_candidate.data;}
 if(value===undefined){context.unexpected.push({method,path});return route.fulfill({status:404,json:{detail:'No actual samecase packet'}});}
 value=clone(value);if(config.beforeResponse)await config.beforeResponse({method,path,value,context});const status=config.status?.({method,path,context});if(status)return route.fulfill({status,json:{detail:'Synthetic authorization/current-original conflict'}});if(config.mutate)value=await config.mutate(value,{method,path,context});return route.fulfill({json:{code:200,msg:'success',data:value}});
 });page.__documentResultContext=context;return context;
}
module.exports={setupDocumentExtractionFindings,fixture};
