const sources=require('./surgery-synthetic/sources.json'),providers=require('./surgery-synthetic/providers.json');
async function openSurgery(page,harness,config={}){
 const state={writes:[],errors:[],releases:{},completed:[],role:'super_admin',response:providers.cases.compatible.response,...config};
 page.on('pageerror',error=>state.errors.push(error.message));
 await page.context().route('**/*',route=>new URL(route.request().url()).origin===harness.origin?route.continue():route.abort('blockedbyclient'));
 await page.route('**/api/**',async route=>{const req=route.request(),path=new URL(req.url()).pathname;state.writes.push({method:req.method(),path,body:req.postDataJSON()});const held=state.hold?.(req.method(),path);if(held)await new Promise(resolve=>state.releases[held]=resolve);await route.fulfill({json:state.response});if(held)state.completed.push(held);});
 await page.goto(harness.origin);await page.waitForFunction(()=>!!window.__surgeryProbe);
 if(state.mode==='provider')await page.evaluate(({role,response,targetReceipt})=>{const p=window.__surgeryProbe,d=(targetReceipt||response).data;p.store.commit('user/permissions',[role]);p.scope.providers=[{provider_id:d.provider_id,revision:d.provider_revision,model:d.configured_model,kind:'specialist',supported_features:['surgery_scheduling']}];p.scope.target={...p.scope.providers[0],name:'合成手术只读能力服务',session:p.store.state.user.accessToken};p.scope.mode='provider';},{role:state.role,response:state.response,targetReceipt:state.targetReceipt});
 return state;
}
module.exports={sources,providers,openSurgery};
