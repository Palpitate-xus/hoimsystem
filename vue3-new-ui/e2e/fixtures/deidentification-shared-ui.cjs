const{expect}=require('@playwright/test');
function actualParts(packet,runId){
 if(runId===packet.success.metadata.run_id)return packet.success.parts_original_utf8;
 const terminal=Object.values(packet.terminal_runs).find(x=>x.metadata.data.run_id===runId);if(!terminal)throw new Error('Unknown actual same-case task');
 return Object.fromEntries(Object.keys(terminal.parts).map(part=>{const path='/api/ai/deidentification/tasks/'+runId+'/parts/'+part,response=packet.additional_actual_http.find(r=>r.method==='GET'&&r.path===path&&r.status===200);if(!response)throw new Error('No original same-task HTTP part');return[part,response.raw_utf8];}));
}
async function installShared(page,packet,{metadata=packet.success.metadata}={}){
 const state={metadata,seen:[],unknown:[],hold:null,denyParts:false};
 await page.route('**/api/**',async route=>{
  const r=route.request(),u=new URL(r.url()),path=u.pathname,method=r.method();state.seen.push({path,search:u.search,method,body:r.postDataJSON()});
  if(state.hold&&state.hold.match({path,method,search:u.search}))await state.hold.promise;
  const reply=data=>route.fulfill({status:200,contentType:'application/json',body:JSON.stringify(data)});
  if(path==='/api/ai/research-cohort/scopes'&&method==='GET')return reply(packet.scope_directory);
  if(path==='/api/ai/research-cohort/scopes/'+packet.scope_request.scope_id&&method==='GET')return reply(packet.super_scope);
  if(path==='/api/ai/deidentification/cases/'+packet.live_source.data.case_id&&method==='GET')return reply(packet.live_source);
  if(path==='/api/ai/deidentification/cases/directory'&&method==='POST')return reply(packet.source_directory);
  if(path==='/api/ai/deidentification/tasks/context'&&method==='POST')return reply(packet.preview);
  if(path==='/api/ai/runs'&&method==='POST')return reply({code:200,msg:'任务已入队',data:packet.success.queued});
  if(path==='/api/ai/runs'&&method==='GET')return reply(packet.ordinary_history);
  if(path==='/api/ai/admin/runs'&&method==='GET')return reply(packet.super_history);
  const runId=path.match(/^\/api\/ai\/(?:admin\/)?runs\/([^/]+)$/)?.[1];
  if(runId&&method==='GET'){
   if(path.includes('/admin/'))return reply(packet.success.trace);
   if(runId!==state.metadata.run_id)throw new Error('Wrong expected actual task');
   return reply({code:200,msg:'success',data:state.metadata});
  }
  if(path===`/api/ai/runs/${state.metadata.run_id}/cancel`&&method==='POST')return reply({code:200,msg:'停止请求已记录'});
  const part=path.match(/^\/api\/ai\/deidentification\/tasks\/([^/]+)\/parts\/(source|scope|task|result)$/);
  if(part&&method==='GET'){
   if(state.denyParts)return route.fulfill({status:403,contentType:'application/json',body:'{"detail":"current purpose withdrawn"}'});
   return route.fulfill({status:200,contentType:'application/json',body:actualParts(packet,part[1])[part[2]]});
  }
  state.unknown.push({path,method});await route.fulfill({status:500,contentType:'application/json',body:'{"detail":"unhandled isolated test request"}'});
 });
 return state;
}
async function openShared(page,harness,scope={},role='admin'){
 await page.goto(harness.origin);await expect.poll(()=>page.evaluate(()=>!!window.__deidentificationSharedProbe)).toBe(true);
 await page.evaluate(({scope,role})=>{const p=window.__deidentificationSharedProbe;p.store.commit('user/permissions',[role]);Object.assign(p.scope,scope);}, {scope,role});
}
function holdRequests(state,match){let release;const promise=new Promise(r=>release=r);state.hold={match,promise};return()=>{state.hold=null;release();};}
module.exports={installShared,openShared,holdRequests,actualParts};
