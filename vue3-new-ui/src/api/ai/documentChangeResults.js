import request from '@/utils/request';
import packed from './documentChangeResultSchemas.json';
import fixed from './documentChangeFixed.json';
import {decodeGeneratedSchemas,generatedSchemaMatches} from '../sofaSchema';
import {supportCanonical as canonical,supportDigest as digest,supportId as uuid,supportHash as hash} from '../inpatientSupport';
import {documentUtf8,documentBytesHash,documentClock,documentCodepointSlice} from './documentEvidence';
import {parseDocumentFrozenJson} from './documentExtractionResults';
import {verifyDocumentChangeScope,verifyDocumentChangeSource,projectDocumentChangeScope} from './documentChanges';

const models=decodeGeneratedSchemas(packed),MAX=fixed.max_wire_bytes,FEATURE='guideline_change_review';
const object=v=>v!==null&&typeof v==='object'&&!Array.isArray(v),own=(v,k)=>object(v)&&Object.hasOwn(v,k),same=(a,b)=>canonical(a)===canonical(b),keys=(v,names)=>object(v)&&same(Object.keys(v).sort(),names.split(',').filter(Boolean).sort());
const blanks=/[\u0009-\u000d\u001c-\u0020\u0085\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000]/gu;
const meaningful=(v,maxBytes=8000)=>typeof v==='string'&&v.replace(blanks,'').length>0&&documentUtf8(v).length<=maxBytes;
const bytes=v=>documentUtf8(typeof v==='string'?v:canonical(v)).length,positive=v=>Number.isSafeInteger(v)&&v>0&&v<=2147483647,current=o=>!o.current||o.current()===true;
function bounded(v){return bytes({code:200,msg:'success',data:v})<=MAX;}
function tree(v){let nodes=0;const active=new Set();function walk(x,d){if(++nodes>2101248||d>32)throw new Error('完整资料结构超限');if(x===null||typeof x==='boolean')return;if(typeof x==='string'){documentUtf8(x);return;}if(typeof x==='number'){if(!Number.isFinite(x)||Number.isInteger(x)&&!Number.isSafeInteger(x))throw new Error('数值不精确');return;}if(typeof x!=='object'||active.has(x)||!Array.isArray(x)&&![Object.prototype,null].includes(Object.getPrototypeOf(x)))throw new Error('非JSON资料');active.add(x);if(Array.isArray(x))x.forEach(y=>walk(y,d+1));else for(const[k,y]of Object.entries(x)){if(['__proto__','prototype','constructor'].includes(k))throw new Error('原型键');documentUtf8(k);walk(y,d+1);}active.delete(x);}walk(v,0);return bounded(v);}
export function documentChangeResultSchemaMatches(name,value){try{return tree(value)&&generatedSchemaMatches(models,name,value);}catch{return false;}}
export const documentChangeCoverageNote=fixed.coverage_note;
export const documentChangeRunStates=Object.freeze({queued:'排队中',running:'运行中',succeeded:'草稿已生成',failed:'运行失败',cancelled:'已取消'});
const targetKey=t=>t.kind+':'+String(t.target_id),scopeSourceId=s=>`document_change_scope:${s.scope.scope_id}:${s.scope.content_hash.slice(0,12)}`,originalSourceId=o=>`document_original:${o.original.original_id}:${o.original.content_hash.slice(0,12)}`;
export async function documentChangeBindingForSource(source){return {schema_version:'document_change_binding_v1',feature_key:FEATURE,scope:source.scope,baseline_original:source.baseline.original,candidate_original:source.candidate.original,inventory_hash:source.inventory_hash,member_count:source.member_count,source_digest:await digest(source)};}
export function documentChangeEvidence(binding){return [{source_id:`document_change_scope:${binding.scope.scope_id}:${binding.scope.content_hash.slice(0,12)}`,kind:'document_change_scope',...binding.scope,source_digest:binding.source_digest,inventory_hash:binding.inventory_hash,member_count:binding.member_count},...['baseline','candidate'].map(side=>({source_id:`document_original:${binding[side+'_original'].original_id}:${binding[side+'_original'].content_hash.slice(0,12)}`,kind:'document_original',side,...binding[side+'_original']}))];}
export async function verifyDocumentChangeContext(context,source,{scope=null,...options}={}){try{
 if(!current(options)||!documentChangeResultSchemaMatches('DocumentChangeContext',context)||!documentClock(context.snapshot_time)||!same(context.missing_data,fixed.missing_data)||!await verifyDocumentChangeSource(source,{scope,...options})||!same(context.document_change_binding,await documentChangeBindingForSource(source)))return false;
 return current(options)&&(!scope||context.snapshot_time>=scope.governance.reviewed_at);
}catch{return false;}}
export async function verifyDocumentChangePrivatePacket(packet,source,options={}){try{
 if(!current(options)||!documentChangeResultSchemaMatches('DocumentChangePrivateScopePacket',packet))return false;
 const b=packet.document_change_binding,g=packet.published_governance,s=packet.scope_snapshot;
 if(!same(b,await documentChangeBindingForSource(source))||s.scope_id!==b.scope.scope_id||await digest(s)!==b.scope.content_hash||g.status!=='published'||await digest(g)!==b.scope.governance_hash||!same(s.request.baseline_original,b.baseline_original)||!same(s.request.candidate_original,b.candidate_original)||s.inventory_hash!==b.inventory_hash||s.inventory.member_count!==b.member_count)return false;
 // Reconstruct only the task-time immutable check input. These derived flags
 // are never a live-current claim or a substitute for a fresh Scope response.
 const frozen={schema_version:'document_change_scope_record_v1',snapshot:s,governance:g,content_hash:b.scope.content_hash,governance_hash:b.scope.governance_hash,audit_event_ids:packet.published_audit_event_ids,inventory_current:true,eligible:true,ineligibility_reasons:[],automatic_supersession:false,hospital_wide_rule_inventory:'not_provided',clinical_validation:'not_provided'};
 return current(options)&&await verifyDocumentChangeScope(frozen,options)&&same(await projectDocumentChangeScope(frozen),source);
}catch{return false;}}
export async function verifyDocumentChangeResult(result,source,instructionsDigest,options={}){try{
 if(!current(options)||!hash(instructionsDigest)||!documentChangeResultSchemaMatches('DocumentChangeGenerationResult',result)||!await verifyDocumentChangeSource(source,options))return false;
 const draft=result.document_change,expectedBinding={scope_id:source.scope.scope_id,scope_content_hash:source.scope.content_hash,scope_governance_hash:source.scope.governance_hash,source_projection_hash:await digest(source),instructions_digest:instructionsDigest};
 if(!same(draft.binding,expectedBinding)||draft.requires_human_review!==true||draft.automatic_changes!==false||draft.coverage!==fixed.coverage)return false;
 const targets=new Map(source.targets.map(t=>[targetKey(t.target),t]));let overlaps=0;
 for(const change of draft.changes){
  if(!meaningful(change.review_note)||!meaningful(change.clarification_question)||Array.from(change.review_note).length>2000||Array.from(change.clarification_question).length>2000)return false;
  const baseline=change.baseline_spans.length>0,candidate=change.candidate_spans.length>0;
  if(change.kind==='paired_wording_question'&&!(baseline&&candidate)||change.kind==='baseline_excerpt_question'&&(!baseline||candidate)||change.kind==='candidate_excerpt_question'&&(baseline||!candidate))return false;
  for(const side of ['baseline','candidate']){const spans=change[side+'_spans'],seen=new Set();for(const span of spans){const key=canonical(span);if(seen.has(key)||span.start>=span.end||span.end>source[side].codepoint_length||bytes(span.quote)>65535||documentCodepointSlice(source[side].text,span.start,span.end)!==span.quote)return false;seen.add(key);}}
  const expected=[];let used=0;
  for(const link of source.rule_links){const side=link.original.original_id===source.baseline.original.original_id?'baseline':'candidate',ordinals=change[side+'_spans'].flatMap((span,index)=>span.start<link.end&&link.start<span.end?[index]:[]);if(!ordinals.length)continue;
   const witness={link,target:targets.get(targetKey(link.target)),baseline_span_ordinals:side==='baseline'?ordinals:[],candidate_span_ordinals:side==='candidate'?ordinals:[],meaning:fixed.overlap_note};
   used+=bytes(witness)+2;if(used>MAX)return false;expected.push(witness);
  }
  if(!same(change.link_overlaps,expected))return false;overlaps+=expected.length;
 }
 const explanation=JSON.parse(JSON.stringify(fixed.explanation));explanation.summary=explanation.summary.replace('{count}',String(draft.changes.length)).replace('{overlaps}',String(overlaps));explanation.sections[0].source_ids=[scopeSourceId(source),originalSourceId(source.baseline),originalSourceId(source.candidate)];explanation.sections[1].source_ids=[scopeSourceId(source)];if(source.rule_link_coverage==='complete_within_declared_scope')explanation.missing_data.pop();
 return current(options)&&same(result,{...explanation,document_change:draft});
}catch{return false;}}
function legacyClock(v){if(v===null)return true;if(typeof v!=='string'||!/^\d{4}-\d\d-\d\d[T ]\d\d:\d\d:\d\d(?:\.\d{6})?$/u.test(v))return false;return documentClock(v.replace(' ','T')+(v.includes('.')?'Z':'.000000Z'));}
function usage(run){const u=run.usage_receipt,token=v=>v===null||Number.isSafeInteger(v)&&v>=0&&v<=2000000;if(!keys(u,'input_tokens,output_tokens,complete,model_call_attempted')||!token(u.input_tokens)||!token(u.output_tokens)||typeof u.complete!=='boolean'||![null,true,false].includes(u.model_call_attempted)||u.complete!==(u.input_tokens!==null&&u.output_tokens!==null)||run.input_tokens!==u.input_tokens||run.output_tokens!==u.output_tokens)return false;
 if(u.model_call_attempted===false&&!(u.complete&&u.input_tokens===0&&u.output_tokens===0))return false;
 if(!['pending','recorded','interrupted'].includes(run.usage_receipt_status)||run.usage_receipt_status==='pending'&&(u.complete||u.model_call_attempted!==null))return false;
 return run.status!=='succeeded'||u.complete&&u.model_call_attempted===true;
}
function basics(run,id){return tree(run)&&object(run)&&uuid(id)&&run.run_id===id&&run.feature_key===FEATURE&&run.patient_id===null&&run.encounter_ref===null&&run.requires_human_review===true&&Object.hasOwn(documentChangeRunStates,run.status)&&[0,1].includes(run.preview)&&Number.isSafeInteger(run.prompt_version)&&run.prompt_version>=0&&positive(run.provider_revision)&&hash(run.context_digest)&&uuid(run.document_change_scope_id)&&run.split_artifacts===true&&usage(run)&&['create_time','start_time','finish_time'].every(k=>legacyClock(run[k]))&&Object.entries(run).every(([key,value])=>!key.endsWith('_findings')||key==='document_change_findings'||value===null);}
export function documentChangeRunHasMarkers(v){try{
 if(!object(v))return false;if(v.feature_key===FEATURE||['document_change_scope_id','document_change_findings','document_change_artifact'].some(k=>own(v,k)))return true;
 const context=v.frozen_request?.payload?.context,input=v.frozen_request?.payload?.input;
 return Boolean([v.context_metadata?.selected_sources,context?.selected_sources,input].some(x=>own(x,'document_change_scope_id'))||[context,v.document_change_findings].some(x=>x?.scope==='document_change_review'||own(x,'document_change_binding'))||v.operational_findings?.source_domain==='document_change_review'||v.result?.schema_version==='document_change_result_ref_v1'||own(v.result,'document_change')||v.evidence?.some?.(e=>e?.kind==='document_change_scope'));
}catch{return true;}}
export async function verifyDocumentChangeRun(bundle,{runId=bundle?.run?.run_id,scopeId=null,liveScope=null,auditOnly=false,...options}={}){try{
 if(typeof auditOnly!=='boolean'||!current(options)||!object(bundle))return false;
 const {run,trace,source:sp,scope:privateScope,result:rp=null}=bundle;
 if(!basics(run,runId)||!basics(trace,runId)||trace.snapshot_complete!==true||!positive(trace.requested_by)||!positive(trace.provider_id)||!documentChangeResultSchemaMatches('DocumentChangeSourcePacket',sp)||sp.run_id!==runId||privateScope?.run_id!==runId)return false;
 for(const[k,value]of Object.entries(run))if(!same(value,trace[k]))return false;
 const source=sp.document_change_source,b=sp.document_change_binding,ctx=run.document_change_findings,a=run.document_change_artifact,m=run.context_metadata,f=trace.frozen_request;
 if(!await verifyDocumentChangePrivatePacket(privateScope,source,options)||!await verifyDocumentChangeContext(ctx,source,options)||!same(b,privateScope.document_change_binding)||!same(b,ctx.document_change_binding)||run.document_change_scope_id!==b.scope.scope_id||scopeId!==null&&scopeId!==b.scope.scope_id)return false;
 if(!auditOnly&&(!liveScope||!liveScope.eligible||!await verifyDocumentChangeScope(liveScope,options)||!same(source,await projectDocumentChangeScope(liveScope))))return false;
 if(!documentChangeResultSchemaMatches('DocumentChangeArtifactRecord',a)||a.run_id!==runId||a.requested_by!==trace.requested_by||!same(a.document_change_binding,b)||a.recorded_at<ctx.snapshot_time||a.source_bytes!==bytes(source)||!same([a.scope_created_audit_event_id,a.scope_review_audit_event_id],[privateScope.published_audit_event_ids.created,privateScope.published_audit_event_ids.reviewed]))return false;
 const auditIds=[a.scope_created_audit_event_id,a.scope_review_audit_event_id,a.created_audit_event_id,...(a.usage_event_id===null?[]:[a.usage_event_id])];if(new Set(auditIds).size!==auditIds.length||run.usage_receipt_status==='recorded'&&a.usage_event_id===null||run.usage_receipt_status==='pending'&&a.usage_event_id!==null)return false;
 if(!keys(f,'catalog_version,system_prompt,task_prompt,payload,provider_snapshot,feature_validation')||typeof f.catalog_version!=='string'||f.system_prompt!==fixed.system_prompt||!meaningful(f.task_prompt,65535)||!keys(f.payload,'input,context,tools,evidence')||!same(f.payload.context,ctx)||!same(f.payload.tools,{}))return false;
 const input=f.payload.input,p=f.provider_snapshot,v=f.feature_validation;
 if(!documentChangeResultSchemaMatches('DocumentChangeRequest',input)||input.document_change_scope_id!==b.scope.scope_id||input.question!==undefined&&input.question!==null&&bytes(input.question)>8000||!documentChangeResultSchemaMatches('DocumentFrozenProvider',p)||p.allows_patient_data!==true||p.effective_output_limit>p.max_output_tokens||p.provider_id!==trace.provider_id||p.revision!==run.provider_revision||!documentChangeResultSchemaMatches('DocumentFrozenValidation',v)||!legacyClock(v.validated_at)||(v.validated_at===null)!==(v.validated_by===null))return false;
 const ev=documentChangeEvidence(b),contextDigest=await digest(ctx),instructions=await documentBytesHash(f.system_prompt+'\n\n'+f.task_prompt),expectedMetadata={snapshot_time:ctx.snapshot_time,source_count:3,department_ids:[],context_digest:contextDigest,clinical_context_fingerprint:await digest(Object.fromEntries(Object.entries(ctx).filter(([key])=>key!=='snapshot_time'))),missing_data:fixed.missing_data,feature_revision:v.feature_revision,validation_status:v.status,tool_fingerprint:await digest({}),instructions_digest:instructions,model_version:p.model};
 if(!same(m,expectedMetadata)||!same(run.evidence,ev)||!same(f.payload.evidence,ev)||run.context_digest!==contextDigest||a.context_digest!==contextDigest||a.prompt_hash!==await digest([f.system_prompt,f.task_prompt]))return false;
 for(const[raw,parsed,expected]of [[trace.frozen_request_json,f,a.input_hash],[trace.frozen_evidence_json,ev,a.evidence_hash],[trace.frozen_context_metadata_json,m,a.metadata_hash]])if(!same(parseDocumentFrozenJson(raw),parsed)||await documentBytesHash(raw)!==expected)return false;
 if(run.status==='succeeded'){
  const ref=run.result;if(!documentChangeResultSchemaMatches('DocumentChangeResultReference',ref)||ref.run_id!==runId||ref.scope_id!==b.scope.scope_id||ref.source_binding_hash!==await digest(b)||auditIds.includes(ref.accept_audit_event_id)||!documentChangeResultSchemaMatches('DocumentChangeResultPacket',rp)||rp.run_id!==runId||!same(rp.document_change_binding,b)||rp.instructions_digest!==instructions||!await verifyDocumentChangeResult(rp.result,source,instructions,options)||await digest(rp.result)!==ref.content_hash||bytes(rp.result)!==ref.result_bytes)return false;
 }else if(!keys(run.result,'')||rp!==null)return false;
 return current(options);
}catch{return false;}}
function id(v){if(!uuid(v))throw new Error('需要明确规范任务UUID');return v;}
const get=(url,params)=>request({url,method:'get',params,retry:0});
export const getDocumentChangeRun=runId=>get(`ai/runs/${id(runId)}`);
export const getDocumentChangeTrace=runId=>get(`ai/admin/runs/${id(runId)}`);
export function getDocumentChangeRunPiece(runId,kind,{auditOnly=false}={}){if(typeof auditOnly!=='boolean'||!['source','scope','result'].includes(kind))throw new Error('独立原件类型不合法');return get(`ai/${auditOnly?'admin/':''}runs/${id(runId)}/document-change/${kind}`);}
export function getDocumentChangeRunHistory(scopeId,{auditOnly=false}={}){if(typeof auditOnly!=='boolean')throw new Error('审计模式须明确');return get(`ai/${auditOnly?'admin/':''}runs`,{feature_key:FEATURE,document_change_scope_id:id(scopeId)});}
export function documentChangeTaskInputValid(input){try{return object(input)&&[Object.prototype,null].includes(Object.getPrototypeOf(input))&&Object.keys(input).every(k=>['document_change_scope_id','question'].includes(k))&&uuid(input.document_change_scope_id)&&(input.question===undefined||input.question===null||typeof input.question==='string'&&Array.from(input.question).length<=2000&&bytes(input.question)<=8000);}catch{return false;}}
export function previewDocumentChange(input){if(!documentChangeTaskInputValid(input))throw new Error('仅接受范围ID与原样问题');return request({url:'ai/document-change/context',method:'post',data:JSON.stringify(input),headers:{'Content-Type':'application/json'},retry:0});}
export function submitDocumentChange(input,preview){if(!documentChangeTaskInputValid(input)||typeof preview!=='boolean')throw new Error('范围或显式预览状态无效');return request({url:'ai/runs',method:'post',data:JSON.stringify({feature_key:FEATURE,input,preview}),headers:{'Content-Type':'application/json'},retry:0});}
export const cancelDocumentChange=runId=>request({url:`ai/runs/${id(runId)}/cancel`,method:'post',retry:0});
export function feedbackDocumentChange(runId,outcome,comment=''){if(!['accepted','modified','rejected'].includes(outcome)||typeof comment!=='string'||Array.from(comment).length>2000||documentUtf8(comment).length>8000)throw new Error('反馈字段不合法');return request({url:`ai/runs/${id(runId)}/feedback`,method:'post',data:JSON.stringify({outcome,comment}),headers:{'Content-Type':'application/json'},retry:0});}
