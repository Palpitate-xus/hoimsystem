const{expect}=require('@playwright/test'),{loadOperationsPackets}=require('./operations-support-packets.cjs');
const packet=loadOperationsPackets('task-lifecycle-v3'),header=packet.header,BASE='/api/ai/operations-support',data=packet.data;
function unique(test){const rows=packet.rows.filter(test);if(rows.length!==1)throw new Error('Actual V3 row missing/ambiguous '+rows.length);return rows[0];}
const selection={operations_case_id:header.case_id,objective:'explain_observations'},caseMetadata=data(unique(r=>r.stage==='original_flow'&&r.method==='GET'&&r.path===BASE+'/cases/'+header.case_id)),featureResponse=unique(r=>r.stage==='ordinary_queued_current'&&r.path==='/api/ai/features'),feature=data(featureResponse).find(v=>v.key==='operations_support'),descriptor=unique(r=>r.stage==='original_flow'&&r.path===BASE+'/task-descriptor');
const phase=(name)=>{const stage=name==='queued'?'ordinary_queued_current':name==='running'?'ordinary_running_current':'original_flow';const metadata=unique(r=>r.method==='GET'&&r.path===BASE+'/tasks/'+header.success_run_id&&r.status===200&&(name==='running'?r.stage==='original_flow':r.stage===stage)&&data(r).status===name);return{metadata,parts:Object.fromEntries(['task','source','binding','result'].map(k=>[k,unique(r=>r.method==='GET'&&r.path===BASE+'/tasks/'+header.success_run_id+'/parts/'+k&&r.stage===stage&&r.status===200)]))};};
const phases={queued:phase('queued'),running:phase('running'),succeeded:phase('succeeded')};
async function installOperationsAssistantUI(page){
 const state={seen:[],unknown:[],next:0,current:'queued',hold:null,deny:null,feedback:null};
 await page.route('**/api/**',async route=>{
  const r=route.request(),u=new URL(r.url()),path=u.pathname,method=r.method();state.seen.push({path,method,search:u.search,body:r.postDataJSON()});if(state.hold?.match({path,method})){const held=state.hold;await held.promise;}
  if(state.deny)return route.fulfill({status:state.deny,contentType:'application/json',body:JSON.stringify({detail:'current authority or Source lost'})});let row;
  if(method==='GET'&&path==='/api/ai/features')row=featureResponse;
  else if(method==='GET'&&path===BASE+'/task-descriptor')row=descriptor;
  else if(method==='GET'&&[BASE+'/cases/'+header.case_id,BASE+'/cases/'+header.case_id+'/parts/source'].includes(path))row=unique(x=>x.stage==='original_flow'&&x.method===method&&x.path===path);
  else if(method==='GET'&&path===BASE+'/tasks/'+header.success_run_id){state.current=['queued','running','succeeded'][Math.min(state.next++,2)];row=phases[state.current].metadata;}
  else if(method==='GET'&&path.startsWith(BASE+'/tasks/'+header.success_run_id+'/parts/'))row=phases[state.current].parts[path.split('/').at(-1)];
  else if(method==='GET'&&path===BASE+'/tasks'){row=unique(x=>x.stage==='final_directory_admin'&&x.method==='GET'&&x.path.startsWith(BASE+'/tasks?'));}
  else if(method==='POST'&&path==='/api/ai/runs'){row=unique(x=>x.stage==='original_flow'&&x.method==='POST'&&x.path===path&&x.status===200&&data(x).preview===false);expect(r.postDataJSON()).toEqual(JSON.parse(row.request_body));state.next=0;}
  else if(method==='POST'&&path==='/api/ai/runs/'+header.success_run_id+'/feedback'){row=unique(x=>x.stage==='feedback_current');state.feedback=r.postDataJSON();expect(state.feedback).toEqual(JSON.parse(row.request_body));}
  if(!row){state.unknown.push({path,method,search:u.search});return route.fulfill({status:599,body:'Unknown actual same-case assistant replay API'});}
  await route.fulfill({status:row.status,contentType:'application/json',body:row.body,headers:row.parts_wire?{'X-AI-Parts-Wire':row.parts_wire}:{}});
 });return state;
}
async function openOperationsAssistant(page,harness,{role='admin',bound=true}={}){
 await page.goto(harness.origin);await expect.poll(()=>page.evaluate(()=>!!window.__operationsProbe)).toBe(true);await page.evaluate(({feature,role,initialInput})=>{const p=window.__operationsProbe;p.store.commit('user/permissions',[role]);p.scope.feature=feature;p.scope.initialInput=initialInput;},{feature,role,initialInput:bound?{operations_case_id:header.case_id}:{}});
}
async function selectOperationsInput(page){await page.getByRole('button',{name:'核对入口指定材料集',exact:true}).click();await expect(page.getByText('已核对当前完整材料集',{exact:false})).toBeVisible();}
async function selectObjective(page){await page.getByRole('combobox',{name:'本次固定目标',exact:true}).press('ArrowDown');await page.getByRole('option',{name:'整理材料内的可引用观察与待核查故障假设',exact:true}).click();}
module.exports={installOperationsAssistantUI,openOperationsAssistant,selectOperationsInput,selectObjective,actualOperationsAssistant:{packet,header,selection,feature,caseMetadata,phases}};
