const fs=require('node:fs/promises'),path=require('node:path'),http=require('node:http'),crypto=require('node:crypto');
const actual=require('./supply-native/production-entry.json');
const sha=v=>crypto.createHash('sha256').update(v).digest('hex');
async function readFiles(root,dir=root){const out=new Map();for(const entry of await fs.readdir(dir,{withFileTypes:true})){const p=path.join(dir,entry.name);if(entry.isDirectory())for(const[k,v]of await readFiles(root,p))out.set(k,v);else if(entry.isFile())out.set('/'+path.relative(root,p).split(path.sep).join('/'),await fs.readFile(p));}return out;}
async function startSupplyProductionServer(){
 const root=path.resolve(__dirname,'../../dist'),files=await readFiles(root),unhandled=[];
 if(!files.has('/index.html'))throw new Error('Canonical production dist required; this helper never builds.');
 const types={'.html':'text/html','.js':'text/javascript','.css':'text/css','.json':'application/json','.svg':'image/svg+xml','.png':'image/png','.ico':'image/x-icon','.woff2':'font/woff2','.woff':'font/woff'};
 const server=http.createServer((req,res)=>{const pathname=new URL(req.url,'http://static.invalid').pathname;if(pathname.startsWith('/api/')){unhandled.push({method:req.method,path:pathname});res.writeHead(503);res.end('No backend or proxy exists');return;}if(!['GET','HEAD'].includes(req.method)){res.writeHead(405);res.end();return;}const key=pathname==='/'?'/index.html':decodeURIComponent(pathname),body=files.get(key);if(!body){res.writeHead(404);res.end();return;}res.writeHead(200,{'Content-Type':types[path.extname(key)]||'application/octet-stream','Cache-Control':'no-store'});res.end(req.method==='HEAD'?undefined:body);});
 await new Promise((resolve,reject)=>{server.once('error',reject);server.listen(0,'127.0.0.1',resolve);});
 const manifest=Object.fromEntries([...files].sort(([a],[b])=>a.localeCompare(b)).map(([p,b])=>[p,sha(b)]));
 return{origin:`http://127.0.0.1:${server.address().port}`,unhandled,manifest,get listening(){return server.listening;},async close(){await new Promise(resolve=>{server.close(resolve);server.closeAllConnections();});const after=await readFiles(root);if(after.size!==files.size||[...after].some(([p,b])=>manifest[p]!==sha(b)))throw new Error('Canonical dist changed during production entry tests');}};
}
async function setupSupplyProduction(page,server,{role='admin',fixture=actual,revoked=false}={}){
 const state={bootstrap:[],reads:[],writes:[],errors:[],unexpected:[],fixture};page.on('pageerror',e=>state.errors.push(e.message));
 await page.addInitScript(()=>localStorage.setItem('hoim-token','synthetic-supply-production-entry'));
 await page.context().route('**/*',route=>new URL(route.request().url()).origin===server.origin?route.continue():route.abort('blockedbyclient'));
 await page.route('**/api/**',async route=>{
  const req=route.request(),url=new URL(req.url()),p=url.pathname,m=req.method(),query=Object.fromEntries(url.searchParams);let reply;
  if(p==='/api/userInfo'){state.bootstrap.push({method:m,path:p,body:req.postDataJSON()});reply={code:200,data:{username:'合成物资生产入口',permissions:role==='super_admin'?['super_admin','admin']:[role],avatar:''}};}
  else if(m==='GET')state.reads.push({path:p,query});else state.writes.push({method:m,path:p,body:req.postDataJSON()});
  if(p==='/api/events/stream'){await route.fulfill({status:204,body:''});return;}
  if(p==='/api/ai/features')reply=fixture.features;
  else if(p==='/api/pharmaceuticalManagement/getList')reply=fixture.legacy_pharmaceuticals;
  else if(p==='/api/consumable/getList')reply=fixture.legacy_consumables;
  else if(p==='/api/ai/supply-sources/options')reply=query.item_kind==='consumable'?fixture.source_options_consumable:query.item_kind?fixture.source_options:fixture.source_options_all;
  else if(p==='/api/ai/supply-series')reply=query.item_kind==='consumable'?fixture.series_directory_consumable:fixture.series_directory;
  else if(p==='/api/ai/supply-series/'+fixture.live_series.data.series_id)reply=fixture.live_series;
  else if(p==='/api/ai/operational-context')reply=fixture.preview||fixture.h14.preview;
  else if(p==='/api/ai/runs'&&m==='POST')reply=fixture.queued_receipt||fixture.h14.queued;
  else if(p==='/api/ai/runs')reply={code:200,data:[]};
  else if(p==='/api/ai/runs/'+(fixture.statuses?.succeeded.data.run_id||fixture.h14?.detail.data.run_id))reply=fixture.statuses?.succeeded||fixture.h14.detail;
  else if(p==='/api/ai/admin/features')reply=actual.admin_features;
  else if(p==='/api/ai/admin/providers')reply=actual.providers;
  else if(p==='/api/ai/admin/knowledge')reply=actual.admin_knowledge;
  else if(p==='/api/ai/admin/grants')reply=actual.admin_grants;
  else if(p==='/api/ai/admin/audit')reply=actual.admin_audit;
  else if(p==='/api/ai/admin/usage')reply=actual.admin_usage;
  else if(p==='/api/ai/admin/runs')reply=actual.admin_runs;
  else if(p==='/api/ai/admin/runs/'+actual.statuses.succeeded.data.run_id)reply=actual.revoked_audit;
  else if(p==='/api/ai/admin/supply-series')reply=revoked?actual.series_admin_directory_revoked:actual.series_admin_directory;
  else if(p==='/api/ai/admin/supply-series/'+actual.live_series.data.series_id)reply=revoked?actual.admin_series_revoked:actual.admin_series;
  else if(p==='/api/ai/admin/supply-sources')reply=actual.source_admin_directory;
  else if(p.startsWith('/api/ai/admin/supply-sources/'))reply=actual.source_admin_details[p.split('/').at(-1)];
  else if(p.endsWith('/supply-capabilities'))reply=actual.provider_check;
  if(!reply){state.unexpected.push({method:m,path:p,query});await route.fulfill({status:501,json:{code:501,msg:'No synthetic endpoint registered'}});return;}
  await route.fulfill({json:reply});
 });return state;
}
async function chooseSupply(page,label,option,container=page){const input=container.getByRole('combobox',{name:label,exact:true});await input.press('ArrowDown');const id=await input.getAttribute('aria-controls');await page.locator('[id="'+id+'"]').getByRole('option',{name:option,exact:true}).click();}
async function openSupplyBusiness(page,server,state,kind='pharmaceutical'){
 const f=state.fixture,sku=kind==='pharmaceutical'?f.source_options.data.items[0]:f.source_options_consumable.data.items[0];
 await page.goto(server.origin+'/#/pharmacy/'+kind);await page.getByRole('row').filter({hasText:sku.name}).getByRole('button',{name:'核对原量与预测',exact:true}).click();return page.getByRole('dialog',{name:'受审物资原量预测',exact:true});
}
async function chooseSupplySeries(page,drawer,fixture=actual,horizon=7){await chooseSupply(page,'物资预测期限',`完整${horizon}个业务日`,drawer);await drawer.getByRole('row').filter({hasText:fixture.live_series.data.series_id}).getByRole('button',{name:'核对完整物资序列',exact:true}).click();await drawer.getByRole('button',{name:'选择此完整受审物资序列',exact:true}).click();await drawer.getByRole('button',{name:'生成辅助建议',exact:true}).waitFor({state:'visible'});}
module.exports={actual,startSupplyProductionServer,setupSupplyProduction,chooseSupply,openSupplyBusiness,chooseSupplySeries};
