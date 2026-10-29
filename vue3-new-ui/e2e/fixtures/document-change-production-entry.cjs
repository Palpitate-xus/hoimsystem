const {startCodingProductionServer,styles}=require('./coding-production-entry.cjs');
const actual=require('./document-change-production/actual.json');
async function setupDocumentChangeProduction(page,server,{role='super_admin'}={}){
 const s={packet:actual,bootstrap:[],reads:[],writes:[],errors:[],unexpected:[],external:[],cssErrors:[],releases:{},completed:[]};page.__documentChangeProduction=s;page.on('pageerror',e=>s.errors.push(e.message));page.on('response',r=>{if(new URL(r.url()).pathname.endsWith('.css')&&r.status()>=400)s.cssErrors.push(r.url());});
 await page.addInitScript(()=>localStorage.setItem('hoim-token','synthetic-document-change-production'));
 await page.context().route('**/*',route=>{if(new URL(route.request().url()).origin===server.origin)return route.continue();s.external.push(route.request().url());return route.abort();});
 await page.route('**/api/**',async route=>{
  const r=route.request(),u=new URL(r.url()),path=u.pathname,method=r.method(),query=Object.fromEntries(u.searchParams),call={method,path,query},p=s.packet,v=p.states.succeeded;let response;
  if(path==='/api/userInfo'&&method==='POST'){s.bootstrap.push(call);return route.fulfill({json:{code:200,data:{username:'synthetic-document-change-super',permissions:[role],avatar:''}}});}
  if(path==='/api/events/stream'&&method==='GET')return route.fulfill({status:204,body:''});
  if(method==='GET')s.reads.push(call);else s.writes.push({...call,body:r.postDataJSON()});
  const scopeId=p.live.scope.data.snapshot.scope_id;
  if(method==='GET'&&path==='/api/ai/features')response=role==='super_admin'?p.live.features:{code:200,data:[]};
  if(method==='GET'&&path==='/api/ai/admin/document-changes/options')response=p.live.options;
  if(method==='GET'&&path==='/api/ai/admin/document-changes/links')response=p.live.link_directory;
  if(method==='GET'&&path==='/api/ai/admin/document-changes/scopes')response=p.live.scope_directory;
  if(method==='GET'&&path===`/api/ai/admin/document-changes/scopes/${scopeId}`)response=p.live.scope;
  if(method==='GET'&&path===`/api/ai/admin/document-changes/scopes/${scopeId}/public-source`)response=p.live.public_source;
  if(method==='GET'&&path==='/api/ai/admin/document-evidence/originals')response=p.live.original_directory;
  if(method==='POST'&&path==='/api/ai/document-change/context')response=p.preview;
  if(method==='POST'&&path==='/api/ai/runs')response=v.receipt;
  if(method==='GET'&&path==='/api/ai/runs')response=p.history;
  if(method==='GET'&&path==='/api/ai/admin/runs')response=p.admin_history;
  if(method==='GET')for(const state of Object.values(p.states).filter(state=>state.detail.data.run_id!==p.states.cancelled.detail.data.run_id||state.detail.data.status==='cancelled')){
   const id=state.detail.data.run_id;
   if(path===`/api/ai/runs/${id}`)response=state.detail;
   if(path===`/api/ai/admin/runs/${id}`)response=state.trace;
   for(const kind of ['source','scope','result'])if(path===`/api/ai/${path.startsWith('/api/ai/admin/')?'admin/':''}runs/${id}/document-change/${kind}`)response=state[kind];
  }
  if(method==='POST'&&path===`/api/ai/runs/${v.detail.data.run_id}/feedback`)response=p.feedback;
  if(!response&&method==='GET'&&path.startsWith('/api/ai/admin/'))response=p.management[path.slice('/api/ai/admin/'.length)];
  if(!response){s.unexpected.push(call);return route.fulfill({status:599,json:{code:599,msg:'未声明的合成生产路由'}});}
  response=structuredClone(response);if(s.mutate)s.mutate(response,path,method);
  const held=s.hold?.(path,method);if(held)await new Promise(resolve=>s.releases[held]=resolve);
  try{return await route.fulfill({json:response});}finally{if(held)s.completed.push(held);}
 });return s;
}
async function openDocumentChangeBusiness(page,server){await page.goto(server.origin+'/#/ai/workbench?feature=guideline_change_review');const panel=page.getByLabel('双原文核对问题任务',{exact:true});await panel.getByRole('button',{name:'刷新比较范围目录',exact:true}).waitFor();return panel;}
async function chooseDocumentChange(page,panel,packet){const {expect}=require('@playwright/test'),id=packet.live.scope.data.snapshot.scope_id;await panel.getByRole('row').filter({hasText:id}).getByRole('button',{name:'读取完整件并选择',exact:true}).click();await expect(panel.getByLabel('已核对完整双原文范围',{exact:true})).toBeVisible();await panel.getByLabel('双原文可选问题',{exact:true}).fill(packet.requests.create.input.question);
 // The frozen synthetic task contains CRLF. A textarea normalizes line endings;
 // initialize the task's raw binding explicitly before checking its exact bytes.
 await page.evaluate(raw=>{const pending=[document.querySelector('#hoim')._vnode],seen=new Set();while(pending.length){const node=pending.pop();if(!node||typeof node!=='object'||seen.has(node))continue;seen.add(node);const handler=node.props?.['onUpdate:modelValue'];if(node.props?.['aria-label']==='双原文可选问题'&&typeof handler==='function'){handler(raw);return;}if(node.component)pending.push(node.component.subTree);if(Array.isArray(node.children))pending.push(...node.children);if(node.suspense)pending.push(node.suspense.activeBranch);}throw new Error('Document question model binding not found');},packet.requests.create.input.question);
await panel.getByText('明确以超级管理员试运行',{exact:true}).click();await expect(panel.getByRole('button',{name:'生成未核实核对问题',exact:true})).toBeEnabled();}
module.exports={actual,startDocumentChangeProductionServer:startCodingProductionServer,setupDocumentChangeProduction,openDocumentChangeBusiness,chooseDocumentChange,styles};
