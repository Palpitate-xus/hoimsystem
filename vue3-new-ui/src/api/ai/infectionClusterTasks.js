import request from'@/utils/request';
import{decodeInfectionResponse,infectionHttp,infectionReferencesValid}from'./infectionClusterSources';
import{bytes,clock,digest,fixed,hash,keys,modelValid,same,unique,uuid,verifyStatisticsInput}from'./infectionClusterProofs';
import{verifyInfectionAnalysis}from'./infectionClusterStatistics';
const id=v=>{if(!uuid(v))throw Error('须明确当前本地任务UUID');return v;};
export const infectionTaskRequestValid=v=>modelValid('TaskCreate',v)&&infectionReferencesValid({infection_cluster_scenario_id:v.infection_cluster_scenario_id});
export const previewInfectionTask=v=>{if(!infectionTaskRequestValid(v))throw Error('须完整明确有限统计场景与预览模式');return infectionHttp('/context',{method:'post',data:v});};
export const createInfectionTask=v=>{if(!infectionTaskRequestValid(v))throw Error('须完整明确有限统计场景与预览模式');return infectionHttp('/tasks',{method:'post',data:v});};
export const getInfectionTask=v=>infectionHttp('/tasks/'+id(v));
export const getInfectionTaskTrace=async v=>decodeInfectionResponse(await request({url:'/ai/admin/runs/'+id(v),method:'get',responseType:'arraybuffer',retry:0}));
export const infectionRunHasMarkers=v=>!!v&&(v.feature_key==='infection_cluster'||String(v.schema_version??'').startsWith('infection_local_')||v.result?.schema_version==='infection_statistics_result_pointer_v1'||Object.hasOwn(v,'infection_cluster_scenario_id'));
export const getInfectionTaskPart=(v,part)=>{if(!['task','source','result'].includes(part))throw Error('只接受明确完整拆分件');return infectionHttp('/tasks/'+id(v)+'/parts/'+part);};
export const cancelInfectionTask=v=>infectionHttp('/tasks/'+id(v)+'/cancel',{method:'post',data:{}});
export const getInfectionTasks=({scenarioId=null,page=1,size=20}={})=>{if(!Number.isSafeInteger(page)||page<1||!Number.isSafeInteger(size)||size<1||size>100)throw Error('须明确完整分页');return infectionHttp('/tasks',{params:{page,size,...(scenarioId===null?{}:{scenario_id:id(scenarioId)})}});};
export function verifyInfectionAcknowledgement(v){return modelValid('TaskAcknowledgement',v);}
export function verifyInfectionCancellation(v,runId){return keys(v,['run_id','feature_key','status','result_available'])&&uuid(v.run_id)&&v.run_id===runId&&v.feature_key==='infection_cluster'&&v.status==='cancelled'&&v.result_available===false;}
export function verifyInfectionTaskMetadata(v,{runId=null,scenarioId=null,current=()=>true}={}){try{
 if(!current()||!modelValid('TaskMetadata',v)||runId!==null&&v.run_id!==runId||scenarioId!==null&&v.scenario_id!==scenarioId||!clock(v.created_at)||!clock(v.run_created_at,'second')||v.run_finish_at!==null&&!clock(v.run_finish_at,'second'))return false;
 const success=v.status==='succeeded',recorded=v.usage!==null;
 if(v.result_available!==success||(v.result_hash!==null)!==success||(v.result_bytes!==null)!==success||(v.receipt_event_id!==null)!==recorded||v.usage_receipt_status!==(recorded?'recorded':'pending')||['succeeded','failed'].includes(v.status)&&!recorded)return false;
 if(recorded){const u=v.usage;if(u.run_id!==v.run_id||u.terminal_status!==v.status||u.result_hash!==v.result_hash||u.calculation_completed===true&&u.calculation_attempted!==true||u.calculation_attempted===false&&(u.calculation_completed!==false||u.calculation_ms!==null)||success&&u.calculation_completed!==true)return false;}
 return current();
}catch{return false;}}
// Global Super directory adds only these three bodyless technical columns.
// Reject every other extension; this does not widen the dedicated Task DTO.
export function infectionGlobalTaskMetadata(v){try{const{requested_by,provider_id,feedback_count,...metadata}=v;if(!Object.hasOwn(v,'requested_by')||!Object.hasOwn(v,'provider_id')||!Object.hasOwn(v,'feedback_count')||!Number.isSafeInteger(requested_by)||requested_by<1||requested_by>2147483647||provider_id!==null||!Number.isSafeInteger(feedback_count)||feedback_count<0||feedback_count>2147483647||!verifyInfectionTaskMetadata(metadata))return null;return metadata;}catch{return null;}}
export function verifyInfectionSplitTrace(v,{runId=null,metadata=null,current=()=>true}={}){try{return current()&&keys(v,['schema_version','run','parts','clinical_body_included','current_patient_purpose_required_even_for_super'])&&v.schema_version==='infection_local_split_trace_v1'&&v.clinical_body_included===false&&v.current_patient_purpose_required_even_for_super===true&&verifyInfectionTaskMetadata(v.run,{runId,current})&&(metadata===null||same(v.run,metadata))&&keys(v.parts,['task','source','result'])&&['task','source','result'].every(k=>v.parts[k]==='/api/ai/infection-cluster/tasks/'+v.run.run_id+'/parts/'+k);}catch{return false;}}
export function infectionTaskDirectoryValid(v,{page=1,size=20,scenarioId=null}={}){try{return modelValid('TaskDirectory',v)&&v.page===page&&v.size===size&&v.items.length===Math.min(size,Math.max(0,v.total-(page-1)*size))&&unique(v.items.map(r=>r.run_id))&&v.items.every(r=>verifyInfectionTaskMetadata(r,{scenarioId}));}catch{return false;}}
async function verifyPart(v,name,rid,current){if(!current()||!modelValid('TaskPart',v)||v.part!==name||v.run_id!==rid||v.value_hash!==await digest(v.value)||!current()||v.value_bytes!==bytes(v.value))return false;return current();}
export async function verifyInfectionTaskParts(metadata,parts,{current=()=>true}={}){try{
 if(!verifyInfectionTaskMetadata(metadata,{current})||!keys(parts,['task','source','result']))return false;
 for(const name of ['task','source','result'])if(!await verifyPart(parts[name],name,metadata.run_id,current))return false;
 const f=parts.task.value,s=parts.source.value;
 if(!modelValid('FrozenTask',f)||!clock(f.created_at)||f.requester_epoch.token_invalid_before!==null&&!clock(f.requester_epoch.token_invalid_before,'naive')||f.recipe_hash!==fixed.recipe_hash||f.implementation_hash!==await digest(fixed.implementation)||!current()||f.system_prompt!==''||f.task_prompt!==fixed.local_task_text||f.prompt_hash!==fixed.local_prompt_hash||f.prompt_hash!==await digest(['',f.task_prompt])||!current()||!await verifyStatisticsInput(s,{current})||!current())return false;
 if(f.run_id!==metadata.run_id||f.scenario_id!==metadata.scenario_id||s.scenario.scenario_id!==f.scenario_id||f.source_binding.snapshot_id!==metadata.snapshot_id||f.profile_id!==metadata.profile_id||f.created_at!==metadata.created_at||f.preview!==metadata.preview||f.source_hash!==metadata.source_hash||parts.source.value_hash!==metadata.source_hash||parts.source.value_bytes!==metadata.source_bytes||!same(f.source_binding,s.scenario.source_binding)||s.recipe_hash!==f.recipe_hash)return false;
 if(metadata.status==='succeeded')return parts.result.value_hash===metadata.result_hash&&parts.result.value_bytes===metadata.result_bytes&&await verifyInfectionAnalysis(s,parts.result.value,{current})&&current();
 return parts.result.value===null&&current();
}catch{return false;}}
export async function verifyInfectionContext(v,{scenarioId=null,current=()=>true}={}){try{
 return current()&&keys(v,['schema_version','source','scenario_content_hash','scenario_governance_hash','profile_id','profile_content_hash','profile_governance_hash','configuration_hash','source_hash','engine','external_model_transfer','automatic_actions'])&&v.schema_version==='infection_local_context_v1'&&v.engine==='prediction'&&v.external_model_transfer===false&&v.automatic_actions===false&&['scenario_content_hash','scenario_governance_hash','profile_content_hash','profile_governance_hash','configuration_hash','source_hash'].every(k=>hash(v[k]))&&uuid(v.profile_id)&&(scenarioId===null||v.source.scenario.scenario_id===scenarioId)&&await verifyStatisticsInput(v.source,{current})&&current()&&v.source_hash===await digest(v.source)&&current();
}catch{return false;}}
export async function readInfectionTaskParts(runId,{current=()=>true}={}){const first=(await getInfectionTask(runId)).data;if(!verifyInfectionTaskMetadata(first,{runId,current}))throw Error('完整当前任务元数据无法核对');const parts={};for(const name of ['task','source','result']){if(!current())throw Error('读取会话已失效');parts[name]=(await getInfectionTaskPart(runId,name)).data;}const last=(await getInfectionTask(runId)).data;if(!current()||!same(first,last)||!await verifyInfectionTaskParts(last,parts,{current})||!current())throw Error('拆分件、当前任务或完整统计无法核对；须显式重读');return{metadata:last,parts};}
