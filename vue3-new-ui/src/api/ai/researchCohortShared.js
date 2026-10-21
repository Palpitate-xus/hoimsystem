import{supportCanonical as canonical,supportId as uuid}from'../inpatientSupport';
import{documentClock}from'./documentEvidence';
import{parseOriginalJson}from'./researchCohortOriginalJson';
import{getResearchTask,getResearchTaskPart,verifyResearchTaskMetadata,verifyResearchTaskParts}from'./researchCohortTasks';
const object=v=>v!==null&&typeof v==='object'&&!Array.isArray(v),same=(a,b)=>canonical(a)===canonical(b),keys=(v,n)=>object(v)&&same(Object.keys(v).sort(),[...n].sort()),own=(v,k)=>object(v)&&Object.hasOwn(v,k),positive=v=>Number.isSafeInteger(v)&&v>0;
export function researchRunHasMarkers(value){
 if(!object(value))return false;
 const tagged=v=>object(v)&&(v.feature_key==='research_cohort'||typeof v.schema_version==='string'&&v.schema_version.startsWith('research_cohort_')||['research_cohort_case_id','research_cohort_artifact'].some(k=>own(v,k))||typeof v.source_id==='string'&&v.source_id.startsWith('research_cohort:'));
 if(tagged(value)||tagged(value.run)||tagged(value.result)||tagged(value.input))return true;
 const f=value.frozen_request?.payload??value.frozen_request;if(tagged(f?.input)||tagged(f?.context)||own(f?.context?.selected_sources,'research_cohort_case_id'))return true;
 if(Array.isArray(value.evidence)&&value.evidence.some(v=>v?.kind==='recorded_research_cohort'||tagged(v)))return true;
 for(const raw of [value.input_json,value.context_metadata_json,value.raw_frozen_json?.input_json,value.raw_frozen_json?.context_metadata_json])if(typeof raw==='string'){
  try{if(tagged(parseOriginalJson(raw,65535)))return true;}catch{if(/"(?:research_cohort_case_id|research_cohort_artifact)"\s*:|research_cohort_task_(?:ref|metadata)_v1/.test(raw))return true;}
 }
 return false;
}
export function researchIncompleteMetadataValid(v){return keys(v,['schema_version','run_id','feature_key','status','create_time','split_artifacts','incomplete_native_artifact','clinical_parts_available','binding','error_code','error_message'])&&v.schema_version==='research_cohort_incomplete_task_metadata_v1'&&uuid(v.run_id)&&typeof v.feature_key==='string'&&['queued','running','succeeded','failed','cancelled'].includes(v.status)&&documentClock(v.create_time)&&v.split_artifacts===true&&v.incomplete_native_artifact===true&&v.clinical_parts_available===false&&v.binding===null&&v.error_code==='NATIVE_ARTIFACT_REQUIRED'&&typeof v.error_message==='string';}
export async function verifyResearchSharedDirectoryRow(row,{caseId=null,current=()=>true}={}){try{if(!object(row)||!['requested_by','provider_id','feedback_count'].every(k=>own(row,k))||!positive(row.requested_by)||(row.provider_id!==null&&!positive(row.provider_id))||!Number.isSafeInteger(row.feedback_count)||row.feedback_count<0)return false;const v=Object.fromEntries(Object.entries(row).filter(([k])=>!['requested_by','provider_id','feedback_count'].includes(k)));return current()&&(researchIncompleteMetadataValid(v)?caseId===null:await verifyResearchTaskMetadata(v,{caseId,current}));}catch{return false;}}
export async function verifyResearchSplitTrace(value,{runId=null,caseId=null,current=()=>true}={}){try{if(!current()||!keys(value,['schema_version','run','parts_require_independent_current_reads','parts'])||value.schema_version!=='research_cohort_split_trace_v1'||value.parts_require_independent_current_reads!==true||!await verifyResearchTaskMetadata(value.run,{runId,caseId,current})||!keys(value.parts,['task','source','scope','result']))return false;return['task','source','scope','result'].every(k=>value.parts[k]===`/api/ai/research-cohort/tasks/${value.run.run_id}/parts/${k}`)&&current();}catch{return false;}}
export async function readResearchCurrentAuditMetadata(listed,{current=()=>true}={}){
 if(!await verifyResearchSharedDirectoryRow(listed,{current})||listed.incomplete_native_artifact===true)throw new Error('当前科研原目录身份无法核对');
 const metadata=(await getResearchTask(listed.run_id,{auditOnly:true})).data;if(!current())return null;
 if(!await verifyResearchTaskMetadata(metadata,{runId:listed.run_id,caseId:listed.research_cohort_case_id,current})||!['feature_key','scope_id','source_projection_hash','source_binding_hash'].every(k=>metadata[k]===listed[k]))throw new Error('当前科研技术metadata与原目录不透明锚无法核对');
 return current()?metadata:null;
}
export async function readResearchSplitTrace(value,{listed=null,caseId=null,current=()=>true}={}){
 const runId=listed?.run_id??value?.run?.run_id;if(!await verifyResearchSplitTrace(value,{runId,caseId,current}))throw new Error('完整科研审计metadata或分件指针无法核对');
 if(listed){if(!await verifyResearchSharedDirectoryRow(listed,{caseId,current})||!['research_cohort_case_id','scope_id','source_projection_hash','source_binding_hash'].every(k=>listed[k]===value.run[k]))throw new Error('原科研目录域或不透明锚发生变化');}
 const metadata=(await getResearchTask(runId,{auditOnly:true})).data;if(!current())return null;if(!await verifyResearchTaskMetadata(metadata,{runId,caseId,current})||!same(metadata,value.run))throw new Error('科研任务metadata已变化，需明确重读');
 if(!metadata.clinical_parts_available)return{metadata,parts:null};
 const parts={};for(const part of metadata.status==='succeeded'?['source','scope','task','result']:['source','scope','task']){const response=await getResearchTaskPart(runId,part,{auditOnly:true});if(!current())return null;parts[part]=response.data;}
 if(listed&&(listed.requested_by!==parts.task?.artifact?.requested_by||listed.provider_id!==parts.task?.artifact?.provider_id))throw new Error('科研目录原请求人或模型锚发生变化');
 if(!await verifyResearchTaskParts(metadata,parts,{auditOnly:true,current}))throw new Error('当前授权科研Source或原始任务TEXT无法核对');
 const latest=(await getResearchTask(runId,{auditOnly:true})).data;if(!current())return null;if(!await verifyResearchTaskMetadata(latest,{runId,caseId,current})||!same(metadata,latest))throw new Error('科研权限或任务在独立分件读取期间已变化');return{metadata,parts};
}
