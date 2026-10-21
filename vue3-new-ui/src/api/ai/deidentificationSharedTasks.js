import request from '@/utils/request';
import {deidentificationCanonical as canonical,deidentificationDigest as digest,deidentificationTextHash as textHash,deidentificationId as uuid,deidentificationHash as hash,deidentificationClock as clock,keys,pick,same,positive,scalar,bytes} from './deidentificationCore';
import {parseDeidentificationJson} from './deidentificationWire';
import {deidentificationTaskInputValid,deidentificationTaskSchemaMatches as schema} from './deidentificationTasks';
import {verifyDeidentificationFrozenSourceRecord,verifyDeidentificationResult,deidentificationUsageValid} from './deidentificationResults';

const MAX=8388608,states=['queued','running','succeeded','failed','cancelled'];
export const deidentificationSharedParts=Object.freeze(['source','scope','task','result']);
const metaKeys=['binding','can_execute','can_export','can_review','clinical_parts_available','create_time','error_code','error_message','feature_key','finish_time','input_tokens','opaque_hashes','output_tokens','part_hashes','parts_wire','preview','proof_scope','raw_frozen_json','result','run_id','schema_version','source','split_artifacts','status','usage_receipt'];
const hashKeys=['source_hash','source_projection_hash','source_content_hash','source_governance_hash','source_binding_hash','prompt_hash','input_hash','evidence_hash','metadata_hash'];
const bindingKeys=['case_id','collection_digest','content_hash','governance_hash','projection_hash','source_id'];
const frameKeys=['binding','can_execute','can_export','can_review','execution','frozen_prompt','provider','publication','raw_frozen_json','raw_hashes','run_id','schema_version','source_binding_hash','source_hash','source_projection_hash','validation'];
const promptKeys=['origin','prompt_version_id','version','native_task_version','system_hash','task_hash','prompt_hash','instructions_digest'];
const rawNames=['input_json','evidence_json','context_metadata_json'],rawHashes=['input_hash','evidence_hash','metadata_hash'];
const canonicalObject=fragments=>'{'+Object.keys(fragments).sort().map(k=>JSON.stringify(k)+':'+fragments[k]).join(',')+'}';
const jsonText=value=>typeof value==='string'&&scalar(value),nullableText=value=>value===null||jsonText(value);
const id=value=>{if(!uuid(value))throw new Error('请指定规范的病例去标识任务标识');return value;};
function rawText(raw,max=MAX){
 if(typeof raw==='string'){if(!scalar(raw)||bytes(raw)<1||bytes(raw)>max)throw new Error('完整分件原UTF8字节无效或超过8MiB');return raw;}
 const value=raw instanceof ArrayBuffer?new Uint8Array(raw):ArrayBuffer.isView(raw)?new Uint8Array(raw.buffer,raw.byteOffset,raw.byteLength):null;
 if(!value||value.byteLength<1||value.byteLength>max)throw new Error('完整分件需要原UTF8字节且不得超过8MiB');
 return new TextDecoder('utf-8',{fatal:true,ignoreBOM:true}).decode(value);
}
export function decodeDeidentificationSharedResponse(raw){
 const text=rawText(raw),value=parseDeidentificationJson(text).value;
 if(!keys(value,['code','msg','data'])||value.code!==200||!jsonText(value.msg))throw new Error('病例去标识任务回执闭集无法核对');
 return value;
}
export function decodeDeidentificationSharedPart(raw){
 const text=rawText(raw),parsed=parseDeidentificationJson(text,{rawPaths:['provider','validation','execution','frozen_prompt','publication'].map(k=>[k])});
 return Object.freeze({value:parsed.value,raw:text});
}
export function decodeDeidentificationCancelResponse(raw){
 const value=parseDeidentificationJson(rawText(raw)).value;
 if(!keys(value,['code','msg'])||value.code!==200||!jsonText(value.msg))throw new Error('停止任务回执无效');return value;
}
const read=(url,params={})=>request({url,method:'get',params,responseType:'arraybuffer',retry:0}).then(decodeDeidentificationSharedResponse);
export const getDeidentificationSharedTask=runId=>read('/ai/runs/'+id(runId));
export const getDeidentificationSharedTrace=runId=>read('/ai/admin/runs/'+id(runId));
export function getDeidentificationSharedPart(runId,part,{auditOnly=false}={}){
 if(!deidentificationSharedParts.includes(part)||typeof auditOnly!=='boolean')throw new Error('请明确独立分件与审计读取方式');
 return request({url:'/ai/deidentification/tasks/'+id(runId)+'/parts/'+part,method:'get',params:{audit_only:auditOnly},responseType:'arraybuffer',retry:0}).then(decodeDeidentificationSharedPart);
}
export function createDeidentificationSharedTask(input,{preview=false}={}){
 if(!deidentificationTaskInputValid(input)||typeof preview!=='boolean')throw new Error('任务仅接受已核对的Case引用和原样可选问题');
 return request({url:'/ai/runs',method:'post',data:JSON.stringify({feature_key:'deidentification',input,preview}),headers:{'Content-Type':'application/json'},responseType:'arraybuffer',retry:0}).then(decodeDeidentificationSharedResponse);
}
export const cancelDeidentificationSharedTask=runId=>request({url:'/ai/runs/'+id(runId)+'/cancel',method:'post',responseType:'arraybuffer',retry:0}).then(decodeDeidentificationCancelResponse);
export function deidentificationRunHasMarkers(value){
 const names=new Set(['deidentification_case_id','deidentification_artifact','frozen_deidentification_audit','deidentification_source','deidentification_binding']);
 const visit=v=>v!==null&&typeof v==='object'&&(Array.isArray(v)?v.some(visit):v.feature_key==='deidentification'||typeof v.schema_version==='string'&&v.schema_version.startsWith('deidentification_')||v.source_domain==='recorded_deidentification_case'||Object.entries(v).some(([k,x])=>names.has(k)||visit(x)));
 return visit(value);
}
export async function verifyDeidentificationSharedMetadata(v,{runId=null,caseId=null,current=()=>true}={}){try{
 if(!current()||!keys(v,metaKeys)||v.schema_version!=='deidentification_shared_task_metadata_v1'||!uuid(v.run_id)||runId!==null&&v.run_id!==runId||v.feature_key!=='deidentification'||!states.includes(v.status)||typeof v.preview!=='boolean'||v.split_artifacts!==true||v.parts_wire!=='canonical_json_body_no_envelope'||!clock(v.create_time)||v.finish_time!==null&&(!clock(v.finish_time)||v.finish_time<v.create_time)||!nullableText(v.error_code)||!nullableText(v.error_message)||[v.can_execute,v.can_review,v.can_export].some(x=>x!==false)||[v.source,v.result,v.raw_frozen_json].some(x=>x!==null)||typeof v.clinical_parts_available!=='boolean'||!keys(v.opaque_hashes,hashKeys)||!Object.values(v.opaque_hashes).every(hash)||!deidentificationUsageValid(v.usage_receipt)||v.usage_receipt.model_call_attempted===null&&(v.input_tokens!==null||v.output_tokens!==null)||v.input_tokens!==v.usage_receipt.input_tokens||v.output_tokens!==v.usage_receipt.output_tokens)return false;
 if(v.clinical_parts_available){
  const b=v.binding,h=v.opaque_hashes;
  if(v.proof_scope!=='currently_authorized_split_artifact_references'||!keys(b,bindingKeys)||!uuid(b.case_id)||caseId!==null&&b.case_id!==caseId||!bindingKeys.filter(k=>!['case_id','source_id'].includes(k)).every(k=>hash(b[k]))||b.source_id!==`deidentification_case:${b.case_id}:${b.content_hash.slice(0,12)}`||b.content_hash!==h.source_content_hash||b.governance_hash!==h.source_governance_hash||b.projection_hash!==h.source_projection_hash||await digest(b)!==h.source_binding_hash||!keys(v.part_hashes,deidentificationSharedParts)||!Object.values(v.part_hashes).every(hash)||v.part_hashes.source!==b.projection_hash||v.part_hashes.scope!==b.content_hash)return false;
 }else if(v.proof_scope!=='technical_metadata_and_opaque_hashes_only'||v.binding!==null||v.part_hashes!==null||caseId!==null)return false;
 if(['queued','running'].includes(v.status)&&v.finish_time!==null||v.status==='succeeded'&&(v.finish_time===null||v.error_code!==null||v.error_message!==null||v.usage_receipt.model_call_attempted!==true)||v.status==='failed'&&v.finish_time===null)return false;
 return current();
}catch{return false;}}
export function verifyDeidentificationIncompleteMetadata(v,{runId=null,directory=false}={}){try{
 const names=['schema_version','run_id','feature_key','status','create_time','split_artifacts','clinical_parts_available','binding','incomplete_native_artifact','error_code','error_message'];
 if(directory)names.push('requested_by','provider_id','feedback_count');
 return keys(v,names)&&v.schema_version==='deidentification_incomplete_task_metadata_v1'&&uuid(v.run_id)&&(runId===null||runId===v.run_id)&&v.feature_key==='deidentification'&&states.includes(v.status)&&clock(v.create_time)&&v.split_artifacts===true&&v.clinical_parts_available===false&&v.binding===null&&v.incomplete_native_artifact===true&&v.error_code==='NATIVE_ARTIFACT_REQUIRED'&&jsonText(v.error_message)&&(!directory||positive(v.requested_by)&&(v.provider_id===null||positive(v.provider_id))&&Number.isSafeInteger(v.feedback_count)&&v.feedback_count>=0);
}catch{return false;}}
export async function verifyDeidentificationSharedTrace(v,expected={},options={}){try{
 if(!keys(v,['schema_version','run','parts_require_independent_current_reads','parts_wire','parts'])||v.schema_version!=='deidentification_split_trace_v1'||v.parts_require_independent_current_reads!==true||v.parts_wire!=='canonical_json_body_no_envelope'||!await verifyDeidentificationSharedMetadata(v.run,expected)||!keys(v.parts,deidentificationSharedParts))return false;
 const prefix='/api/ai/deidentification/tasks/'+v.run.run_id+'/parts/';
 return deidentificationSharedParts.every(k=>v.parts[k]===prefix+k+'?audit_only=true')&&(options.current||(()=>true))();
}catch{return false;}}
export async function verifyDeidentificationSharedParts(metadata,parts,expected={},options={}){const{current=()=>true}=options;try{
 if(!current()||!await verifyDeidentificationSharedMetadata(metadata,{runId:expected.runId??null,caseId:expected.references?.deidentification_case_id??null,current})||!metadata.clinical_parts_available||!keys(parts,deidentificationSharedParts))return false;
 const decoded={};for(const k of deidentificationSharedParts){
  if(!keys(parts[k],['value','raw']))return false;
  decoded[k]=decodeDeidentificationSharedPart(parts[k].raw);
  if(!same(decoded[k].value,parts[k].value)||await textHash(decoded[k].raw)!==metadata.part_hashes[k]||!current())return false;
 }
 const t=decoded.task.value,s=decoded.source.value,scope=decoded.scope.value,result=decoded.result.value,b=metadata.binding,h=metadata.opaque_hashes;
 if(!keys(t,frameKeys)||t.schema_version!=='deidentification_split_task_v1'||t.run_id!==metadata.run_id||[t.can_execute,t.can_review,t.can_export].some(x=>x!==false)||!same(t.binding,b)||t.source_hash!==h.source_hash||t.source_binding_hash!==h.source_binding_hash||t.source_projection_hash!==b.projection_hash||!same(t.raw_hashes,pick(h,rawHashes))||!keys(t.raw_frozen_json,rawNames)||!schema('PublicBinding',b))return false;
 const body={schema_version:'deidentification_task_source_v1',source_snapshot:scope,public_source:s,publication:t.publication,prompt:t.frozen_prompt,provider:t.provider,validation:t.validation,execution:t.execution};
 if(!await verifyDeidentificationFrozenSourceRecord(body,expected,{current})||t.execution.preview!==metadata.preview||scope.capture.collection_digest!==b.collection_digest||t.frozen_prompt.prompt_hash!==h.prompt_hash||scope.case_id!==b.case_id)return false;
 const taskParsed=parseDeidentificationJson(decoded.task.raw,{rawPaths:['provider','validation','execution','frozen_prompt','publication'].map(k=>[k])});
 const raw=k=>taskParsed.raw[JSON.stringify([k])];
 const sourceRaw=canonicalObject({schema_version:JSON.stringify(body.schema_version),source_snapshot:decoded.scope.raw,public_source:decoded.source.raw,publication:raw('publication'),prompt:raw('frozen_prompt'),provider:raw('provider'),validation:raw('validation'),execution:raw('execution')});
 if(bytes(sourceRaw)>MAX||await textHash(sourceRaw)!==h.source_hash)return false;
 const parsed={};for(let i=0;i<rawNames.length;i++){const k=rawNames[i];if(!jsonText(t.raw_frozen_json[k])||bytes(t.raw_frozen_json[k])>65535||await textHash(t.raw_frozen_json[k])!==h[rawHashes[i]]||!current())return false;parsed[k]=parseDeidentificationJson(t.raw_frozen_json[k],{maxBytes:65535}).value;}
 const input=parsed.input_json;if(!schema('FrozenTaskRecord',input)||!deidentificationTaskInputValid(input.input)||input.input.deidentification_case_id!==b.case_id)return false;
 const expectedInput=canonicalObject({schema_version:JSON.stringify('deidentification_task_v1'),catalog_version:JSON.stringify(t.frozen_prompt.catalog_version),input:canonical(input.input),context:canonical(b),provider:raw('provider'),validation:raw('validation'),execution:raw('execution'),prompt:canonical(pick(t.frozen_prompt,promptKeys))});
 const evidence=[{source_id:b.source_id,kind:'complete_selected_fields_only',projection_hash:b.projection_hash}];
 const context={schema_version:'deidentification_task_metadata_v1',binding:b,snapshot_time:t.execution.snapshot_time,instructions_digest:t.frozen_prompt.instructions_digest,model_version:t.provider.model,feature_revision:t.execution.feature_revision};
 if(t.raw_frozen_json.input_json!==expectedInput||t.raw_frozen_json.evidence_json!==canonical(evidence)||t.raw_frozen_json.context_metadata_json!==canonical(context))return false;
 if(metadata.status==='succeeded'){if(!await verifyDeidentificationResult(result,s,t.frozen_prompt.instructions_digest,{current}))return false;}else if(result!==null)return false;
 return current();
}catch{return false;}}
