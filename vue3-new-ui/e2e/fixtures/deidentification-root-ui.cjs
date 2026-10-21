const{expect}=require('@playwright/test'),{installShared}=require('./deidentification-shared-ui.cjs');
async function openDeidentificationRoot(page,harness,packet,{mode='parent',roles=['admin'],initial={},metadata=null,withdrawn=false,fullRegistry=false}={}){
 const state=await installShared(page,packet,{...(metadata?{metadata}:{})});state.errors=[];page.on('pageerror',e=>state.errors.push(e.message));
 await page.context().route('**/*',r=>new URL(r.request().url()).origin===harness.origin?r.continue():r.abort());
 // These six read-only management bootstrap replies are explicitly synthetic UI
 // setup. Source/Task bodies and part bytes below remain the immutable real case.
 await page.route('**/api/ai/admin/{features,providers,knowledge,grants,audit,usage}',route=>route.fulfill({status:200,contentType:'application/json',body:'{"code":200,"msg":"isolated platform bootstrap","data":[]}'}));
 await page.route('**/api/ai/features',route=>route.fulfill({status:200,contentType:'application/json',body:fullRegistry?packet.additional_actual_http.find(r=>r.path==='/api/ai/features'&&r.method==='GET'&&r.status===200).raw_utf8:JSON.stringify({code:200,msg:'actual same-case feature DTO',data:[packet.feature]})}));
 if(withdrawn)await page.route('**/api/ai/admin/runs?**',route=>route.fulfill({status:200,contentType:'application/json',body:JSON.stringify(packet.withdrawn_history)}));
 await page.addInitScript(v=>window.__deidentificationRootInitial=v,{mode,roles,features:[packet.feature],initialInput:{deidentification_case_id:packet.live_source.data.case_id},...initial});
 await page.goto(harness.origin);await expect.poll(()=>page.evaluate(()=>!!window.__deidentificationRootProbe)).toBe(true);return state;
}
module.exports={openDeidentificationRoot};
