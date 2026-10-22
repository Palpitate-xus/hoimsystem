import request from '@/utils/request';
import {supportCanonical as canonical,supportDigest as digest,supportId as uuid} from '../inpatientSupport';
import {documentClock} from './documentEvidence';
import {researchVariableFixed as fixed,researchVariableWhole as whole} from './researchVariableProofs';
import {decodeResearchVariableResponse,researchVariableSelectionValid,researchVariableBindingReference,verifyResearchVariableBinding,researchVariableTaskReceiptValid,verifyResearchVariableRun,previewResearchVariableTask,getResearchVariableTask,getResearchVariableTrace,getResearchVariableTaskPart,getResearchVariableHistory} from './researchVariableTasks';

const object=v=>v!==null&&typeof v==='object'&&!Array.isArray(v),same=(a,b)=>canonical(a)===canonical(b),own=(v,k)=>Object.hasOwn(v,k),keys=(v,n)=>object(v)&&same(Object.keys(v).sort(),[...n].sort());
const omit=(v,n)=>Object.fromEntries(Object.entries(v).filter(([key])=>!n.includes(key)));
const scopeNote='完整原件按独立分件核对；登记容量不保证完整模型请求可容纳，入队另全包校验；未调用模型、抽取、导出或验证科学意义。';
const eligibilityBasis='current_recorded_fields_and_reviewed_definitions_not_scientific_validation';

function metadataForScope(value){
 const s=value.snapshot,p=value.proof,c=s.capture,d=c.dictionary_original,g=p.governance;
 return {batch_id:s.batch_id,scope_id:s.scope_id,scope_content_hash:c.scope_original.content_hash,scope_governance_hash:c.scope_original.governance_hash,content_hash:p.content_hash,created_by:s.created_by,created_at:s.created_at,created_event_id:s.created_event_id,last_event_id:p.last_event_id,status:g.status,revision:g.revision,reviewed_by:g.reviewed_by,reviewed_at:g.reviewed_at,revoked_by:g.revoked_by,revoked_at:g.revoked_at,dictionary_id:s.dictionary_id,dictionary_content_hash:d.content_hash,dictionary_governance_hash:d.governance_hash,projection_hash:p.projection_hash,collection_digest:s.collection_digest,member_manifest_hash:s.member_manifest_hash,schema_version:'research_variable_source_metadata_v1',record_kind:'batch',record_id:s.batch_id,technical_only:false,body_included:false,detail_required:true,original:null,review_basis_note:null,revoke_reason:null};
}

// This is the executable preview path, so both current independent pieces
// must remain eligible. It is deliberately separate from frozen audit reads.
export async function verifyResearchVariablePreview(value,sourcePart,scopePart,{selection,current=()=>true}={}){try{
 if(!current()||!researchVariableSelectionValid(selection)||!whole(value)||!whole(sourcePart)||!whole(scopePart)||!keys(value,['schema_version','context','metadata','evidence','research_variable_binding','binding_reference','parts','model_preview','limits','scope_note'])||value.schema_version!=='research_variable_context_preview_v1')return null;
 const binding=value.research_variable_binding,source=sourcePart.value,privateScope=scopePart.value;
 if(!await verifyResearchVariableBinding(binding,source,privateScope,{batchId:selection.research_variable_batch_id,current}))return null;
 const reference=await researchVariableBindingReference(binding),context={scope:{source_domain:fixed.source_domain,selected_sources:{research_variable_batch_id:binding.batch_id}},snapshot_time:value.context.snapshot_time,research_variable_binding:reference,question:selection.question??null,missing_data:fixed.limitations};
 if(!documentClock(context.snapshot_time)||context.snapshot_time<privateScope.proof.governance.reviewed_at||binding.request_authorization.actor_token_invalid_before!==null&&binding.request_authorization.actor_token_invalid_before>context.snapshot_time||!same(value.context,context)||!same(value.binding_reference,reference))return null;
 const metadata={snapshot_time:context.snapshot_time,source_count:1,department_ids:[],context_digest:await digest(context),clinical_context_fingerprint:await digest(omit(context,['snapshot_time'])),missing_data:fixed.limitations};
 const evidence=[{source_id:binding.source_id,kind:'research_variable_batch',content_hash:binding.batch_content_hash,governance_hash:binding.batch_governance_hash,source_digest:binding.source_projection_hash,documents_hash:binding.documents_hash,coverage:'all_declared_recorded_candidates_no_inferred_absence_or_automatic_winner'}];
 if(!same(value.metadata,metadata)||!same(value.evidence,evidence)||!same(value.parts,{source:`/ai/research-variables/batches/${binding.batch_id}/parts/source`,scope:`/ai/research-variables/batches/${binding.batch_id}/parts/snapshot`})||!same(value.model_preview,{included:false,reason:'complete_source_is_an_independent_part'})||!same(value.limits,{independent_piece_bytes:fixed.max_wire_bytes,short_run_column_bytes:fixed.max_run_text_bytes,full_binding_bytes:fixed.max_binding_bytes})||value.scope_note!==scopeNote)return null;
 const expected=metadataForScope(privateScope);
 for(const[name,part]of [['source',sourcePart],['snapshot',scopePart]])if(!keys(part,['schema_version','metadata','part','current_validation','value'])||part.schema_version!=='research_variable_source_part_v1'||part.part!==name||!same(part.metadata,expected)||!same(part.current_validation,{eligible:true,exclusion_reasons:[],eligibility_basis:eligibilityBasis}))return null;
 return current()?{bindingReference:reference,source,privateScope,preview:value,level:'complete_current_originals_and_server_recorded_purpose_anchors'}:null;
}catch{return null;}}

