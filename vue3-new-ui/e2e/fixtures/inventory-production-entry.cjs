const fs=require('node:fs/promises'),path=require('node:path'),http=require('node:http'),crypto=require('node:crypto');
const actual=require('./inventory-production-packets.cjs').actual();
const sha=v=>crypto.createHash('sha256').update(v).digest('hex');
async function readFiles(root,dir=root){const out=new Map();for(const entry of await fs.readdir(dir,{withFileTypes:true})){const p=path.join(dir,entry.name);if(entry.isDirectory())for(const[k,v]of await readFiles(root,p))out.set(k,v);else if(entry.isFile())out.set('/'+path.relative(root,p).split(path.sep).join('/'),await fs.readFile(p));}return out;}
async function startInventoryProductionServer(){
 const root=path.resolve(__dirname,'../../dist'),files=await readFiles(root),unhandled=[];
 if(!files.has('/index.html'))throw new Error('Canonical production dist required; this helper never builds.');
 const types={'.html':'text/html','.js':'text/javascript','.css':'text/css','.json':'application/json','.svg':'image/svg+xml','.png':'image/png','.ico':'image/x-icon','.woff2':'font/woff2','.woff':'font/woff'};
 const server=http.createServer((req,res)=>{const pathname=new URL(req.url,'http://static.invalid').pathname;if(pathname.startsWith('/api/')){unhandled.push({method:req.method,path:pathname});res.writeHead(503);res.end('No backend or proxy exists');return;}if(!['GET','HEAD'].includes(req.method)){res.writeHead(405);res.end();return;}const key=pathname==='/'?'/index.html':decodeURIComponent(pathname),body=files.get(key);if(!body){res.writeHead(404);res.end();return;}res.writeHead(200,{'Content-Type':types[path.extname(key)]||'application/octet-stream','Cache-Control':'no-store'});res.end(req.method==='HEAD'?undefined:body);});
 await new Promise((resolve,reject)=>{server.once('error',reject);server.listen(0,'127.0.0.1',resolve);});
 const manifest=Object.fromEntries([...files].sort(([a],[b])=>a.localeCompare(b)).map(([p,b])=>[p,sha(b)]));
 return{origin:`http://127.0.0.1:${server.address().port}`,unhandled,manifest,get listening(){return server.listening;},async close(){await new Promise(resolve=>{server.close(resolve);server.closeAllConnections();});const after=await readFiles(root);if(after.size!==files.size||[...after].some(([p,b])=>manifest[p]!==sha(b)))throw new Error('Canonical dist changed during production entry tests');}};
}
async function setupInventoryProduction(page,server,{role='pharmacist',revoked=false,disabled=false}={}){
 const state={bootstrap:[],reads:[],writes:[],errors:[],unexpected:[],cssErrors:[],external:[],getStatus:'succeeded',denyCurrent:false},f=actual;page.on('pageerror',e=>state.errors.push(e.message));page.on('response',r=>{if(new URL(r.url()).origin===server.origin&&new URL(r.url()).pathname.endsWith('.css')&&r.status()>=400)state.cssErrors.push({url:r.url(),status:r.status()});});page.on('requestfailed',r=>{if(new URL(r.url()).pathname.endsWith('.css'))state.cssErrors.push({url:r.url(),error:r.failure()});});await page.addInitScript(()=>localStorage.setItem('hoim-token','synthetic-inventory-production-entry'));await page.context().route('**/*',route=>{if(new URL(route.request().url()).origin===server.origin)return route.continue();state.external.push({method:route.request().method(),url:route.request().url()});return route.abort('blockedbyclient');});await page.route('**/api/**',async route=>{
  const req=route.request(),u=new URL(req.url()),p=u.pathname,m=req.method(),query=Object.fromEntries(u.searchParams);let reply;
  if(p==='/api/userInfo'){state.bootstrap.push({method:m,path:p,body:req.postDataJSON()});reply={code:200,data:{username:'合成库存生产入口',permissions:role==='super_admin'?['super_admin','admin']:[role],avatar:''}};}else if(m==='GET')state.reads.push({path:p,query});else state.writes.push({method:m,path:p,body:req.postDataJSON()});
  if(p==='/api/events/stream'&&m==='GET')return route.fulfill({status:204,body:''});
  if(p==='/api/ai/features'&&m==='GET')reply=disabled?f.features_disabled:role==='nurse'?f.features_nurse:role==='super_admin'?f.features_super:f.features;
  else if(p==='/api/pharmaceuticalManagement/getList'&&m==='GET')reply=f.legacy_pharmaceuticals;
  else if(p==='/api/consumable/getList'&&m==='GET')reply=f.legacy_consumables;
  else if(p==='/api/ai/inventory-native-sources/options'&&m==='GET')reply=query.item_kind==='consumable'?(role==='super_admin'?f.source_options_consumable_super:f.source_options_consumable):query.item_id?(role==='super_admin'?f.source_options_selected_super:f.source_options_selected):query.item_kind?f.source_options:role==='super_admin'?f.source_options_all_super:f.source_options_all;
  else if(p==='/api/ai/inventory-scenarios'&&m==='GET')reply=query.item_kind==='consumable'?f.scenario_directory_consumable:f.scenario_directory;
  else if(p==='/api/ai/inventory-scenarios/'+f.live_scenario.data.scenario_id&&m==='GET'){if(state.denyCurrent)return route.fulfill({status:409,json:{detail:'合成完整来源集合已经变化，旧场景不能继续执行'}});reply=f.live_scenario;}
  else if(p==='/api/ai/operational-context'&&m==='POST')reply=f.preview;
  else if(p==='/api/ai/runs'&&m==='POST')reply=f.queued_receipt;
  else if(p==='/api/ai/runs'&&m==='GET')reply=f.history;
  else if(m==='GET'&&p.startsWith('/api/ai/runs/')){const row=Object.values(f.full_by_status).find(v=>p==='/api/ai/runs/'+v.data.run_id);reply=row&&row.data.run_id===f.full_by_status.succeeded.data.run_id?f.full_by_status[state.getStatus]:row;}
  else if(p==='/api/ai/admin/features'&&m==='GET')reply=f.admin_features;
  else if(p==='/api/ai/admin/providers'&&m==='GET')reply=f.providers;
  else if(p==='/api/ai/admin/knowledge'&&m==='GET')reply=f.admin_knowledge;
  else if(p==='/api/ai/admin/grants'&&m==='GET')reply=f.admin_grants;
  else if(p==='/api/ai/admin/audit'&&m==='GET')reply=f.admin_audit;
  else if(p==='/api/ai/admin/usage'&&m==='GET')reply=f.admin_usage;
  else if(p==='/api/ai/admin/runs'&&m==='GET')reply=f.admin_runs;
  else if(p==='/api/ai/admin/runs/'+f.full_by_status.succeeded.data.run_id&&m==='GET')reply=f.revoked_audit;
  else if(p==='/api/ai/admin/inventory-native-sources'&&m==='GET')reply=f.source_admin_directory;
  else if(p.startsWith('/api/ai/admin/inventory-native-sources/')&&m==='GET')reply=f.source_admin_details[p.split('/').at(-1)];
  else if(p==='/api/ai/admin/inventory-scenarios'&&m==='GET')reply=revoked?f.scenario_admin_directory_revoked:f.scenario_admin_directory;
  else if(p==='/api/ai/admin/inventory-scenarios/'+f.live_scenario.data.scenario_id&&m==='GET')reply=revoked?f.scenario_admin_revoked:f.scenario_admin_detail;
  else if(p===`/api/ai/admin/providers/${f.provider_check.data.provider_id}/inventory-capabilities`&&m==='POST')reply=f.provider_check;
  if(!reply){state.unexpected.push({method:m,path:p,query});return route.fulfill({status:501,json:{code:501,msg:'No synthetic endpoint registered'}});}return route.fulfill({json:reply});
 });return state;
}
async function openInventoryBusiness(page,server,kind='pharmaceutical'){const sku=kind==='pharmaceutical'?actual.source_options_selected.data.items[0]:actual.source_options_consumable.data.items[0];await page.goto(server.origin+'/#/pharmacy/'+kind);await page.getByRole('row').filter({hasText:sku.name}).getByRole('button',{name:'核对库存候选',exact:true}).click();return page.getByRole('dialog',{name:'受审完整库存候选比较',exact:true});}
async function chooseInventoryScenario(page,dialog){await dialog.getByRole('row').filter({hasText:actual.live_scenario.data.scenario_id}).getByRole('button',{name:'核对完整库存场景',exact:true}).click();await dialog.getByRole('button',{name:'选择此受审完整库存场景',exact:true}).click();await expectEnabled(dialog.getByRole('button',{name:'生成辅助建议',exact:true}));}
async function expectEnabled(button){const{expect}=require('@playwright/test');await expect(button).toBeEnabled();}
async function styles(page,button){const{expect}=require('@playwright/test');await expect(button).toBeVisible();const computed=await button.evaluate(e=>({display:getComputedStyle(e).display,border:getComputedStyle(e).borderTopStyle}));expect(['inline-flex','flex']).toContain(computed.display);expect(computed.border).toBe('solid');expect(await page.evaluate(()=>Array.from(document.styleSheets).some(s=>s.href&&new URL(s.href).origin===location.origin&&new URL(s.href).pathname.endsWith('.css')))).toBe(true);}
module.exports={actual,startInventoryProductionServer,setupInventoryProduction,openInventoryBusiness,chooseInventoryScenario,styles};
