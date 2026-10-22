const {expect}=require('@playwright/test');
const {startSupplyProductionServer}=require('./supply-production-entry.cjs');
const {openRcaTask}=require('./rca-evidence-task-ui.cjs');

// Serve only the already-built canonical dist. Actual same-case Main responses
// are replayed at the browser boundary; this does not start a backend or model.
async function openRcaProduction(page,server,{view='business'}={}){
 const state={bootstrap:[],unexpected:[],external:[],errors:[],cssErrors:[]};
 page.on('pageerror',error=>state.errors.push(error.message));
 page.on('response',response=>{if(new URL(response.url()).pathname.endsWith('.css')&&response.status()>=400)state.cssErrors.push(response.url());});
 await page.addInitScript(()=>localStorage.setItem('hoim-token','synthetic-rca-production-session'));
 await page.context().route('**/*',route=>{
  if(new URL(route.request().url()).origin===server.origin)return route.continue();
  state.external.push(route.request().url());return route.abort('blockedbyclient');
 });
 const path=view==='business'?'/system/adverseEvent':'/ai/manage';
 const api=await openRcaTask(page,{origin:server.origin+'/#'+path},{shared:true,waitForView:false,fallback:async({route,request,path,packet})=>{
  let reply=null;
  if(path==='/api/userInfo'&&request.method()==='POST'){
   state.bootstrap.push({method:request.method(),body:request.postDataJSON()});
   reply={code:200,data:{username:'synthetic-rca-production-author',permissions:['super_admin','admin'],avatar:''}};
  }
  if(path==='/api/events/stream')return route.fulfill({status:204,body:''});
  if(request.method()==='GET'){
   if(path==='/api/adverseEvent/getList')reply=packet.business_directory;
   if(path==='/api/ai/admin/rca-evidence/options')reply=packet.source_options;
   if(path===`/api/ai/admin/rca-evidence/events/${packet.current_case.data.immutable.event_id}/directory/cases`)reply=packet.case_directory;
   if(path==='/api/ai/admin/features')reply={code:200,msg:'success',data:packet.features.data};
   // These empty management tables are explicitly synthetic bootstrap data;
   // no Source proof or Task receipt is fabricated from them.
   if(['/api/ai/admin/providers','/api/ai/admin/knowledge','/api/ai/admin/grants','/api/ai/admin/audit','/api/ai/admin/usage'].includes(path))reply={code:200,msg:'success',data:[]};
  }
  if(!reply){state.unexpected.push({method:request.method(),path});return route.fulfill({status:501,json:{detail:'No explicit RCA production replay route'}});}
  return route.fulfill({json:reply});
 }});
 return {...api,...state};
}
function checkedRcaProduction(state){
 expect(state.errors).toEqual([]);expect(state.cssErrors).toEqual([]);expect(state.unexpected).toEqual([]);expect(state.external).toEqual([]);
 expect(state.bootstrap).toEqual([{method:'POST',body:{accesstoken:'synthetic-rca-production-session'}}]);
}
module.exports={startRcaProductionServer:startSupplyProductionServer,openRcaProduction,checkedRcaProduction};
