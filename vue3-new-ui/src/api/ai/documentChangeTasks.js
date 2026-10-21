import {supportCanonical as canonical,supportDigest as digest,supportId as uuid,supportHash as hash} from '../inpatientSupport';
import {documentUtf8,documentClock} from './documentEvidence';
import {verifyDocumentChangeScope,getDocumentChangeScope} from './documentChanges';
import {documentChangeTaskInputValid,verifyDocumentChangeContext,documentChangeEvidence,verifyDocumentChangeRun,getDocumentChangeRun,getDocumentChangeTrace,getDocumentChangeRunPiece} from './documentChangeResults';
const object=v=>v!==null&&typeof v==='object'&&!Array.isArray(v),same=(a,b)=>canonical(a)===canonical(b),keys=(v,n)=>object(v)&&same(Object.keys(v).sort(),n.split(',').sort()),positive=v=>Number.isSafeInteger(v)&&v>0&&v<=2147483647;
export function documentChangeInitialInputValid(v){try{return object(v)&&[Object.prototype,null].includes(Object.getPrototypeOf(v))&&Object.keys(v).every(k=>['document_change_scope_id','question'].includes(k))&&(!Object.hasOwn(v,'document_change_scope_id')||uuid(v.document_change_scope_id))&&(!Object.hasOwn(v,'question')||v.question===null||typeof v.question==='string'&&Array.from(v.question).length<=2000&&documentUtf8(v.question).length<=8000);}catch{return false;}}
export async function verifyDocumentChangePreview(value,input,scope,source,{current=()=>true}={}){try{
 if(!current()||!documentChangeTaskInputValid(input)||!keys(value,'context,metadata,evidence,document_change_source_reference,model_preview_scope')||!scope?.eligible||!await verifyDocumentChangeScope(scope,{current})||input.document_change_scope_id!==scope.snapshot.scope_id||!await verifyDocumentChangeContext(value.context,source,{scope,current}))return false;
 const ctx=value.context,b=ctx.document_change_binding,m={snapshot_time:ctx.snapshot_time,source_count:3,department_ids:[],context_digest:await digest(ctx),clinical_context_fingerprint:await digest(Object.fromEntries(Object.entries(ctx).filter(([key])=>key!=='snapshot_time'))),missing_data:ctx.missing_data};
 return current()&&same(value.metadata,m)&&same(value.evidence,documentChangeEvidence(b))&&same(value.document_change_source_reference,{scope_id:b.scope.scope_id,source_digest:b.source_digest})&&value.model_preview_scope==='complete_public_source_plus_question_only;provider_whole_wire_budget_checked_before_queue';
}catch{return false;}}
export function documentChangeReceiptValid(v,{scopeId,runId=null,preview=null}={}){try{
 if(!object(v)||!uuid(v.run_id)||runId!==null&&v.run_id!==runId||v.feature_key!=='guideline_change_review'||!uuid(scopeId)||v.document_change_scope_id!==scopeId||v.patient_id!==null||v.encounter_ref!==null||v.requires_human_review!==true||!['queued','running','succeeded','failed','cancelled'].includes(v.status)||!Number.isSafeInteger(v.preview)||![0,1].includes(v.preview)||preview!==null&&v.preview!==Number(preview)||!Number.isSafeInteger(v.prompt_version)||v.prompt_version<0||!positive(v.provider_revision)||!hash(v.context_digest))return false;
 const m=v.context_metadata,u=v.usage_receipt,token=n=>n===null||Number.isSafeInteger(n)&&n>=0&&n<=2000000;
 return keys(m,'snapshot_time,source_count,department_ids,context_digest,clinical_context_fingerprint,missing_data,feature_revision,validation_status,tool_fingerprint,instructions_digest,model_version')&&documentClock(m.snapshot_time)&&m.context_digest===v.context_digest&&m.source_count===3&&same(m.department_ids,[])&&Array.isArray(m.missing_data)&&m.missing_data.length===3&&m.missing_data.every(s=>typeof s==='string')&&hash(m.clinical_context_fingerprint)&&hash(m.tool_fingerprint)&&hash(m.instructions_digest)&&positive(m.feature_revision)&&['unreviewed','pilot','validated','suspended'].includes(m.validation_status)&&typeof m.model_version==='string'&&m.model_version.length>0&&keys(u,'input_tokens,output_tokens,complete,model_call_attempted')&&token(u.input_tokens)&&token(u.output_tokens)&&typeof u.complete==='boolean'&&u.complete===(u.input_tokens!==null&&u.output_tokens!==null)&&[null,true,false].includes(u.model_call_attempted)&&v.input_tokens===u.input_tokens&&v.output_tokens===u.output_tokens&&Object.entries(v).every(([k,x])=>!k.endsWith('_findings')||k==='document_change_findings'||x===null);
}catch{return false;}}
export async function readVerifiedDocumentChangeTask(runId,{selectedScope,receipt=null,expectedInput=null,preview=null,current=()=>true}={}){
 if(!current()||!uuid(runId)||!selectedScope?.eligible||!await verifyDocumentChangeScope(selectedScope,{current}))throw new Error('当前有限范围未完整核对');
 const scopeId=selectedScope.snapshot.scope_id;
 // Reads may observe worker progress between endpoints. At most three fresh
 // read sets are allowed; no POST or provider execution is retried.
 for(let attempt=0;attempt<3;attempt++){
  const [r,t,s,p,l]=await Promise.all([getDocumentChangeRun(runId),getDocumentChangeTrace(runId),getDocumentChangeRunPiece(runId,'source'),getDocumentChangeRunPiece(runId,'scope'),getDocumentChangeScope(scopeId)]);if(!current())return null;
  const run=r.data,trace=t.data,liveScope=l.data;
  if(!documentChangeReceiptValid(run,{scopeId,runId,preview})||!documentChangeReceiptValid(trace,{scopeId,runId,preview})||receipt&&(run.context_digest!==receipt.context_digest||run.prompt_version!==receipt.prompt_version||run.provider_revision!==receipt.provider_revision)||expectedInput!==null&&!same(trace.frozen_request?.payload?.input,expectedInput)||run.context_digest!==trace.context_digest||!same(run.document_change_findings,trace.document_change_findings)||!same(run.context_metadata,trace.context_metadata))throw new Error('返回任务、范围、冻结提交或短回执不符');
  if(!liveScope?.eligible||liveScope.content_hash!==selectedScope.content_hash||liveScope.governance_hash!==selectedScope.governance_hash)throw new Error('当前原件或治理已变化');
  if(run.status!==trace.status||!same(run.usage_receipt,trace.usage_receipt))continue;
  const result=run.status==='succeeded'?(await getDocumentChangeRunPiece(runId,'result')).data:null;if(!current())return null;
  const bundle={run,trace,source:s.data,scope:p.data,result};
  if(!await verifyDocumentChangeRun(bundle,{runId,scopeId,liveScope,current}))throw new Error('完整冻结任务、逐字证明或实际原件核对失败');
  return current()?{bundle,liveScope}:null;
 }
 throw new Error('任务状态仍在变化，请手动重新读取；未自动重试提交');
}
