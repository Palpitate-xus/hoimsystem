const fixture=require('./document-extraction-input/actual.json');
const clone=v=>JSON.parse(JSON.stringify(v));
async function setupDocumentExtractionInput(page,config={}){
 const context={calls:[],errors:[],unexpected:[]},f=fixture,oid=f.original_published.snapshot.original_id,lid=f.large_original.snapshot.original_id;
 page.on('pageerror',error=>context.errors.push(String(error)));page.__documentInputContext=context;
 await page.route('**/api/ai/admin/document-evidence/**',async route=>{
  const req=route.request(),url=new URL(req.url()),path=url.pathname.split('/document-evidence')[1],method=req.method();context.calls.push({method,path,query:Object.fromEntries(url.searchParams)});let value;
  if(method==='GET'&&path==='/originals'){
   const currentPage=Number(url.searchParams.get('page')),size=Number(url.searchParams.get('page_size'));
   if(size===20)value=config.pagination?f.pages.find(p=>p.page===currentPage):currentPage===1?f.directories[config.directory||'small']:undefined;
  }else if(method==='GET'&&path===`/originals/${oid}`)value=config.currentOriginal==='draft'?f.original_draft:config.currentOriginal==='revoked'?f.original_revoked:f.original_published;
  else if(method==='GET'&&path===`/originals/${lid}`)value=f.large_original;
  if(value===undefined){context.unexpected.push({method,path,query:Object.fromEntries(url.searchParams)});return route.fulfill({status:404,json:{detail:'No actual fixture for this request'}});}
  value=clone(value);if(config.beforeResponse)await config.beforeResponse({method,path,context,value});
  const status=config.status?.({method,path,context});if(status)return route.fulfill({status,json:{detail:'synthetic current authorization or source conflict'}});
  if(config.mutate)value=await config.mutate(value,{method,path,context});
  return route.fulfill({json:{code:200,msg:'success',data:value}});
 });return context;
}
module.exports={setupDocumentExtractionInput,fixture};
