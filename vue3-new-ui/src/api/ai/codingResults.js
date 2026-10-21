import registry from './codingResultSchemas.json';
import fixed from './codingFixedPolicy.json';
import {decodeGeneratedSchemas,generatedSchemaMatches} from '../sofaSchema';
import {supportCanonical as canonical,supportDigest as digest,supportHash as hash,supportId as uuid} from '../inpatientSupport';
import {codingCaseReferencesValid,verifyCodingEvidenceFrozenCase} from './codingEvidence';

const schemas=decodeGeneratedSchemas(registry),object=v=>v!==null&&typeof v==='object'&&!Array.isArray(v),same=(a,b)=>canonical(a)===canonical(b);
const keys=(v,n)=>object(v)&&same(Object.keys(v).sort(),[...n].sort()),pick=(v,n)=>Object.fromEntries(n.map(k=>[k,v[k]]));
const bytes=v=>new TextEncoder().encode(canonical(v)).length,positive=v=>Number.isSafeInteger(v)&&v>0&&v<=2147483647;
const scalar=s=>typeof s==='string'&&!/[\uD800-\uDBFF](?![\uDC00-\uDFFF])|(?<![\uD800-\uDBFF])[\uDC00-\uDFFF]/u.test(s);
const current=o=>!o.current||o.current();
const rawDigest=async text=>Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',new TextEncoder().encode(text))),b=>b.toString(16).padStart(2,'0')).join('');
export const codingSchemaMatches=(name,value)=>generatedSchemaMatches(schemas,name,value);
export function codingClock(v){try{return typeof v==='string'&&/^[1-9]\d{3}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{6}Z$/.test(v)&&new Date(v.slice(0,23)+'Z').toISOString()===v.slice(0,23)+'Z';}catch{return false;}}
function expectedScope(b,e){return(e.patientId==null||positive(e.patientId)&&b.patient_id===e.patientId)&&(e.admissionId==null||uuid(e.admissionId)&&b.admission_id===e.admissionId)&&(e.homeId==null||uuid(e.homeId)&&b.home_id===e.homeId)&&(e.references==null||codingCaseReferencesValid(e.references)&&e.references.coding_case_id===b.case_snapshot_id);}
function shortContext(b,time){return{scope:'patient',source_domain:'single_home_coding_evidence',department_ids:b.department_ids,selected_sources:{coding_case_id:b.case_snapshot_id},coding_binding:b,scope_note:fixed.scope_note,missing_data:fixed.context_missing,truncated_sources:[],snapshot_time:time};}
const originalEvidence=b=>({source_id:b.source_id,kind:'clinical_record',title:'单次住院完整病案编码原件及最小化引文投影',content:canonical({coding_binding:b})});

export async function verifyCodingContext(packet,expected={},options={}){try{
 const minimal=['coding_binding','coding_source','coding_case'],full=[...minimal,...Object.keys(shortContext({},''))].filter((v,i,a)=>a.indexOf(v)===i);
 if(!current(options)||(!keys(packet,minimal)&&!keys(packet,full))||bytes(packet)>3*8388608||!codingSchemaMatches('CodingContextBinding',packet.coding_binding))return false;
 const b=packet.coding_binding,s=packet.coding_source,c=packet.coding_case;
 if(!expectedScope(b,expected)||b.source_id!==`coding_case:${b.case_snapshot_id}:${b.content_hash.slice(0,12)}`||!codingClock(b.captured_at)||!await verifyCodingEvidenceFrozenCase(c,{patientId:b.patient_id,admissionId:b.admission_id,homeId:b.home_id})||!current(options))return false;
 if(c.status!=='published'&&options.auditOnly!==true||c.case_snapshot_id!==b.case_snapshot_id||c.content_hash!==b.content_hash||c.source_id!==b.source_id||c.projection_hash!==b.projection_hash||c.collection_digest!==b.collection_digest||!same(c.public_source,s)||await digest(s)!==b.projection_hash)return false;
 const collection=c.snapshot.collection,department=collection.admission_binding.department_id;
 if(collection.manifest_hash!==b.manifest_hash||collection.captured_at!==b.captured_at||s.case_publication_governance_hash!==b.publication_governance_hash||await digest(s.policy)!==b.policy_hash||!same(b.department_ids,department===null?[]:[department]))return false;
 if(Object.hasOwn(packet,'scope')&&(!codingClock(packet.snapshot_time)||!same(pick(packet,Object.keys(shortContext(b,packet.snapshot_time))),shortContext(b,packet.snapshot_time))))return false;
 return current(options);
}catch{return false;}}

