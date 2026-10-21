import request from '@/utils/request';
import {operationsCanonical as canonical,operationsDigest as digest,operationsTextHash as textHash,operationsId as uuid,operationsHash as hash,operationsSame as same,operationsKeys as keys,operationsPick as pick,operationsPositive as positive,operationsClock as clock,operationsSchema as schema,operationsWhole as whole,operationsBytes as bytes,operationsScalar as scalar,operationsFixed as fixed,decodeOperationsPart,decodeOperationsResponse,parseOperationsJson} from './operationsSupportCore';
import {getOperationsCase,verifyOperationsCaseMetadata,verifyOperationsPublicSource,operationsRequestValid} from './operationsSupportSources';
export const operationsTaskParts=Object.freeze(['task','source','binding','result']);
export const operationsObjectives=Object.freeze(structuredClone(fixed.objectives));
const BASE='/ai/operations-support',states=['queued','running','succeeded','failed','cancelled'],terminal=['succeeded','failed','cancelled'];
const id=v=>{if(!uuid(v))throw new Error('请明确规范运维任务UUID');return v;};
const nullable=(v,check)=>v===null||check(v),count=v=>Number.isSafeInteger(v)&&v>=0&&v<=2147483647;
const read=path=>request({url:BASE+path,method:'get',responseType:'arraybuffer',retry:0}).then(decodeOperationsResponse);
const presentTask=value=>typeof value==='string'&&scalar(value)&&bytes(value)<=65535&&value.replace(/[\u0009-\u000d\u001c-\u0020\u0085\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000]/gu,'').length>0;
function temperature(v){
 if(typeof v!=='string')return false;const m=v.match(/^(-?)(\d+)(?:\.(\d+))?(?:E([+-]?\d+))?$/iu);if(!m)return false;
 const digits=(m[2]+(m[3]??'')).replace(/^0+/u,'');if(!digits)return true;if(m[1])return false;
 const exponent=Number(m[4]??0);if(!Number.isSafeInteger(exponent))return false;const size=digits.length-(m[3]?.length??0)+exponent;
 return size<1||size===1&&(digits[0]==='1'||digits[0]==='2'&&!/[1-9]/u.test(digits.slice(1)));
}
export function operationsRunHasMarkers(value){
 const markers=new Set(['operations_case_id','operations_support_artifact','operations_source','operations_binding']);
 const visit=x=>x!==null&&typeof x==='object'&&(Array.isArray(x)?x.some(visit):x.feature_key==='operations_support'||typeof x.schema_version==='string'&&x.schema_version.startsWith('operations_')||x.source_domain==='reviewed_operations_documents'||Object.entries(x).some(([k,v])=>markers.has(k)||visit(v)));
 return visit(value);
}
export function verifyOperationsUsage(value){return schema('OperationsUsage',value)&&value.complete===(value.input_tokens!==null&&value.output_tokens!==null)&&(value.model_call_attempted!==false||value.input_tokens===0&&value.output_tokens===0)&&(value.model_call_attempted!==null||value.input_tokens===null&&value.output_tokens===null);}
export function verifyOperationsTaskMetadata(value,{runId=null,selection=null,current=()=>true}={}){try{
 if(!current()||!schema('OperationsTaskMetadata',value)||!clock(value.create_time)||!nullable(value.start_time,clock)||!nullable(value.finish_time,clock)||value.start_time!==null&&value.start_time<value.create_time||runId!==null&&value.run_id!==runId||!whole(value)||value.binding!==null&&!schema('OperationsViewBinding',value.binding)||value.parts_state==='available'!==(value.binding!==null)||!nullable(value.usage,verifyOperationsUsage)||(value.usage===null)!==(value.usage_event_id===null))return false;
 if(value.finish_time!==null){const begin=value.start_time??value.create_time;if(value.finish_clock_basis==='legacy_run_seconds'?(!value.finish_time.endsWith('.000000Z')||value.finish_time.slice(0,19)<begin.slice(0,19)):value.finish_time<begin)return false;}
 if(selection!==null&&(!operationsRequestValid('OperationsTaskSelection',selection)||value.binding===null||selection.operations_case_id!==value.binding.operations_case_id||selection.objective!==value.binding.objective))return false;
 if(value.status==='queued'&&(value.start_time!==null||value.finish_time!==null||value.usage!==null)||value.status==='running'&&(value.start_time===null||value.finish_time!==null||value.usage!==null)||value.status==='succeeded'&&(value.finish_time===null||value.usage?.model_call_attempted!==true||value.error_code!==null||value.error_message!==null)||value.status==='failed'&&value.finish_time===null)return false;
 if(value.finish_clock_basis==='not_finished'&&value.finish_time!==null||value.finish_clock_basis==='actual_usage_receipt_utc6'&&(value.finish_time===null||value.usage===null)||value.receipt_pending&&(value.usage!==null||value.start_time===null))return false;
 return current();
}catch{return false;}}
export async function verifyOperationsDraft(value,source,selection,{current=()=>true}={}){try{
 if(!current()||!schema('OperationsDraft',value)||!operationsRequestValid('OperationsTaskSelection',selection)||!await verifyOperationsPublicSource(source,{current})||value.source_id!==source.source_id||selection.operations_case_id!==source.source_id||value.objective!==selection.objective||await digest(source)!==value.source_sha256||!whole(value))return false;
 const documents=new Map(source.documents.map(v=>[v.source_id,v]));
 const span=(v,runbook=false)=>{const d=documents.get(v.source_id);return d&&(!runbook||d.kind==='runbook')&&v.end_codepoint>v.start_codepoint&&v.end_codepoint<=Array.from(d.text).length&&Array.from(d.text).slice(v.start_codepoint,v.end_codepoint).join('')===v.quote;};
 for(const row of [...value.observations,...value.hypotheses]){const seen=new Set();for(const ref of row.evidence){const k=canonical(pick(ref,['source_id','start_codepoint','end_codepoint']));if(!span(ref)||seen.has(k))return false;seen.add(k);}}
 if(value.manual_checks.length&&(selection.objective!=='prepare_reviewed_checks'||source.action_basis!=='reviewed_runbook_reference_only'))return false;
 if(!value.manual_checks.every(v=>span(v.instruction_reference,true))||source.action_basis==='missing_reviewed_runbook'&&!value.gaps.some(v=>v.kind==='missing_reviewed_runbook'))return false;
 return current();
}catch{return false;}}
function verifyFrames(prompt,execution,metadata,binding){
 if(!keys(prompt,['schema_version','prompt_id','prompt_version','origin','catalog_version','native_task_version','system_prompt','task_prompt','instructions_digest'])||prompt.schema_version!=='operations_prompt_snapshot_v1'||prompt.system_prompt!==fixed.system_prompt||prompt.native_task_version!==fixed.native_task_version||!presentTask(prompt.task_prompt)||typeof prompt.catalog_version!=='string'||!prompt.catalog_version||prompt.prompt_id!==binding.prompt_id||prompt.prompt_version!==binding.prompt_version||prompt.instructions_digest!==metadata.binding.instructions_digest)return false;
 if(prompt.prompt_id===null?(prompt.origin!=='packaged_task'||prompt.prompt_version!==0):(prompt.origin!=='database_version'||!uuid(prompt.prompt_id)||!positive(prompt.prompt_version)))return false;
 if(!keys(execution,['schema_version','feature_key','preview','requester_epoch','configuration','provider_snapshot','feature_validation'])||execution.schema_version!=='operations_execution_snapshot_v1'||execution.feature_key!=='operations_support'||execution.preview!==metadata.preview)return false;
 const actor=execution.requester_epoch,config=execution.configuration,provider=execution.provider_snapshot,validation=execution.feature_validation;
 if(!keys(actor,['user_id','user_role','token_invalid_before'])||actor.user_id!==metadata.requested_by||!['admin','super_admin'].includes(actor.user_role)||!nullable(actor.token_invalid_before,clock)||!keys(config,['revision','enabled','allowed_roles','daily_limit','active_prompt_id'])||config.revision!==binding.config_revision||![0,1].includes(config.enabled)||!positive(config.daily_limit)||config.daily_limit>1000000||config.active_prompt_id!==prompt.prompt_id||!Array.isArray(config.allowed_roles)||!same(config.allowed_roles,[...new Set(config.allowed_roles)].sort())||config.allowed_roles.some(v=>!['super_admin','admin','director','doctor','nurse','cashier','pharmacist','guide','patient','lab_technician','registrar'].includes(v))||actor.user_role!=='super_admin'&&!config.allowed_roles.includes(actor.user_role))return false;
 if(!keys(provider,['provider_id','revision','name','kind','api_base','model','timeout_seconds','max_output_tokens','validation_report','temperature_decimal','allows_patient_data','effective_output_limit'])||provider.provider_id!==binding.provider_id||provider.revision!==binding.provider_revision||!['chat','responses'].includes(provider.kind)||![provider.name,provider.api_base,provider.model,provider.validation_report].every(scalar)||!provider.model.trim()||!positive(provider.timeout_seconds)||provider.timeout_seconds>300||!positive(provider.max_output_tokens)||provider.max_output_tokens>1000000||!positive(provider.effective_output_limit)||provider.effective_output_limit>provider.max_output_tokens||!temperature(provider.temperature_decimal)||typeof provider.allows_patient_data!=='boolean')return false;
 if(!keys(validation,['status','note','validated_by','validated_at'])||typeof validation.status!=='string'||!scalar(validation.note)||!nullable(validation.validated_by,positive)||!nullable(validation.validated_at,clock)||!metadata.preview&&(config.enabled!==1||validation.status!=='validated'))return false;
 return true;
}
function receiptShape(r){
 const names=['schema_version','run_id','case_id','requested_by','created_audit_event_id','claim_event_id','dispatch_event_id','lease_token','source_projection_hash','source_binding_hash','instructions_digest','usage','status','error_code','latency_ms','result_hash','result_reference_hash','terminal_header_hash','recorded_at'];
 return keys(r,names)&&r.schema_version==='operations_support_usage_event_v1'&&uuid(r.run_id)&&uuid(r.case_id)&&positive(r.requested_by)&&positive(r.created_audit_event_id)&&nullable(r.claim_event_id,positive)&&nullable(r.dispatch_event_id,positive)&&nullable(r.lease_token,uuid)&&['source_projection_hash','source_binding_hash','instructions_digest','result_reference_hash','terminal_header_hash'].every(k=>hash(r[k]))&&nullable(r.result_hash,hash)&&verifyOperationsUsage(r.usage)&&terminal.includes(r.status)&&nullable(r.error_code,v=>typeof v==='string'&&/^[A-Z][A-Z0-9_]{0,79}$/u.test(v))&&count(r.latency_ms)&&clock(r.recorded_at);
}
export async function verifyOperationsTaskParts(metadata,parts,{caseMetadata,selection=null,current=()=>true}={}){try{
 if(!current()||!verifyOperationsTaskMetadata(metadata,{selection,current})||metadata.parts_state!=='available'||!keys(parts,operationsTaskParts)||!verifyOperationsCaseMetadata(caseMetadata)||!caseMetadata.source_accessible)return false;
 for(const name of operationsTaskParts){if(!keys(parts[name],['value','raw'])||!same(decodeOperationsPart(parts[name].raw).value,parts[name].value)||!current())return false;}
 const task=parts.task.value,source=parts.source.value,b=parts.binding.value,result=parts.result.value,bind=metadata.binding;
 if(!schema('OperationsTaskPart',task)||!schema('OperationsBindingPart',b)||task.run_id!==metadata.run_id||b.run_id!==metadata.run_id||!same(task.binding,bind)||!same(b.binding,bind)||b.requested_by!==metadata.requested_by||!clock(b.recorded_at)||b.recorded_at!==metadata.create_time||caseMetadata.case_id!==bind.operations_case_id||caseMetadata.source_count!==source.documents?.length||!await verifyOperationsPublicSource(source,{caseMetadata,current})||await textHash(parts.source.raw)!==bind.source_projection_hash||bytes(parts.source.raw)!==b.source_bytes||caseMetadata.public_hash!==bind.source_projection_hash)return false;
 const privateBinding={schema_version:'operations_source_binding_v1',case_id:caseMetadata.case_id,case_requested_by:caseMetadata.requested_by,case_private_hash:caseMetadata.private_hash,case_public_hash:caseMetadata.public_hash,case_membership_hash:caseMetadata.member_bindings_hash,case_creation_event_id:caseMetadata.creation_event_id,case_assembled_at:caseMetadata.assembled_at,objective:bind.objective};
 if(await digest(privateBinding)!==bind.source_binding_hash||await textHash(task.prompt_snapshot_json)!==bind.prompt_snapshot_hash||await textHash(task.execution_snapshot_json)!==bind.execution_snapshot_hash||!current())return false;
 const prompt=parseOperationsJson(task.prompt_snapshot_json,262144),execution=parseOperationsJson(task.execution_snapshot_json,262144);
 if(!verifyFrames(prompt,execution,metadata,b)||await textHash(prompt.system_prompt+'\n\n'+prompt.task_prompt)!==bind.instructions_digest)return false;
 const input={schema_version:'operations_support_task_ref_v1',operations_case_id:bind.operations_case_id,objective:bind.objective,...pick(bind,['source_projection_hash','source_binding_hash','prompt_snapshot_hash','execution_snapshot_hash'])};
 const evidence=[{kind:'reviewed_operations_documents',source_id:bind.operations_case_id,source_projection_hash:bind.source_projection_hash,source_binding_hash:bind.source_binding_hash}];
 const rawMetadata={schema_version:'operations_support_task_metadata_v1',operations_case_id:bind.operations_case_id,objective:bind.objective,instructions_digest:bind.instructions_digest,provider_id:b.provider_id,provider_revision:b.provider_revision};
 if(task.raw.input_json!==canonical(input)||task.raw.evidence_json!==canonical(evidence)||task.raw.context_metadata_json!==canonical(rawMetadata))return false;
 const ids=[b.created_audit_event_id,b.claim_event_id,b.dispatch_event_id,b.usage_event_id].filter(v=>v!==null);if(new Set(ids).size!==ids.length||(b.claim_event_id===null)!==(b.lease_token===null)||(b.claim_event_id===null)!==(b.claimed_at===null)||(b.dispatch_event_id===null)!==(b.dispatched_at===null)||(b.usage_event_id===null)!==(b.usage_receipt_json===null)||!nullable(b.claimed_at,clock)||!nullable(b.dispatched_at,clock)||b.claimed_at!==null&&b.claimed_at<b.recorded_at||b.dispatched_at!==null&&(b.claimed_at===null||b.dispatched_at<b.claimed_at)||b.usage_event_id!==metadata.usage_event_id||metadata.start_time!==b.claimed_at)return false;
 if(b.usage_receipt_json!==null){
  const r=parseOperationsJson(b.usage_receipt_json,65535);if(!receiptShape(r)||r.run_id!==metadata.run_id||r.case_id!==bind.operations_case_id||r.requested_by!==metadata.requested_by||!same(pick(r,['created_audit_event_id','claim_event_id','dispatch_event_id','lease_token']),pick(b,['created_audit_event_id','claim_event_id','dispatch_event_id','lease_token']))||!same(pick(r,['source_projection_hash','source_binding_hash','instructions_digest']),pick(bind,['source_projection_hash','source_binding_hash','instructions_digest']))||!same(r.usage,metadata.usage)||r.status!==metadata.status||r.error_code!==metadata.error_code||r.recorded_at!==metadata.finish_time||r.recorded_at<(b.dispatched_at??b.claimed_at??b.recorded_at)||b.claim_event_id===null&&(r.dispatch_event_id!==null||r.status==='succeeded'||r.usage.model_call_attempted!==false))return false;
  if(metadata.status==='succeeded'){
   const resultHash=await textHash(parts.result.raw),ref={schema_version:'operations_support_result_ref_v1',run_id:metadata.run_id,source_binding_hash:bind.source_binding_hash,instructions_digest:bind.instructions_digest,result_sha256:resultHash,result_bytes:bytes(parts.result.raw)};
   if(r.result_hash!==resultHash||await digest(ref)!==r.result_reference_hash)return false;
  }else if(r.result_hash!==null||r.result_reference_hash!==await textHash('{}'))return false;
 }else if(metadata.usage!==null||metadata.receipt_pending!==(b.dispatch_event_id!==null))return false;
 const selected={operations_case_id:bind.operations_case_id,objective:bind.objective};
 if(metadata.status==='succeeded'?!await verifyOperationsDraft(result,source,selected,{current}):result!==null)return false;
 return current();
}catch{return false;}}
export function verifyOperationsTrace(value,{runId=null,current=()=>true}={}){try{
 return current()&&keys(value,['schema_version','run','parts_require_independent_current_reads','parts_wire','parts'])&&value.schema_version==='operations_support_split_trace_v1'&&value.parts_require_independent_current_reads===true&&value.parts_wire==='canonical_json_body_no_envelope'&&verifyOperationsTaskMetadata(value.run,{runId,current})&&value.run.parts_state==='available'&&keys(value.parts,operationsTaskParts)&&operationsTaskParts.every(k=>value.parts[k]===`/api/ai/operations-support/tasks/${value.run.run_id}/parts/${k}`);
}catch{return false;}}
export const getOperationsTaskDescriptor=()=>read('/task-descriptor');
export const getOperationsTask=runId=>read('/tasks/'+id(runId));
export const getOperationsTaskTrace=runId=>read('/tasks/'+id(runId)+'/trace');
export function getOperationsTaskPart(runId,name){if(!operationsTaskParts.includes(name))throw new Error('运维任务仅接受明确四分件');return request({url:BASE+'/tasks/'+id(runId)+'/parts/'+name,method:'get',responseType:'arraybuffer',retry:0}).then(decodeOperationsPart);}
export function createOperationsTask(value,{preview=false}={}){if(!operationsRequestValid('OperationsTaskSelection',value)||typeof preview!=='boolean')throw new Error('运维任务仅接受明确材料集与三个固定目标之一');return request({url:'/ai/runs',method:'post',data:canonical({feature_key:'operations_support',input:value,preview}),headers:{'Content-Type':'application/json'},responseType:'arraybuffer',retry:0}).then(decodeOperationsResponse);}
export const cancelOperationsTask=runId=>request({url:BASE+'/tasks/'+id(runId)+'/cancel',method:'post',responseType:'arraybuffer',retry:0}).then(decodeOperationsResponse);
export function getOperationsTasks({caseId=null,page=1,size=20}={}){if(caseId!==null&&!uuid(caseId)||!positive(page)||page>1000000||!positive(size)||size>50)throw new Error('请明确有界技术目录与可选材料集');return request({url:BASE+'/tasks',method:'get',params:{...(caseId===null?{}:{case_id:caseId}),page,size},responseType:'arraybuffer',retry:0}).then(decodeOperationsResponse);}
export function verifyOperationsTaskDirectory(value,{page=1,size=20,current=()=>true}={}){try{return current()&&keys(value,['items','page','size','has_more','pagination_basis'])&&value.page===page&&value.size===size&&typeof value.has_more==='boolean'&&Array.isArray(value.items)&&value.items.length<=size&&new Set(value.items.map(x=>x.run_id)).size===value.items.length&&value.items.every(x=>verifyOperationsTaskMetadata(x,{current}))&&value.pagination_basis==='committed_opaque_task_candidates_before_independent_current_part_authorization';}catch{return false;}}
export async function loadOperationsTaskBundle(runId,{caseId=null,selection=null,auditOnly=false,current=()=>true}={}){
 if(!current()||typeof auditOnly!=='boolean'||caseId!==null&&!uuid(caseId))throw new Error('当前读取已关闭');
 const metadata=(await getOperationsTask(runId)).data;if(!verifyOperationsTaskMetadata(metadata,{runId,current}))throw new Error('技术状态无法核对');
 if(metadata.parts_state!=='available')return{metadata,parts:null,caseMetadata:null,trace:null};
 if(caseId!==null&&metadata.binding.operations_case_id!==caseId)throw new Error('当前任务不属于原目录明确材料集');
 if(selection!==null&&!verifyOperationsTaskMetadata(metadata,{runId,selection,current}))throw new Error('任务与本次明确选择不同');
 const caseMetadata=(await getOperationsCase(metadata.binding.operations_case_id)).data;if(!current()||!verifyOperationsCaseMetadata(caseMetadata)||!caseMetadata.source_accessible)throw new Error('当前受审材料集已失效');
 let trace=null;if(auditOnly){trace=(await getOperationsTaskTrace(runId)).data;if(!verifyOperationsTrace(trace,{runId,current})||!same(trace.run,metadata))throw new Error('审计目录与当前任务状态已变化');}
 if(!current())throw new Error('当前读取已关闭');
 const parts=Object.fromEntries(await Promise.all(operationsTaskParts.map(async k=>[k,await getOperationsTaskPart(runId,k)])));
 if(!await verifyOperationsTaskParts(metadata,parts,{caseMetadata,selection,current})||!current())throw new Error('完整材料、原始Prompt、实际用量或引用无法核对');
 return{metadata,parts,caseMetadata,trace};
}
export function feedbackOperationsTask(runId,outcome,comment=''){
 if(!['accepted','modified','rejected'].includes(outcome)||!scalar(comment)||Array.from(comment).length>2000||bytes(comment)>8000)throw new Error('反馈须为明确状态与完整原文');
 return request({url:'/ai/runs/'+id(runId)+'/feedback',method:'post',data:canonical({outcome,comment}),headers:{'Content-Type':'application/json'},responseType:'arraybuffer',retry:0}).then(decodeOperationsResponse);
}
export const operationsReferencesValid=value=>keys(value,['operations_case_id'])&&uuid(value.operations_case_id);
export function verifyOperationsTaskDescriptor(value){return keys(value,['feature_key','native_task_version','objectives','parts','parts_wire','max_part_utf8_bytes'])&&value.feature_key==='operations_support'&&value.native_task_version===fixed.native_task_version&&same(value.objectives,fixed.objectives)&&same(value.parts,operationsTaskParts)&&value.parts_wire==='canonical_json_body_no_envelope'&&value.max_part_utf8_bytes===8388608;}
export function verifyOperationsCancelAck(value,{runId=null}={}){return keys(value,['schema_version','run_id','status','cancel_event_id','usage_event_id','receipt_pending','automatic_legacy_write'])&&value.schema_version==='operations_support_cancel_ack_v1'&&uuid(value.run_id)&&(runId===null||runId===value.run_id)&&value.status==='cancelled'&&positive(value.cancel_event_id)&&nullable(value.usage_event_id,positive)&&typeof value.receipt_pending==='boolean'&&value.receipt_pending===(value.usage_event_id===null)&&value.automatic_legacy_write===false;}
export function operationsFeatureAllowed(feature,role,{preview=false}={}){try{
 return feature?.key==='operations_support'&&feature.number===79&&feature.engine==='llm'&&feature.scope==='input'&&feature.input_mode==='operations_support_evidence'&&same(feature.source_reference_keys,['operations_case_id'])&&feature.provider_configured===true&&['admin','super_admin'].includes(role)&&Array.isArray(feature.allowed_roles)&&new Set(feature.allowed_roles).size===feature.allowed_roles.length&&(role==='super_admin'||feature.allowed_roles.includes(role))&&(preview?role==='super_admin':feature.enabled===true&&feature.validation_status==='validated');
}catch{return false;}}

export async function resolveOperationsCitation(span,source,{current=()=>true}={}){try{
 if(!current()||!keys(span,['source_id','start_codepoint','end_codepoint','quote'])||!uuid(span.source_id)||!Number.isSafeInteger(span.start_codepoint)||!Number.isSafeInteger(span.end_codepoint)||span.start_codepoint<0||span.end_codepoint<=span.start_codepoint||!scalar(span.quote)||!span.quote||!await verifyOperationsPublicSource(source,{current}))return null;
 const document=source.documents.find(v=>v.source_id===span.source_id),text=document&&Array.from(document.text);if(!text||span.end_codepoint>text.length||text.slice(span.start_codepoint,span.end_codepoint).join('')!==span.quote||!current())return null;
 return{...span,document};
}catch{return null;}}