export function getResearchVariablePreviewPart(batchId,part){
 if(!uuid(batchId)||!['source','snapshot'].includes(part))throw new Error('预览须使用明确批次的完整独立分件');
 return request({url:`/ai/research-variables/batches/${batchId}/parts/${part}`,method:'get',responseType:'arraybuffer',retry:0}).then(raw=>decodeResearchVariableResponse(raw));
}

export async function readVerifiedResearchVariablePreview(selection,{current=()=>true}={}){
 if(!current())return null;if(!researchVariableSelectionValid(selection))throw new Error('仅接受明确批次和原样问题');
 const preview=await previewResearchVariableTask(selection);if(!current())return null;
 // Returned addresses are never followed; request both fixed local routes.
 const [source,scope]=await Promise.all(['source','snapshot'].map(part=>getResearchVariablePreviewPart(selection.research_variable_batch_id,part)));if(!current())return null;
 const result=await verifyResearchVariablePreview(preview,source,scope,{selection,current});
 if(!current())return null;if(!result)throw new Error('完整当前批次、原字面值或预览权限锚无法核对，未显示部分原件');return result;
}

function selectedContextMatches(run,selection){
 if(selection===null)return true;if(!researchVariableSelectionValid(selection)||run.research_variable_batch_id!==selection.research_variable_batch_id)return false;
 return {scope:{source_domain:fixed.source_domain,selected_sources:{research_variable_batch_id:selection.research_variable_batch_id}},snapshot_time:run.context_metadata.snapshot_time,research_variable_binding:run.research_variable_findings.binding,question:selection.question??null,missing_data:fixed.limitations};
}

export function researchVariableReceiptContinues(receipt,run){try{
 const batchId=receipt.research_variable_batch_id;
 if(!researchVariableTaskReceiptValid(receipt,{batchId})||!researchVariableTaskReceiptValid(run,{batchId})||run.run_id!==receipt.run_id||['context_digest','prompt_version','provider_revision','preview'].some(key=>run[key]!==receipt[key]))return false;
 const prior=receipt.research_variable_artifact,next=run.research_variable_artifact,phases=['claim_event_id','claim_lease','claimed_at','dispatch_event_id','dispatched_at','usage_event_id'];
 if(!same(omit(prior,phases),omit(next,phases))||phases.some(key=>prior[key]!==null&&prior[key]!==next[key])||!same(run.research_variable_findings.binding,receipt.research_variable_findings.binding))return false;
 if(receipt.status==='running'&&run.status==='queued'||['succeeded','failed','cancelled'].includes(receipt.status)&&run.status!==receipt.status)return false;
 if(receipt.usage_receipt_status==='recorded'&&(run.usage_receipt_status!=='recorded'||!same(run.usage_receipt,receipt.usage_receipt)||!same(run.result_reference,receipt.result_reference)))return false;
 return true;
}catch{return false;}}

export async function readVerifiedResearchVariableTask(runId,{batchId,receipt=null,selection=null,preview=null,withTrace=false,auditOnly=false,current=()=>true}={}){
 if(!current())return null;
 if(!uuid(runId)||!uuid(batchId)||typeof withTrace!=='boolean'||typeof auditOnly!=='boolean'||auditOnly&&!withTrace||receipt!==null&&(receipt.run_id!==runId||!researchVariableTaskReceiptValid(receipt,{batchId,preview})))throw new Error('原任务回执或明确审计方式无效');
 let trace=null,run;
 if(auditOnly){trace=await getResearchVariableTrace(runId);run=trace.run;}else run=await getResearchVariableTask(runId);
 if(!current())return null;
 if(run?.run_id!==runId||run.research_variable_batch_id!==batchId||preview!==null&&run.preview!==Number(preview)||receipt!==null&&!researchVariableReceiptContinues(receipt,run))throw new Error('完整任务与所请求ID、原批次或短回执不符');
 const context=selectedContextMatches(run,selection);if(context===false||context!==true&&(await digest(context)!==run.context_digest||await digest(omit(context,['snapshot_time']))!==run.context_metadata.clinical_context_fingerprint))throw new Error('完整任务未绑定原样提交问题');
 if(!current())return null;
 const partNames=['binding','source','scope','receipt',...(run.status==='succeeded'?['result']:[])];
 const values=await Promise.all(partNames.map(name=>getResearchVariableTaskPart(runId,name,{auditOnly})));if(!current())return null;
 const parts=Object.fromEntries(partNames.map((name,index)=>[name,values[index]]));
 if(withTrace&&!auditOnly){trace=await getResearchVariableTrace(runId);if(!current())return null;}
 const checked=await verifyResearchVariableRun(run,parts,{runId,batchId,auditOnly,trace,current});
 if(!current())return null;if(!checked)throw new Error('完整来源、任务分件或实际回执不一致，未显示部分结果');
 return {run,parts,trace,checked};
}

export async function readResearchVariableHistory(batchId,{current=()=>true}={}){
 if(!current())return null;const rows=await getResearchVariableHistory({batchId});if(!current())return null;
 if(!Array.isArray(rows)||rows.length>30||!whole(rows)||rows.some(row=>!researchVariableTaskReceiptValid(row,{batchId}))||new Set(rows.map(row=>row.run_id)).size!==rows.length)throw new Error('历史目录与当前批次不符，未降级显示通用结果');
 return rows;
}