export async function verifyCodingDraft(draft,source,projectionHash,options={}){try{
 if(!current(options)||!codingSchemaMatches('CodingEvidenceDraft',draft)||bytes(draft)>8388608||draft.source_id!==source.source_id||draft.source_projection_hash!==projectionHash||!Array.isArray(source.code_bindings)||source.code_bindings.length>4096||!Array.isArray(source.documents)||source.documents.length>16)return false;
 const bindings=source.code_bindings.map(r=>r.binding_token),claims=draft.claims.map(r=>r.binding_token);
 if(new Set(bindings).size!==bindings.length||new Set(claims).size!==claims.length||!same([...bindings].sort(),[...claims].sort()))return false;
 const documents=new Map();
 for(const d of source.documents){if(!current(options)||documents.has(d.source_id)||!scalar(d.text)||await rawDigest(d.text)!==d.text_hash)return false;documents.set(d.source_id,d);}
 for(const claim of draft.claims){
  if(!current(options)||!scalar(claim.review_note)||!claim.review_note.trim()||claim.clarification_question!==null&&(!scalar(claim.clarification_question)||!claim.clarification_question.trim())||['support_claim','conflict_claim'].includes(claim.model_assessment)&&!claim.citations.length||claim.model_assessment==='clarification_requested'&&claim.clarification_question===null)return false;
  const seen=new Set();
  for(const citation of claim.citations){const d=documents.get(citation.document_source_id),identity=canonical([citation.document_source_id,citation.start,citation.end]);if(!d||seen.has(identity)||!scalar(citation.quote)||citation.end<=citation.start||citation.text_hash!==d.text_hash||citation.end>Array.from(d.text).length||Array.from(d.text).slice(citation.start,citation.end).join('')!==citation.quote)return false;seen.add(identity);}
 }
 return current(options);
}catch{return false;}}

function explanation(source,draft){
 const rows=source.code_bindings,primary=rows.filter(r=>r.kind==='diagnosis'&&Number.isSafeInteger(r.is_primary)&&r.is_primary===1).length,unknownPrimary=rows.filter(r=>!Number.isSafeInteger(r.is_primary)||![0,1].includes(r.is_primary)).length,unknownKind=rows.filter(r=>!['diagnosis','operation'].includes(r.kind)).length;
 const assessed={support_claim:0,conflict_claim:0,insufficient_evidence:0,clarification_requested:0};for(const claim of draft.claims)assessed[claim.model_assessment]++;
 return{summary:`已形成${rows.length}项已记录编码的待复核模型意见，尚未作临床或编码确认。`,sections:[{title:'完整记录结构',content:`本件共有${rows.length}项绑定；其中明确记录的主诊断标记${primary}项，未知或无效主诊断标记${unknownPrimary}项，未知编码类型${unknownKind}项。记录数量和标记不证明编码正确或文书支持。`,source_ids:[source.source_id]},{title:'模型主张分布，均待人工核实',content:`模型主张支持${assessed.support_claim}项、冲突${assessed.conflict_claim}项、证据不足${assessed.insufficient_evidence}项、需澄清${assessed.clarification_requested}项。请逐项查看原文投影引文及待核实问题。`,source_ids:[source.source_id]}],warnings:fixed.output_warnings,missing_data:[...fixed.output_missing,...source.missing_document_fields.map(k=>'病案文书字段未记录：'+k)]};
}

