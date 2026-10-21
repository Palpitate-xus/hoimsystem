const {startSupplyProductionServer}=require('./supply-production-entry.cjs');
const {load}=require('./load-drug-label-business-main.cjs');
async function setup(page,server,{kind='chat',role='pharmacist'}={}){
 const p=load(kind),state={p,calls:[],errors:[],unexpected:[],bootstrap:[]};
 page.on('pageerror',e=>state.errors.push(e.message));
 await page.addInitScript(()=>localStorage.setItem('hoim-token','synthetic-leaflet-production-entry'));
 await page.context().route('**/*',route=>new URL(route.request().url()).origin===server.origin?route.continue():route.abort('blockedbyclient'));
 await page.route('**/api/**',async route=>{
  const req=route.request(),url=new URL(req.url()),path=url.pathname,method=req.method(),query=Object.fromEntries(url.searchParams);let reply;
  if(path==='/api/events/stream'){await route.fulfill({status:200,contentType:'text/event-stream',body:': synthetic idle\n\n'});return;}
  const entry={method,path,query,body:method==='POST'&&req.postData()?req.postDataJSON():null};
  if(path==='/api/userInfo'){state.bootstrap.push(entry);reply={code:200,data:{username:'synthetic-leaflet-production-entry',permissions:role==='super_admin'?['super_admin','admin']:[role],avatar:''}};}
  else state.calls.push(entry);
  if(path==='/api/pharmaceuticalManagement/getList'){
   // Existing business list uses an explicitly synthetic row with the actual
   // same-case Source identity. This is not a captured business HTTP response.
   const id=p.source.data.snapshot.identity;reply={code:200,data:[{id:id.pharmaceutical_id,name:id.name,barcode:id.barcode,status:id.status,stock:0,price:'0',expireddate:null,supplier:null,antibiotic_level:0,remark:'Synthetic business entry only'}]};
  }else if(path==='/api/ai/features')reply={code:200,data:[p.feature]};
  else if(path==='/api/ai/drug-label-sources/options')reply=role==='super_admin'?p.options_super:p.options;
  else if(path==='/api/ai/drug-label-sources/catalog')reply=p.catalog;
  else if(path==='/api/ai/drug-label-sources')reply=p.directory;
  else if(path==='/api/ai/drug-label-sources/'+p.input.drug_label_source_binding_id)reply=role==='super_admin'?p.source_super:p.source;
  else if(path==='/api/ai/drug-label/context'&&method==='POST')reply=p.preview;
  else if(path==='/api/ai/runs'&&method==='POST')reply=p.queued;
  else if(path==='/api/ai/runs/'+p.full.data.run_id)reply=role==='super_admin'?p.super_full:p.full;
  else if(path==='/api/ai/admin/runs/'+p.full.data.run_id)reply=p.trace;
  if(!reply){state.unexpected.push(entry);await route.fulfill({status:501,json:{code:501,msg:'Unregistered synthetic entry endpoint'}});return;}
  await route.fulfill({json:reply});
 });
 await page.goto(server.origin+'/#/pharmacy/pharmaceutical');
 await page.getByRole('row').filter({hasText:p.source.data.snapshot.identity.name}).waitFor();
 return state;
}
async function openAssistant(page,state){
 await page.getByRole('row').filter({hasText:state.p.source.data.snapshot.identity.name}).getByRole('button',{name:'核对说明书字段',exact:true}).click();
 const drawer=page.getByRole('dialog',{name:'本药品说明书逐字字段复核',exact:true});
 await drawer.getByRole('button',{name:'打开说明书来源目录',exact:true}).click();
 const directory=drawer.getByLabel('本次说明书来源目录',{exact:true});
 await directory.getByRole('row').filter({hasText:state.p.input.drug_label_source_binding_id}).getByRole('button',{name:'读取本件完整依据',exact:true}).click();
 await page.getByRole('dialog',{name:'说明书原件与独立签署核对',exact:true}).getByRole('button',{name:'明确选择本件来源',exact:true}).click();
 return drawer;
}
function checked(state){
 if(state.errors.length||state.unexpected.length)throw new Error(JSON.stringify({errors:state.errors,unexpected:state.unexpected}));
 if(state.bootstrap.length!==1||state.bootstrap[0].method!=='POST'||state.bootstrap[0].body.accesstoken!=='synthetic-leaflet-production-entry')throw new Error('Unexpected authentication bootstrap');
}
module.exports={startServer:startSupplyProductionServer,setup,openAssistant,checked};
