const governance=require('./surgery-synthetic/governance.json');
const sources=require('./surgery-synthetic/sources-eight-kind.json'),providers=require('./surgery-synthetic/providers-eight-kind.json');
async function openSurgery(page,harness,config={}){
 const state={writes:[],errors:[],releases:{},completed:[],role:'super_admin',response:providers.cases.compatible.response,...config};
 page.on('pageerror',error=>state.errors.push(error.message));
 await page.context().route('**/*',route=>new URL(route.request().url()).origin===harness.origin?route.continue():route.abort('blockedbyclient'));
 await page.route('**/api/**',async route=>{const req=route.request(),path=new URL(req.url()).pathname;state.writes.push({method:req.method(),path,body:req.postDataJSON()});const held=state.hold?.(req.method(),path);if(held)await new Promise(resolve=>state.releases[held]=resolve);const reply=state.respond?await state.respond(req,path,state):{json:state.response};await route.fulfill(reply?.json===undefined?{json:reply}:reply);if(held)state.completed.push(held);});
 await page.goto(harness.origin);await page.waitForFunction(()=>!!window.__surgeryProbe);
 if(state.mode==='provider')await page.evaluate(({role,response,targetReceipt})=>{const p=window.__surgeryProbe,d=(targetReceipt||response).data;p.store.commit('user/permissions',[role]);p.scope.providers=[{provider_id:d.provider_id,revision:d.provider_revision,model:d.configured_model,kind:'specialist',supported_features:['surgery_scheduling']}];p.scope.target={...p.scope.providers[0],name:'合成手术只读能力服务',session:p.store.state.user.accessToken};p.scope.mode='provider';},{role:state.role,response:state.response,targetReceipt:state.targetReceipt});
 if(['sources','registry','editor'].includes(state.mode))await page.evaluate(({role,mode,poolId,applicationId,clinicalSigners,protectedBinding,sourceKind,resourceId,legacyScheduleId})=>{const p=window.__surgeryProbe;p.store.commit('user/permissions',[role]);Object.assign(p.scope,{mode,poolId,applicationId,clinicalSigners,protectedBinding,sourceKind,resourceId,legacyScheduleId});},{role:state.role,mode:state.mode,poolId:state.poolId??null,applicationId:state.applicationId??null,clinicalSigners:state.clinicalSigners??null,protectedBinding:state.protectedBinding??null,sourceKind:state.sourceKind??'resource_availability_busy',resourceId:state.resourceId??null,legacyScheduleId:state.legacyScheduleId??null});
 return state;
}
module.exports={sources,providers,governance,openSurgery};
