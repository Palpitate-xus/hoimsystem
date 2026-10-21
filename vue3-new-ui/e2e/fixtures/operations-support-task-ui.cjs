const{expect}=require('@playwright/test'),{loadOperationsPackets}=require('./operations-support-packets.cjs');
const packet=loadOperationsPackets('main-custom-prompt'),value=i=>packet.data(packet.rows[i]),metadata=value(29),caseMetadata=value(10),parts=Object.fromEntries(['task','source','binding','result'].map((k,i)=>[k,packet.rows[25+i]]));
const actual={packet,metadata,caseMetadata,parts,feature:value(0).find(v=>v.key==='operations_support'),descriptor:value(1),selection:{operations_case_id:metadata.binding.operations_case_id,objective:metadata.binding.objective}};
async function installOperationsTaskUI(page){
 const state={seen:[],unknown:[],hold:null,deny:null,tamper:null};
 await page.route('**/api/**',async route=>{
  const r=route.request(),path=new URL(r.url()).pathname,method=r.method();state.seen.push({path,method,body:r.postDataJSON()});
  if(state.hold?.match({path,method})){const gate=state.hold;await gate.promise;}
  if(state.deny)return route.fulfill({status:state.deny,contentType:'application/json',body:JSON.stringify({detail:'current source or authority lost'})});
  let row;if(method==='GET'){
   if(path==='/api/ai/operations-support/tasks/'+metadata.run_id)row=packet.rows[29];
   else if(path==='/api/ai/operations-support/tasks/'+metadata.run_id+'/trace')row=packet.rows[30];
   else if(path==='/api/ai/operations-support/cases/'+caseMetadata.case_id)row=packet.rows[10];
   else for(const[k,v]of Object.entries(parts))if(path==='/api/ai/operations-support/tasks/'+metadata.run_id+'/parts/'+k)row=v;
  }
  if(!row){state.unknown.push({path,method});return route.fulfill({status:599,body:'Unknown isolated task API'});}
  let body=row.body;if(state.tamper){const changed=state.tamper({path,method,value:JSON.parse(body)});if(changed!==undefined)body=JSON.stringify(changed);}
  await route.fulfill({status:row.status,contentType:'application/json',body,headers:row.parts_wire?{'X-AI-Parts-Wire':row.parts_wire}:{}});
 });return state;
}
async function openOperationsTask(page,harness,{role='admin',auditOnly=false}={}){
 await page.goto(harness.origin);await expect.poll(()=>page.evaluate(()=>!!window.__operationsProbe)).toBe(true);
 await page.evaluate(({role,auditOnly,runId,selection})=>{const p=window.__operationsProbe;p.store.commit('user/permissions',[role]);p.scope.auditOnly=auditOnly;p.scope.references=selection;p.scope.runId=runId;},{role,auditOnly,runId:metadata.run_id,selection:actual.selection});
}
function holdOperationsTask(state,match){let release;state.hold={match,promise:new Promise(r=>release=r)};return()=>{state.hold=null;release();};}
module.exports={actualOperationsTask:actual,installOperationsTaskUI,openOperationsTask,holdOperationsTask};
