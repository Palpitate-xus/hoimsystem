const {startCodingProductionServer,styles}=require('./coding-production-entry.cjs');
const actual=require('./document-extraction-assistant/actual.json');
const clone=value=>structuredClone(value);
async function setupDocumentProduction(page,server,{kind='chat',role='super_admin'}={}){
 const packet=actual[kind],s={packet,reads:[],writes:[],bootstrap:[],errors:[],unexpected:[],external:[],cssErrors:[],releases:{},completed:[],status:'succeeded'};
 page.__documentProduction=s;page.on('pageerror',error=>s.errors.push(error.message));page.on('response',response=>{if(new URL(response.url()).pathname.endsWith('.css')&&response.status()>=400)s.cssErrors.push(response.url());});
 await page.addInitScript(()=>localStorage.setItem('hoim-token','synthetic-document-production-session'));
 await page.context().route('**/*',route=>{if(new URL(route.request().url()).origin===server.origin)return route.continue();s.external.push(route.request().url());return route.abort();});
 await page.route('**/api/**',async route=>{
  const req=route.request(),u=new URL(req.url()),path=u.pathname,method=req.method(),query=Object.fromEntries(u.searchParams),call={method,path,query};let reply;
  if(path==='/api/userInfo'){s.bootstrap.push({method,path,body:req.postDataJSON()});return route.fulfill({json:{code:200,data:{username:'synthetic-document-production-author',permissions:[role],avatar:''}}});}
  if(path==='/api/events/stream'&&method==='GET')return route.fulfill({status:204,body:''});
  if(method==='GET')s.reads.push(call);else s.writes.push({...call,body:req.postDataJSON()});
  const succeeded=packet.states.succeeded,original=succeeded.detail.data.document_original,id=original.snapshot.original_id;
  if(path==='/api/ai/features'&&method==='GET')reply=role==='super_admin'?packet.features:{code:200,data:[]};
  else if(path==='/api/ai/admin/document-evidence/options'&&method==='GET')reply=packet.source_directories.options;
  else if(path==='/api/ai/admin/document-evidence/originals'&&method==='GET')reply=packet.original_directory;
  // The body below is the exact real same-case Original DTO retained by Run;
  // only its standard Source-GET success wrapper is supplied by this replay.
  else if(path==='/api/ai/admin/document-evidence/originals/'+id&&method==='GET')reply={code:200,msg:'success',data:original};
  else if(path==='/api/ai/admin/document-evidence/candidates'&&method==='GET')reply=packet.source_directories.candidates;
  else if(path==='/api/ai/admin/document-evidence/publications'&&method==='GET')reply=packet.source_directories.publications;
  else if(path==='/api/ai/document-extraction/context'&&method==='POST')reply=packet.preview;
  else if(path==='/api/ai/runs'&&method==='POST')reply=packet.states.queued.receipt;
  else if(path==='/api/ai/runs'&&method==='GET')reply=packet.history.ordinary;
  else if(path==='/api/ai/admin/runs'&&method==='GET')reply=packet.history.admin;
  else if(path==='/api/ai/runs/'+succeeded.detail.data.run_id+'/document-candidates'&&method==='POST')reply=succeeded.saved_candidate;
  else if(path==='/api/ai/runs/'+succeeded.detail.data.run_id+'/feedback'&&method==='POST')reply=packet.feedback_ack;
  else if(method==='GET'){
   const entry=Object.values(packet.states).find(value=>path==='/api/ai/runs/'+value.detail.data.run_id||path==='/api/ai/admin/runs/'+value.detail.data.run_id);
   if(entry){const state=entry.detail.data.run_id===succeeded.detail.data.run_id?packet.states[s.status]:entry;reply=path.startsWith('/api/ai/admin/')?state.trace:state.detail;}
   else if(path.startsWith('/api/ai/admin/'))reply=packet.management[path.slice('/api/ai/admin/'.length)];
  }
  if(!reply){s.unexpected.push(call);return route.fulfill({status:599,json:{code:599,msg:'No explicit synthetic document route'}});}
  const value=clone(reply);if(s.mutate)s.mutate(value,path,method);
  const held=s.hold?.(method,path);if(held)await new Promise(resolve=>s.releases[held]=resolve);
  try{const failure=s.failure?.(method,path);return await route.fulfill(failure?{status:failure,json:{code:failure,msg:'Synthetic current authorization or original changed'}}:{json:value});}finally{if(held)s.completed.push(held);}
 });return s;
}
async function openDocumentBusiness(page,server){await page.goto(server.origin+'/#/ai/workbench?feature=guideline_ingestion');const panel=page.getByLabel('原文条款抽取任务',{exact:true});await panel.getByRole('button',{name:'选择并核对完整原件',exact:true}).first().waitFor();return panel;}
async function chooseDocumentOriginal(page,panel,packet){const {expect}=require('@playwright/test');await panel.getByRole('button',{name:'选择并核对完整原件',exact:true}).first().click();await expect(panel.getByLabel('已核对抽取原件',{exact:true})).toBeVisible();await panel.getByLabel('原文抽取可选问题',{exact:true}).fill(packet.request.input.question);await expect(panel.getByRole('button',{name:'提交未审核条款抽取',exact:true})).toBeEnabled();}
module.exports={actual,startDocumentProductionServer:startCodingProductionServer,setupDocumentProduction,openDocumentBusiness,chooseDocumentOriginal,styles};