export async function verifyCodingRun(run,expected={},options={}){try{
 if(!object(run)||!uuid(run.run_id)||run.feature_key!=='drg_evidence_review'||!['queued','running','succeeded','failed','cancelled'].includes(run.status)||!positive(run.patient_id)||!uuid(run.encounter_ref)||!hash(run.context_digest)||!object(run.result)||Object.keys(run).some(k=>k.endsWith('_findings')&&!['coding_findings','tool_findings'].includes(k)&&run[k]!==undefined&&run[k]!==null)||!keys(run.tool_findings,[]))return false;
 const packet=run.coding_findings||run.frozen_request?.payload?.context;
 if(!await verifyCodingContext(packet,{...expected,patientId:expected.patientId??run.patient_id,admissionId:expected.admissionId??run.encounter_ref},options))return false;
 const b=packet.coding_binding,m=run.context_metadata;
 if(run.patient_id!==b.patient_id||run.encounter_ref!==b.admission_id||!keys(m,['context_digest','clinical_context_fingerprint','tool_fingerprint','source_count','department_ids','missing_data','snapshot_time','feature_revision','validation_status','instructions_digest','model_version'])||!hash(m.instructions_digest)||!scalar(m.model_version)||!m.model_version||!codingClock(m.snapshot_time)||!positive(m.feature_revision)||m.source_count!==1||!['unreviewed','pilot','validated','suspended'].includes(m.validation_status)||m.context_digest!==run.context_digest||!same(m.department_ids,b.department_ids)||!same(m.missing_data,fixed.context_missing))return false;
 const short=shortContext(b,m.snapshot_time);
 if(await digest(short)!==run.context_digest||await digest(Object.fromEntries(Object.entries(short).filter(([k])=>k!=='snapshot_time')))!==m.clinical_context_fingerprint||await digest({})!==m.tool_fingerprint||!same(run.evidence,[originalEvidence(b)]))return false;
 if(run.frozen_request){
  const f=run.frozen_request,p=f.payload;
  if(!codingSchemaMatches('CodingFrozenProvider',f.provider_snapshot)||!codingSchemaMatches('CodingFrozenValidation',f.feature_validation)||f.provider_snapshot.effective_output_limit>f.provider_snapshot.max_output_tokens)return false;
  const validatedAt=f.feature_validation.validated_at;
  if(validatedAt!==null){if(!/^\d{4}-\d\d-\d\d \d\d:\d\d:\d\d(?:\.\d{6})?$/.test(validatedAt))return false;const parsed=validatedAt.replace(' ','T'),millis=parsed.includes('.')?parsed.slice(0,23):parsed+'.000';if(new Date(millis+'Z').toISOString()!==millis+'Z')return false;}
  if(!keys(f,['catalog_version','system_prompt','task_prompt','payload','provider_snapshot','feature_validation'])||!p||!keys(p,['context','input','tools','evidence'])||!object(p.input)||Object.keys(p.input).some(k=>!['coding_case_id','question'].includes(k))||p.input.coding_case_id!==b.case_snapshot_id||Object.hasOwn(p.input,'question')&&(!scalar(p.input.question)||Array.from(p.input.question).length>12000)||!keys(p.tools,[])||!same(p.evidence,run.evidence)||!await verifyCodingContext(p.context,expected,options)||!same(p.context.coding_binding,b)||!same(pick(p.context,Object.keys(short)),short)||typeof f.system_prompt!=='string'||typeof f.task_prompt!=='string'||await rawDigest(f.system_prompt)!==fixed.system_prompt_digest||await rawDigest(f.system_prompt+'\n\n'+f.task_prompt)!==m.instructions_digest||f.provider_snapshot?.model!==m.model_version||f.provider_snapshot?.revision!==run.provider_revision||f.provider_snapshot?.provider_id!==run.provider_id||run.snapshot_complete!==true||f.feature_validation?.feature_revision!==m.feature_revision||f.feature_validation?.status!==m.validation_status)return false;
 }
 if(run.status!=='succeeded')return keys(run.result,[])&&current(options);
 if(!codingSchemaMatches('CodingGenerationResult',run.result)||bytes(run.result)>8388608||!await verifyCodingDraft(run.result.coding_analysis,packet.coding_source,b.projection_hash,options))return false;
 return same(Object.fromEntries(Object.entries(run.result).filter(([k])=>k!=='coding_analysis')),explanation(packet.coding_source,run.result.coding_analysis))&&current(options);
}catch{return false;}}

export function verifyCodingReceipt(receipt,full){try{
 const anchors=['run_id','feature_key','patient_id','encounter_ref','context_digest','context_metadata','provider_revision','prompt_version','preview'];
 return object(receipt)&&object(full)&&uuid(receipt.run_id)&&receipt.feature_key==='drg_evidence_review'&&anchors.every(k=>same(receipt[k],full[k]))&&['queued','running','succeeded','failed','cancelled'].includes(receipt.status)&&(!['succeeded','failed','cancelled'].includes(receipt.status)||receipt.status===full.status);
}catch{return false;}}
export function codingRunHasMarkers(run){const has=(v,k)=>object(v)&&Object.hasOwn(v,k),contexts=[run?.frozen_request?.payload?.context,run?.operational_findings];return run?.feature_key==='drg_evidence_review'||has(run,'coding_findings')||has(run?.result,'coding_analysis')||contexts.some(c=>object(c)&&(['coding_binding','coding_source','coding_case'].some(k=>has(c,k))||c.source_domain==='single_home_coding_evidence'||has(c.selected_sources,'coding_case_id')))||has(run?.frozen_request?.payload?.input,'coding_case_id');}
export async function resolveCodingEvidence(evidence,packet,expected={},options={}){try{if(!await verifyCodingContext(packet,expected,options)||!same(evidence,originalEvidence(packet.coding_binding)))return null;return{...evidence,content:JSON.stringify({coding_binding:packet.coding_binding,coding_case:packet.coding_case},null,2)};}catch{return null;}}
