import fixed from './rcaEvidenceFixed.json';
import {supportCanonical} from '../inpatientSupport';
import {rcaSchema,rcaSchemaDefinition,rcaBound,rcaKeys,rcaSame,rcaClock,rcaDigest,rcaBytes,rcaHash,rcaPlain,rcaQuoteValid,rcaGovernance,verifyRcaPublic,verifyRcaCase,projectRcaCase,parseRcaJson} from './rcaEvidenceProofs';
const floor=value=>value.slice(0,19)+'.000000Z',emptyHash=()=>rcaDigest({});
const chosen=(value,expected={})=>(!expected.runId||value.run_id===expected.runId)&&(!expected.caseId||(value.rca_evidence_case_id||value.case_id)===expected.caseId);
export function rcaRunHasMarkers(v){if(!v||typeof v!=='object'||Array.isArray(v))return false;const has=(x,k)=>x!==null&&typeof x==='object'&&Object.prototype.hasOwnProperty.call(x,k);return v.feature_key==='incident_rca'||v.input_mode==='rca_evidence'||has(v.input,'rca_evidence_case_id')||['rca_evidence_case_id','rca_evidence_findings','rca_evidence_artifact'].some(k=>has(v,k))||has(v.result,'rca_evidence_draft')||has(v.frozen_request?.payload?.input,'rca_evidence_case_id')||has(v.frozen_request?.payload?.context,'rca_evidence_binding')||v.frozen_request?.payload?.context?.source_domain===fixed.source_domain||typeof v.result_reference?.schema_version==='string'&&v.result_reference.schema_version.startsWith('rca_evidence_');}
export function rcaBindingValid(v){try{
 if(!rcaSchema('RcaTaskBinding',v)||v.source_id!==`rca_case:${v.case_id}:${v.case_content_hash.slice(0,12)}`||!rcaClock(v.source_snapshot_time)||(v.patient_grant===null)!==(v.patient_id_at_capture===null))return false;
 for(const [grant,kind]of [[v.event_grant,'event_investigation'],[v.patient_grant,'associated_patient_processing']]){if(grant===null)continue;if(grant.event_id!==v.event_id||grant.patient_id_at_grant!==v.patient_id_at_capture||grant.grantee_id!==v.requested_by||grant.permission_kind!==kind||!rcaClock(grant.issued_at)||!rcaClock(grant.valid_until)||grant.issued_at>=grant.valid_until)return false;}
 return v.patient_grant===null||v.patient_grant.grant_id!==v.event_grant.grant_id;
}catch{return false;}}
export function rcaContextValid(v){try{
 if(!rcaSchema('RcaShortContext',v)||!rcaBound(v)||!rcaBindingValid(v.rca_evidence_binding)||!rcaClock(v.snapshot_time))return false;const b=v.rca_evidence_binding;
 if(v.scope_note!==fixed.scope_note||v.source_domain!==fixed.source_domain||!rcaSame(v.missing_data,fixed.missing_data)||!rcaKeys(v.selected_sources,['rca_evidence_case_id'])||v.selected_sources.rca_evidence_case_id!==b.case_id||b.source_snapshot_time>v.snapshot_time)return false;
 return [b.event_grant,b.patient_grant].every(g=>g===null||g.issued_at<=v.snapshot_time&&v.snapshot_time<g.valid_until);
}catch{return false;}}
export const rcaEvidenceFor=b=>[{source_id:b.source_id,kind:'rca_evidence_case',title:'明确事件的受审发布资料及独立用途绑定',content:supportCanonical({rca_evidence_binding:b})}];
// The evidence body is the same complete canonical binding, not a text excerpt.
function evidenceValid(value,b){return rcaSame(value,rcaEvidenceFor(b));}
async function metadataValid(v,context){return rcaSchema('RcaTaskMetadata',v)&&rcaClock(v.snapshot_time)&&v.snapshot_time===context.snapshot_time&&v.context_digest===await rcaDigest(context)&&v.clinical_context_fingerprint===await rcaDigest(Object.fromEntries(Object.entries(context).filter(([k])=>k!=='snapshot_time')))&&v.tool_fingerprint===await emptyHash()&&rcaSame(v.missing_data,fixed.missing_data);}
export async function verifyRcaPreview(v,expected={}, {current=()=>true}={}){try{
 if(!current()||!rcaSchema('RcaPreview',v)||!rcaBound(v)||!rcaContextValid(v.context))return false;const b=v.context.rca_evidence_binding;
 return (!expected.caseId||b.case_id===expected.caseId)&&v.source_url===`/api/ai/admin/rca-evidence/cases/${b.case_id}/public-source`&&v.case_url===`/api/ai/admin/rca-evidence/cases/${b.case_id}`&&await metadataValid(v.metadata,v.context)&&await evidenceValid(v.evidence,b)&&current();
}catch{return false;}}
export function rcaUsageValid(v){return rcaSchema('RcaUsageReceipt',v)&&v.complete===(v.input_tokens!==null&&v.output_tokens!==null)&&(v.model_call_attempted!==false||v.input_tokens===0&&v.output_tokens===0)&&(v.model_call_attempted!==null||v.input_tokens===null&&v.output_tokens===null);}
export function rcaSummaryValid(v,expected={}){
 if(!rcaSchema('RcaRunSummary',v)||!rcaBound(v)||!chosen(v,expected)||![v.create_time,v.start_time,v.finish_time].every(t=>t===null||rcaClock(t)&&t.endsWith('.000000Z')))return false;
 if(v.start_time!==null&&v.start_time<v.create_time||v.finish_time!==null&&v.finish_time<(v.start_time||v.create_time))return false;
 const usage=v.usage_receipt;
 if(usage!==null&&!rcaUsageValid(usage)||v.input_tokens!==(usage?.input_tokens??null)||v.output_tokens!==(usage?.output_tokens??null)||(v.usage_receipt_status==='recorded')!==(usage!==null))return false;
 return rcaClock(v.context_metadata.snapshot_time)&&rcaSame(v.context_metadata.missing_data,fixed.missing_data);
}
const summaryValid=rcaSummaryValid;
export function rcaSummaryCanAdvance(before,after){if(!summaryValid(before,{})||!summaryValid(after,{}))return false;const fields=['run_id','feature_key','feature_name','preview','prompt_version','provider_revision','context_digest','patient_id','encounter_ref','create_time','run_clock_basis','requires_human_review','context_metadata','rca_evidence_case_id'];if(fields.some(k=>!rcaSame(before[k],after[k]))||before.start_time!==null&&before.start_time!==after.start_time||before.usage_receipt!==null&&before.finish_time!==null&&before.finish_time!==after.finish_time||before.usage_receipt!==null&&!rcaSame(before.usage_receipt,after.usage_receipt))return false;return before.status==='queued'||before.status==='running'&&after.status!=='queued'||before.status===after.status;}
export function rcaHistoryValid(v,{caseId=null,page=1,pageSize=20}={}){try{
 if(!rcaSchema('RcaHistoryResponse',v)||!rcaBound(v)||v.page!==page||v.page_size!==pageSize||v.data.length>pageSize||v.data.length>Math.max(0,v.total-(page-1)*pageSize)||new Set(v.data.map(x=>x.run_id)).size!==v.data.length)return false;
 return v.data.every(row=>summaryValid(row,{caseId}));
}catch{return false;}}
export async function verifyRcaTask(v,expected={}, {current=()=>true,auditOnly=false}={}){try{
 if(!current()||!rcaSchema(auditOnly?'RcaRunTrace':'RcaRunDetail',v)||!rcaBound(v))return false;
 const summary=Object.fromEntries(Object.keys(rcaSchemaDefinition('RcaRunSummary').properties).map(k=>[k,v[k]]));
 if(!summaryValid(summary,expected))return false;const a=v.rca_evidence_artifact,f=v.rca_evidence_findings,b=f.rca_evidence_binding,context=f.context;
 if(!rcaContextValid(context)||!rcaSame(b,context.rca_evidence_binding)||f.input.rca_evidence_case_id!==b.case_id||!rcaBindingValid(b)||!await metadataValid(v.context_metadata,context)||!await evidenceValid(v.evidence,b))return false;
 if(v.run_id!==a.run_id||v.rca_evidence_case_id!==a.case_id||v.context_digest!==a.context_digest||b.case_id!==a.case_id||b.event_id!==a.event_id||b.patient_id_at_capture!==a.patient_id_at_capture||b.requested_by!==a.requested_by||b.event_grant.grant_id!==a.event_grant_id||(b.patient_grant?.grant_id??null)!==a.patient_grant_id||b.source_projection_hash!==a.source_hash||b.source_bytes!==a.source_bytes||await rcaDigest(b)!==a.binding_hash||rcaBytes(b)!==a.binding_bytes||v.context_metadata.instructions_digest!==a.instructions_digest||await rcaDigest(context)!==a.context_digest)return false;
 if(!rcaClock(a.recorded_at)||floor(a.recorded_at)!==v.create_time||a.recorded_at<context.snapshot_time||a.actor_token_invalid_before!==null&&(!rcaClock(a.actor_token_invalid_before)||a.actor_token_invalid_before>context.snapshot_time))return false;
 const claimed=a.claim_event_id!==null,dispatched=a.dispatch_event_id!==null;
 if(claimed!==(a.claim_lease!==null)||claimed!==(a.claimed_at!==null)||claimed&&( !rcaClock(a.claimed_at)||a.claimed_at<a.recorded_at||v.start_time!==floor(a.claimed_at))||!claimed&&v.start_time!==null||dispatched!==(a.dispatched_at!==null)||dispatched&&(!claimed||!rcaClock(a.dispatched_at)||a.dispatched_at<a.claimed_at))return false;
 const ids=[a.create_event_id,a.claim_event_id,a.dispatch_event_id,a.usage_event_id,v.result_reference?.accept_audit_event_id??null].filter(x=>x!==null);if(new Set(ids).size!==ids.length)return false;
 if((a.usage_event_id!==null)!==(v.usage_receipt!==null))return false;
 if(v.status==='queued'&&(claimed||v.finish_time!==null||v.usage_receipt!==null)||v.status==='running'&&(!claimed||v.finish_time!==null||v.usage_receipt!==null))return false;
 if(['succeeded','failed','cancelled'].includes(v.status)&&v.finish_time===null)return false;
 if(v.status==='failed'&&v.usage_receipt===null||v.status==='cancelled'&&v.latency_ms!==null&&v.usage_receipt===null)return false;
 if(v.status==='succeeded'&&(!dispatched||v.error_code!==null||v.usage_receipt?.model_call_attempted!==true||!v.result_reference||v.result_reference.run_id!==v.run_id||v.result_reference.accepted_lease!==a.claim_lease))return false;
 if(v.status!=='succeeded'&&v.result_reference!==null)return false;
 const root=`/api/ai/${auditOnly?'admin/':''}runs/${v.run_id}/rca-evidence/`;
 return Object.entries(v.parts).every(([key,path])=>path===root+key)&&current();
}catch{return false;}}
export async function verifyRcaResult(v,source,instructions,{current=()=>true}={}){try{
 if(!current()||!rcaSchema('RcaEvidenceGenerationResult',v)||!rcaBound(v)||!await verifyRcaPublic(source,{current}))return false;const d=v.rca_evidence_draft;
 if(d.case_id!==source.case_id||d.source_projection_hash!==await rcaDigest(source)||d.instructions_digest!==instructions||d.coverage!==fixed.coverage)return false;
 const items=new Map(source.items.map(x=>[x.item_id,x])),timeline=new Set(source.timeline.map(x=>x.entry_id));
 for(const h of d.hypotheses){if(!rcaPlain(h.hypothesis,16000)||!h.supporting_quotes.length&&!h.evidence_needed.length||new Set(h.timeline_entry_ids).size!==h.timeline_entry_ids.length||h.timeline_entry_ids.some(id=>!timeline.has(id))||[...h.evidence_needed,...h.investigation_questions].some(x=>!rcaPlain(x,8000)))return false;for(const q of [...h.supporting_quotes,...h.conflicting_quotes])if(!items.has(q.item_id)||!rcaQuoteValid(q,items.get(q.item_id).text))return false;}
 if(d.clarification_questions.some(x=>!rcaPlain(x,8000)))return false;
 const expected={summary:`已生成${d.hypotheses.length}项未核实调查假设；逐字引用核对不认证因果或责任。`,sections:[{title:'本次资料范围',content:'仅使用所选事件的有限受审发布稿与人工时间线，未证明调查完整。',source_ids:[source.source_id]},{title:'草稿状态',content:'候选假设、冲突引文和问题保留在独立草稿中，须逐项调查；未自动保存至原RCA或推进PDCA。',source_ids:[]}],warnings:['隐私、原意和来源发布审核不认证因果解释、责任归属、临床适用或整改成效。','空假设或空问题不表示没有事件促成因素或调查已经完成。'],missing_data:fixed.missing_data,rca_evidence_draft:d};
 return rcaSame(v,expected)&&current();
}catch{return false;}}
export async function verifyRcaTaskParts(row,parts,expected={},options={}){try{
 const current=options.current||(()=>true);if(!await verifyRcaTask(row,expected,options)||!rcaKeys(parts,['source','case','result','receipt']))return false;
 const source=parts.source,body=parts.case,receipt=parts.receipt,b=row.rca_evidence_findings.rca_evidence_binding,a=row.rca_evidence_artifact;
 if(!await verifyRcaCase(body,{frozen:true,current})||!rcaSame(await projectRcaCase(body,{frozen:true,current}),source)||source.case_id!==b.case_id||source.content_hash!==b.case_content_hash||source.governance_hash!==b.case_governance_hash||body.immutable.capture.collection_hash!==b.collection_hash||await rcaDigest(source)!==b.source_projection_hash||rcaBytes(source)!==b.source_bytes||source.snapshot_time!==b.source_snapshot_time||(source.event_state.patient_association==='recorded_patient')!==(b.patient_id_at_capture!==null))return false;
 if(receipt===null){if(row.usage_receipt!==null||a.usage_event_id!==null)return false;}else{
  if(!rcaSchema('RcaUsageEvent',receipt)||!rcaBound(receipt)||!rcaUsageValid(receipt.usage)||!rcaSame(receipt.usage,row.usage_receipt)||receipt.run_id!==row.run_id||receipt.case_id!==b.case_id||receipt.claim_event_id!==a.claim_event_id||receipt.dispatch_event_id!==a.dispatch_event_id||receipt.lease_token!==a.claim_lease||receipt.binding_hash!==a.binding_hash||receipt.source_hash!==a.source_hash||receipt.status!==row.status||receipt.error_code!==row.error_code||!rcaClock(receipt.recorded_at)||floor(receipt.recorded_at)!==row.finish_time||receipt.recorded_at<(a.dispatched_at||a.claimed_at||a.recorded_at)||receipt.usage.model_call_attempted!==false&&a.dispatch_event_id===null||receipt.usage.model_call_attempted===null&&receipt.error_code!=='WORKER_INTERRUPTED')return false;
 }
 if(row.status==='succeeded')return receipt!==null&&await verifyRcaResult(parts.result,source,a.instructions_digest,{current})&&await rcaDigest(parts.result)===row.result_reference.result_hash&&rcaBytes(parts.result)===row.result_reference.result_bytes&&receipt.result_hash===row.result_reference.result_hash&&current();
 return parts.result===null&&(receipt===null||receipt.result_hash===null)&&current();
}catch{return false;}}
export function verifyRcaCancelAck(v,runId){return rcaSchema('RcaCancelAcknowledgement',v)&&v.run_id===runId&&v.receipt_pending===(v.usage_event_id===null)&&v.cancel_event_id!==v.usage_event_id;}
export async function verifyRcaQueuedAck(v,row,{current=()=>true,auditOnly=false}={}){try{
 if(!summaryValid(v,{runId:row.run_id,caseId:row.rca_evidence_case_id})||v.status!=='queued'||!await verifyRcaTask(row,{}, {current,auditOnly}))return false;
 const fields=['run_id','feature_key','feature_name','preview','prompt_version','provider_revision','context_digest','patient_id','encounter_ref','create_time','run_clock_basis','requires_human_review','context_metadata','rca_evidence_case_id'];return fields.every(k=>rcaSame(v[k],row[k]))&&current();
}catch{return false;}}
export async function verifyRcaTrace(v,parts,expected={}, {current=()=>true}={}){try{
 if(!await verifyRcaTaskParts(v,parts,expected,{current,auditOnly:true}))return false;const a=v.rca_evidence_artifact,f=v.frozen_request,raw=v.raw_frozen_json;
 if(v.requested_by!==a.requested_by||v.provider_id!==f.provider_snapshot.provider_id||v.provider_revision!==f.provider_snapshot.revision||!rcaSame(f.payload.context,v.rca_evidence_findings.context)||!rcaSame(f.payload.input,v.rca_evidence_findings.input)||!rcaKeys(f.payload.tools,[])||!rcaSame(f.payload.evidence,v.evidence)||f.system_prompt!==fixed.system_prompt||!rcaPlain(f.task_prompt,65535))return false;
 for(const [key,field]of [['input_json','input_hash'],['evidence_json','evidence_hash'],['context_metadata_json','metadata_hash']])if(rcaBytes(raw[key])>65535||await rcaHash(raw[key])!==a[field])return false;
 if(!rcaSame(parseRcaJson(raw.input_json),f)||!rcaSame(parseRcaJson(raw.evidence_json),v.evidence)||!rcaSame(parseRcaJson(raw.context_metadata_json),v.context_metadata))return false;
 if(await rcaDigest([f.system_prompt,f.task_prompt])!==a.prompt_hash||await rcaHash(f.system_prompt+'\n\n'+f.task_prompt)!==a.instructions_digest||v.context_metadata.model_version!==f.provider_snapshot.model||v.context_metadata.feature_revision!==f.feature_validation.feature_revision||v.context_metadata.validation_status!==f.feature_validation.status||!rcaSame(f.source_case_governance,parts.case.governance)||f.actor_epoch.token_invalid_before!==a.actor_token_invalid_before)return false;
 const g=v.current_case_governance,original=parts.case.governance;
 if(!rcaGovernance(g,parts.case.immutable.recorded_at)||!['published','revoked'].includes(g.status)||g.status==='revoked'&&g.revision!==3||!Object.keys(original).filter(k=>!['status','revision','revoked_by','revoked_at','revoke_reason','revoked_audit_event_id'].includes(k)).every(k=>rcaSame(original[k],g[k]))||await rcaDigest({case_id:a.case_id,content_hash:parts.case.content_hash,governance:g})!==v.current_case_governance_hash)return false;
 const ids={create:a.create_event_id,claim:a.claim_event_id,dispatch:a.dispatch_event_id,usage:a.usage_event_id,accept:v.result_reference?.accept_audit_event_id??null};
 for(const [phase,pk]of Object.entries(ids)){const event=v.phase_audits[phase];if(pk===null){if(event!==null)return false;continue;}if(!event||event.event_id!==pk||event.actor_id!==a.requested_by||event.action!=='rca_run.'+phase||event.target!==v.run_id||!rcaClock(event.create_time)||!event.create_time.endsWith('.000000Z')||rcaBytes(event.detail_json)>65535)return false;const detail=parseRcaJson(event.detail_json);if(supportCanonical(detail)!==event.detail_json||detail.audit_clock_basis!=='legacy_utc_second_storage'||!rcaClock(detail.recorded_at_utc6)||floor(detail.recorded_at_utc6)!==event.create_time)return false;
  if(phase==='usage'){const value={...detail};delete value.recorded_at_utc6;delete value.audit_clock_basis;if(!rcaSame(value,parts.receipt))return false;}
  if(phase==='create'){
   const omitted=new Set(['create_event_id','claim_event_id','claim_lease','claimed_at','dispatch_event_id','dispatched_at','usage_event_id']),artifact=Object.fromEntries(Object.entries(a).filter(([key])=>!omitted.has(key)));
   const header={run_id:v.run_id,feature_key:v.feature_key,provider_id:v.provider_id,provider_revision:v.provider_revision,prompt_version:v.prompt_version,prompt_hash:a.prompt_hash,context_digest:v.context_digest,patient_id:null,encounter_ref:null,requested_by:v.requested_by,preview:v.preview,create_time:v.create_time.slice(0,19),input_hash:a.input_hash,evidence_hash:a.evidence_hash,metadata_hash:a.metadata_hash};
   if(!rcaSame(detail,{schema_version:'rca_evidence_creation_anchor_v1',artifact,run_header_hash:await rcaDigest(header),recorded_at_utc6:a.recorded_at,audit_clock_basis:'legacy_utc_second_storage'}))return false;
  }
  if(phase==='claim'||phase==='dispatch'){
   const expected={schema_version:phase==='claim'?'rca_evidence_claim_audit_v1':'rca_evidence_dispatch_audit_v1',run_id:v.run_id,case_id:a.case_id,requested_by:a.requested_by,create_event_id:a.create_event_id,lease_token:a.claim_lease,source_hash:a.source_hash,binding_hash:a.binding_hash,[phase==='claim'?'claimed_at':'dispatched_at']:phase==='claim'?a.claimed_at:a.dispatched_at,recorded_at_utc6:phase==='claim'?a.claimed_at:a.dispatched_at,audit_clock_basis:'legacy_utc_second_storage',...(phase==='dispatch'?{claim_event_id:a.claim_event_id}:{})};
   if(!rcaSame(detail,expected))return false;
  }
  if(phase==='accept'){
   const r=detail.result,keys=['schema_version','result','create_event_id','claim_event_id','dispatch_event_id','binding_hash','terminal_state_hash','recorded_at_utc6','audit_clock_basis'];
   if(!rcaKeys(detail,keys)||detail.schema_version!=='rca_evidence_accept_audit_v1'||detail.create_event_id!==a.create_event_id||detail.claim_event_id!==a.claim_event_id||detail.dispatch_event_id!==a.dispatch_event_id||detail.binding_hash!==a.binding_hash||detail.terminal_state_hash!==parts.receipt.terminal_state_hash||!rcaKeys(r,['schema_version','run_id','source_hash','instructions_digest','accepted_lease','accepted_at','result_hash','result_bytes'])||r.schema_version!=='rca_evidence_run_result_v1'||r.run_id!==v.run_id||r.source_hash!==a.source_hash||r.instructions_digest!==a.instructions_digest||r.accepted_lease!==a.claim_lease||r.result_hash!==v.result_reference.result_hash||r.result_bytes!==v.result_reference.result_bytes||!rcaClock(r.accepted_at)||r.accepted_at!==detail.recorded_at_utc6)return false;
  }
 }
 return current();
}catch{return false;}}
