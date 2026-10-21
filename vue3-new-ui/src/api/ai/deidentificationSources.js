import request from '@/utils/request';
import {deidentificationPolicy as policy,deidentificationCanonical as canonical,deidentificationDigest as digest,deidentificationTextHash as textHash,deidentificationId as uuid,deidentificationHash as sha,deidentificationClock as clock,deidentificationBasis as basis,deidentificationRequestValid as requestValid,keys,pick,same,positive,ordered,jsonScalars,bytes,naiveClock,calendar,scalar,deidentificationDocument as document} from './deidentificationCore';
import {verifyDeidentificationAuthority} from './deidentificationAuthority';
export {deidentificationPolicy,deidentificationBasis,deidentificationRequestValid,applyDeidentificationEdits} from './deidentificationCore';
import {applyDeidentificationEdits} from './deidentificationCore';
const BASE='ai/deidentification',MAX=policy.max_bytes,scopeKeys=['scope_id','scope_content_hash','scope_governance_hash','patient_id'];
const bounded=v=>jsonScalars(v)&&bytes(canonical(v))<=MAX;
export const deidentificationScopeValid=v=>requestValid('PatientScopeRequest',v);
function rawValid(family,raw){if(!keys(raw,policy.family_columns[family]||[]))return false;return Object.entries(raw).every(([k,v])=>v===null||({Integer:()=>Number.isSafeInteger(v),Date:()=>calendar(v),DateTime:()=>naiveClock(v),String:()=>scalar(v),Text:()=>scalar(v)})[policy.raw_column_types[family][k]]?.());}
function parentValid(v){return keys(v,['kind','status','technical_hash'])&&scalar(v.kind)&&['patient_bound','unknown_parent','missing_parent','patient_mismatch'].includes(v.status)&&sha(v.technical_hash);}
const manifestValid=e=>keys(e,['family','record_id','original_hash','parent_binding','window_status'])&&Object.hasOwn(policy.family_columns,e.family)&&(typeof e.record_id==='string'&&e.record_id.length>0||e.family==='patient_demographics'&&positive(e.record_id))&&sha(e.original_hash)&&parentValid(e.parent_binding)&&['unknown_clock','recorded_calendar_in_scope'].includes(e.window_status);
async function verifyAuthorities(v,scope,acl,permission){
 const common=['scope_id','schema_version','content_hash','status','revision','created_by','created_at','reviewed_by','reviewed_at','revoked_by','revoked_at','valid_from','valid_until','payload_json_hash','parent_binding_json_hash','review_basis_note_hash','revoke_reason_hash'],seen=new Map(),users=new Set([v.actor_id,scope.identity.created_by]);
 for(const id of [scope.governance.reviewed_by,scope.authorization_review.authorization_reviewed_by])if(id!==null)users.add(id);
 if(!Array.isArray(v.authorization_manifest)||!ordered(v.authorization_manifest.map(x=>[x.kind,x.source_record_id])))return false;
 for(const e of v.authorization_manifest){
  if(!keys(e,['kind','source_record_id','metadata'])||!['acl','authorization'].includes(e.kind)||!uuid(e.source_record_id))return false;
  const r=e.metadata,extra=e.kind==='acl'?['acl_id','user_id','permission']:['authorization_id','patient_id','authorization_kind','access_basis','authorization_review_status','authorization_reviewed_by','authorization_reviewed_at','authorization_review_basis_hash'];
  if(!keys(r,[...common,...extra])||r.scope_id!==scope.identity.scope_id||r[e.kind==='acl'?'acl_id':'authorization_id']!==e.source_record_id||r.schema_version!==(e.kind==='acl'?'research_project_acl_v1':'research_patient_auth_v1')||!positive(r.created_by)||!clock(r.created_at)||!['draft','published','rejected','revoked'].includes(r.status)||!Number.isSafeInteger(r.revision))return false;
  if(r.status==='draft'?r.revision!==1:['published','rejected'].includes(r.status)?r.revision!==2:![2,3].includes(r.revision))return false;
  for(const[k,x]of Object.entries(r)){if(k.endsWith('_hash')&&!sha(x))return false;if((k.endsWith('_at')||['valid_from','valid_until'].includes(k))&&x!==null&&!clock(x))return false;}
  for(const k of ['created_by','reviewed_by','revoked_by','authorization_reviewed_by','user_id','patient_id'])if(Object.hasOwn(r,k)&&r[k]!==null){if(!positive(r[k]))return false;if(k!=='patient_id')users.add(r[k]);}
  if(e.kind==='acl'?!['read_only','read_capture'].includes(r.permission):!['permission_recorded','waiver_recorded','unknown','withdrawn','denied'].includes(r.authorization_kind)||!['explicit_project_acl','current_care_or_grant'].includes(r.access_basis)||!['unknown','recorded_reviewed','not_confirmed'].includes(r.authorization_review_status))return false;
  seen.set(e.kind+':'+e.source_record_id,r);
 }
 const gov=['status','revision','reviewed_by','reviewed_at','revoked_by','revoked_at'];
 for(const[k,p]of [['acl',acl],['authorization',permission]]){
  const r=seen.get(k+':'+p.identity.source_record_id);if(!r)return false;
  const expected=Object.fromEntries(Object.entries(p.identity).filter(([k])=>!['source_kind','source_record_id'].includes(k)));
  expected[k==='acl'?'acl_id':'authorization_id']=p.identity.source_record_id;
  Object.assign(expected,pick(p.governance,gov),{content_hash:p.content_hash,payload_json_hash:await textHash(canonical(p.payload)),parent_binding_json_hash:await textHash(canonical(p.parent_binding)),review_basis_note_hash:await textHash(p.governance.review_basis_note),revoke_reason_hash:await textHash(p.governance.revoke_reason)});
  if(k==='authorization'){Object.assign(expected,pick(p.authorization_review,['authorization_review_status','authorization_reviewed_by','authorization_reviewed_at']));expected.authorization_review_basis_hash=await textHash(p.authorization_review.authorization_review_basis);}
  if(!same(r,expected))return false;
 }
 if(!Array.isArray(v.authority_actors)||!ordered(v.authority_actors.map(a=>a.user_id))||!same(v.authority_actors.map(a=>a.user_id),[...users].sort((a,b)=>a-b)))return false;
 for(const a of v.authority_actors)if(!keys(a,['user_id','exists','role','token_invalid_before'])||!positive(a.user_id)||typeof a.exists!=='boolean'||(a.exists?typeof a.role!=='string'||!a.role||Array.from(a.role).length>64||a.token_invalid_before!==null&&!naiveClock(a.token_invalid_before):a.role!==null||a.token_invalid_before!==null))return false;
 return 3+v.member_manifest.length+v.authorization_manifest.length+v.authority_actors.length<=policy.max_roots;
}
export async function verifyDeidentificationCapture(v,{current=()=>true}={}){try{
 if(!current()||!keys(v,['schema_version','purpose','request','actor_id','scope_original','actor_acl','patient_authorization','authorization_manifest','authority_actors','supported_columns','member_manifest','selected_originals','selected_documents','manifest_hash','captured_at','collection_digest'])||!bounded(v)||v.schema_version!=='deidentification_capture_v1'||v.purpose!=='deidentification_review'||!requestValid('CaptureRequest',v.request)||!positive(v.actor_id)||!clock(v.captured_at))return false;
 const s=v.scope_original,a=v.actor_acl,p=v.patient_authorization,r=v.request;
 for(const[k,x]of [['scope',s],['acl',a],['authorization',p]])if(!await verifyDeidentificationAuthority(x,{kind:k,current}))return false;
 if(!same([r.scope_id,r.scope_content_hash,r.scope_governance_hash],[s.identity.scope_id,s.content_hash,s.governance_hash])||!s.payload.permitted_uses.includes('deidentification_review')||!s.payload.patient_ids.includes(r.patient_id)||a.identity.user_id!==v.actor_id||a.identity.permission!=='read_capture'||p.identity.patient_id!==r.patient_id||!same(a.parent_binding.scope,s)||!same(p.parent_binding.scope,s))return false;
 for(const x of [s,a,p])if(x.governance.status!=='published'||x.governance.reviewed_at>v.captured_at||x.identity.valid_from===null||!(x.identity.valid_from<=v.captured_at&&v.captured_at<x.identity.valid_until))return false;
 if(!['permission_recorded','waiver_recorded'].includes(p.identity.authorization_kind)||p.authorization_review.authorization_review_status!=='recorded_reviewed'||s.authorization_review.authorization_review_status!=='recorded_reviewed'||!same(v.supported_columns,Object.fromEntries(s.payload.data_families.map(f=>[f,policy.family_columns[f]]))))return false;
 if(!Array.isArray(v.member_manifest)||v.member_manifest.length>policy.max_roots||!v.member_manifest.every(manifestValid)||!v.member_manifest.every(e=>Object.hasOwn(v.supported_columns,e.family))||!ordered(v.member_manifest.map(e=>[e.family,e.record_id]))||await digest(v.member_manifest)!==v.manifest_hash)return false;
 if(s.payload.data_families.includes('patient_demographics')&&!same(v.member_manifest.filter(e=>e.family==='patient_demographics').map(e=>e.record_id),[r.patient_id]))return false;
 const manifest=new Map(v.member_manifest.map(e=>[canonical([e.family,e.record_id]),e])),originals=new Map();
 if(!Array.isArray(v.selected_originals)||!Array.isArray(v.selected_documents)||v.selected_documents.length!==r.documents.length)return false;
 for(const e of v.selected_originals){const key=canonical([e.family,e.record_id]),raw=e.original;if(!keys(e,['family','record_id','original_hash','parent_binding','window_status','original'])||!rawValid(e.family,raw)||originals.has(key)||!same(pick(e,['family','record_id','original_hash','parent_binding','window_status']),manifest.get(key))||raw.patient_id!==r.patient_id||raw[policy.family_keys[e.family]]!==e.record_id||await digest(raw)!==e.original_hash)return false;originals.set(key,e);}
 if(!same([...originals.keys()].sort(),[...new Set(r.documents.map(d=>canonical([d.family,d.record_id])))].sort()))return false;
 for(const[index,selected]of r.documents.entries()){
  const e=originals.get(canonical([selected.family,selected.record_id])),raw=e.original,parentKind=selected.family==='medical_records'?'registration_uuid':selected.family==='structured_medical_records'?'admission_id':'direct_patient_fk';
  const expectedParent={kind:parentKind,status:'patient_bound',technical_hash:await digest(parentKind==='direct_patient_fk'?{patient_id:r.patient_id}:{[parentKind]:raw[parentKind],exists:true,patient_id:r.patient_id})};
  const clockValue=raw[policy.family_clocks[selected.family]],w=s.payload.record_window;
  if(!s.payload.data_families.includes(selected.family)||!naiveClock(clockValue)||clockValue.slice(0,10)<w.date_from||clockValue.slice(0,10)>w.date_to||!same(e.parent_binding,expectedParent)||e.window_status!=='recorded_calendar_in_scope'||e.original_hash!==selected.expected_original_hash||!same(v.selected_documents[index],{locator:selected,document:await document('selected_document:'+index,selected.field,raw[selected.field])}))return false;
 }
 if(!await verifyAuthorities(v,s,a,p)||!current())return false;
 return await digest(Object.fromEntries(Object.entries(v).filter(([k])=>!['captured_at','collection_digest'].includes(k))))===v.collection_digest&&current();
}catch{return false;}}
export async function verifyDeidentificationSnapshot(v,{current=()=>true}={}){try{
 if(!keys(v,['schema_version','case_id','scope_id','patient_id','created_by','recorded_at','capture','basis_note','limitations'])||!bounded(v)||v.schema_version!=='deidentification_case_v1'||!uuid(v.case_id)||!uuid(v.scope_id)||!positive(v.patient_id)||!positive(v.created_by)||!clock(v.recorded_at)||!basis(v.basis_note)||!same(v.limitations,policy.limitations)||!await verifyDeidentificationCapture(v.capture,{current}))return false;
 return current()&&same([v.scope_id,v.patient_id,v.created_by,v.recorded_at],[v.capture.request.scope_id,v.capture.request.patient_id,v.capture.actor_id,v.capture.captured_at]);
}catch{return false;}}
export async function projectDeidentificationSnapshot(snapshot,metadata){
 if(metadata.case_id!==snapshot.case_id||await digest(snapshot)!==metadata.content_hash)throw new Error('原件和投影锚不符');
 const docs=[];for(const[i,v]of snapshot.capture.selected_documents.entries())docs.push(await document(`deid_document:${snapshot.case_id}:${i}`,v.document.field,v.document.text));
 const v={schema_version:'deidentification_public_source_v1',source_id:metadata.source_id,source_content_hash:metadata.content_hash,source_governance_hash:metadata.governance_hash,documents:docs,coverage:'complete_selected_fields_only',original_time_basis:'legacy_naive_calendar_dates_timezone_unknown',limitations:[...policy.limitations],anonymity_guaranteed:false};
 if(!bounded(v))throw new Error('完整投影超限');return v;
}
const metaKeys=['schema_version','case_id','source_id','scope_id','recorded_at','content_hash','collection_digest','parent_binding_hash','manifest_hash','status','revision','governance_hash','detail_required'];
function statusValid(v){return v.status==='draft'?v.revision===1:['published','rejected'].includes(v.status)?v.revision===2:v.status==='revoked'&&[2,3].includes(v.revision);}
export function deidentificationMetadataValid(v,scope=null){return keys(v,metaKeys)&&v.schema_version==='deidentification_case_metadata_v1'&&uuid(v.case_id)&&uuid(v.scope_id)&&clock(v.recorded_at)&&['content_hash','collection_digest','parent_binding_hash','manifest_hash','governance_hash'].every(k=>sha(v[k]))&&statusValid(v)&&v.detail_required===true&&v.source_id===`deidentification_case:${v.case_id}:${v.content_hash.slice(0,12)}`&&(scope===null||v.scope_id===scope.scope_id);}
export async function verifyDeidentificationSource(v,{scope=null,auditOnly=false,current=()=>true}={}){try{
 if(!current()||!keys(v,[...metaKeys,'snapshot','public_source','current','eligible','audit_only','can_review','can_revoke','exclusion_reasons','proof_scope'])||!bounded(v)||!deidentificationMetadataValid(pick(v,metaKeys),scope)||v.audit_only!==auditOnly||!['current','eligible','can_review','can_revoke'].every(k=>typeof v[k]==='boolean')||v.eligible!==(v.current&&v.status==='published'&&!auditOnly)||v.can_review&&(auditOnly||!v.current||v.status!=='draft')||v.can_revoke&&!['draft','published'].includes(v.status))return false;
 if(v.proof_scope==='safe_metadata_and_opaque_hashes_only')return v.snapshot===null&&v.public_source===null&&auditOnly&&!v.current&&!v.can_review&&same(v.exclusion_reasons,['current_project_patient_purpose_not_authorized']);
 if(v.proof_scope!=='complete_selected_originals_and_opaque_nonselected_manifest'||!same(v.exclusion_reasons,[...(!v.current?['whole_collection_or_original_authority_changed']:[]),...(v.status!=='published'?['source_not_published']:[])]))return false;
 if(v.snapshot===null)return v.public_source===null&&!auditOnly&&!(v.current&&['draft','published'].includes(v.status));
 const s=v.snapshot;if(!await verifyDeidentificationSnapshot(s,{current})||s.case_id!==v.case_id||s.scope_id!==v.scope_id||s.recorded_at!==v.recorded_at||scope!==null&&!same(pick(s.capture.request,scopeKeys),scope)||await digest(s)!==v.content_hash||v.collection_digest!==s.capture.collection_digest||v.manifest_hash!==s.capture.manifest_hash||await digest(pick(s.capture,['scope_original','actor_acl','patient_authorization']))!==v.parent_binding_hash)return false;
 // Own Source governance includes undisclosed audit notes. Its SHA is an opaque
 // server anchor; only the fully visible immutable Source and projection recur.
 return same(await projectDeidentificationSnapshot(s,v),v.public_source)&&current();
}catch{return false;}}
export function deidentificationFieldsValid(v,scope){try{return keys(v,['schema_version','request','items','complete','collection_digest','limitations'])&&bounded(v)&&v.schema_version==='deidentification_choices_v1'&&same(v.request,scope)&&deidentificationScopeValid(scope)&&v.complete===true&&sha(v.collection_digest)&&same(v.limitations,policy.limitations)&&Array.isArray(v.items)&&new Set(v.items.map(e=>canonical([e.family,e.record_id,e.field]))).size===v.items.length&&v.items.every(e=>keys(e,['family','record_id','original_hash','parent_binding','window_status','field','text_state','utf8_bytes','codepoint_length'])&&manifestValid(pick(e,['family','record_id','original_hash','parent_binding','window_status']))&&policy.text_fields[e.family]?.includes(e.field)&&['not_recorded','recorded_empty','recorded'].includes(e.text_state)&&(e.text_state==='not_recorded'?e.utf8_bytes===null&&e.codepoint_length===null:Number.isSafeInteger(e.utf8_bytes)&&e.utf8_bytes>=0&&Number.isSafeInteger(e.codepoint_length)&&e.codepoint_length>=0&&e.utf8_bytes>=e.codepoint_length&&(e.text_state==='recorded_empty'?e.utf8_bytes===0&&e.codepoint_length===0:e.utf8_bytes>0&&e.codepoint_length>0)));}catch{return false;}}
export function deidentificationDirectoryValid(v,scope){return keys(v,['schema_version','items','total','complete','detail_required'])&&v.schema_version==='deidentification_case_directory_v1'&&Array.isArray(v.items)&&v.items.length<=policy.max_roots&&v.total===v.items.length&&v.complete===true&&v.detail_required===true&&ordered(v.items.map(e=>e.case_id))&&v.items.every(e=>deidentificationMetadataValid(e,scope));}
export async function verifyDeidentificationPreview(v,request,{current=()=>true}={}){return keys(v,['schema_version','capture','expected_collection_digest','can_create','no_business_write'])&&v.schema_version==='deidentification_preview_v1'&&v.can_create===true&&v.no_business_write===true&&same(v.capture.request,request)&&v.expected_collection_digest===v.capture.collection_digest&&await verifyDeidentificationCapture(v.capture,{current})&&current();}
const childMeta=['schema_version','content_hash','governance_hash','status','revision','recorded_at','manual_status','detail_required'];
function childMetadata(v,kind){return v.schema_version===`deidentification_${kind}_metadata_v1`&&uuid(v[kind+'_id'])&&uuid(v[kind==='review'?'case_id':'review_id'])&&sha(v.content_hash)&&sha(v.governance_hash)&&clock(v.recorded_at)&&statusValid(v)&&v.detail_required===true&&['unknown','reviewed_residual_risk_remains','not_confirmed'].includes(v.manual_status);}
function flags(v,kind,auditOnly){return v.audit_only===auditOnly&&['current','eligible','can_manual_review','can_review','can_revoke'].every(k=>typeof v[k]==='boolean')&&(!v.eligible||v.current&&v.status==='published'&&v.manual_status==='reviewed_residual_risk_remains'&&!auditOnly)&&(!v.can_manual_review||v.current&&v.status==='draft'&&v.manual_status==='unknown'&&!auditOnly)&&(!v.can_review||v.current&&v.status==='draft'&&!auditOnly)&&(!v.can_revoke||['draft','published'].includes(v.status)&&!auditOnly)&&v.anonymity_guaranteed===false&&same(v.limitations,policy.limitations);}
function manualValid(v,original,kind){if(v===null)return original.manual_status==='unknown';return keys(v,['request','actor','recorded_at'])&&requestValid(kind==='review'?'ResidualReview':'ReleaseAuthorityReview',v.request)&&v.request.expected_revision===1&&v.request.expected_content_hash===original.content_hash&&v.request.decision===original.manual_status&&keys(v.actor,['user_id','user_role','token_invalid_before'])&&positive(v.actor.user_id)&&policy.source_roles.includes(v.actor.user_role)&&(v.actor.token_invalid_before===null||clock(v.actor.token_invalid_before))&&v.actor.user_id!==original.original.created_by&&clock(v.recorded_at)&&v.recorded_at>=original.recorded_at;}
async function publishedSource(source,binding){if(!keys(binding,['case_id','content_hash','governance_hash','collection_digest','projection_hash'])||binding.case_id!==source.case_id||binding.content_hash!==source.content_hash||binding.collection_digest!==source.collection_digest||!sha(binding.governance_hash)||!sha(binding.projection_hash))return null;const p=await projectDeidentificationSnapshot(source.snapshot,{...source,governance_hash:binding.governance_hash});return await digest(p)===binding.projection_hash?p:null;}
export async function verifyDeidentificationReview(v,source,{auditOnly=false,current=()=>true}={}){try{
 if(!keys(v,[...childMeta,'review_id','case_id','original','output','manual_review','current','eligible','audit_only','can_manual_review','can_review','can_revoke','limitations','anonymity_guaranteed'])||!bounded(v)||!childMetadata(v,'review')||!flags(v,'review',auditOnly)||v.case_id!==source.case_id||!await verifyDeidentificationSource(source,{auditOnly:source.audit_only,current}))return false;
 if(v.original===null)return v.output===null&&v.manual_review===null&&!v.eligible&&!v.can_manual_review&&!v.can_review;
 const o=v.original;if(!source.snapshot||!keys(o,['schema_version','review_id','case_id','created_by','recorded_at','source_binding','request','output_hash','output_bytes','limitations'])||o.schema_version!=='deidentification_review_v1'||o.review_id!==v.review_id||o.case_id!==v.case_id||!positive(o.created_by)||o.recorded_at!==v.recorded_at||!requestValid('ReviewCreate',o.request)||o.request.case_id!==v.case_id||o.request.expected_content_hash!==source.content_hash||o.request.expected_governance_hash!==o.source_binding.governance_hash||!same(o.limitations,policy.limitations)||await digest(o)!==v.content_hash)return false;
 const p=await publishedSource(source,o.source_binding);if(p===null)return false;
 const output=await applyDeidentificationEdits(p.documents,o.request.edits);if(!same(output,v.output)||await digest(output)!==o.output_hash||bytes(canonical(output))!==o.output_bytes||!manualValid(v.manual_review,v,'review'))return false;
 return current()&&(!v.current||source.eligible)&&(!v.can_manual_review||v.manual_review===null);
}catch{return false;}}
export async function verifyDeidentificationRelease(v,review,source,{auditOnly=false,current=()=>true}={}){try{
 if(!keys(v,[...childMeta,'release_id','review_id','original','artifact','manual_review','current','eligible','audit_only','download_count','maximum_downloads','valid_from','valid_until','can_manual_review','can_review','can_revoke','limitations','anonymity_guaranteed'])||!bounded(v)||!childMetadata(v,'release')||!flags(v,'release',auditOnly)||v.review_id!==review.review_id||!Number.isSafeInteger(v.download_count)||v.download_count<0||!Number.isSafeInteger(v.maximum_downloads)||v.maximum_downloads<1||v.maximum_downloads>100||v.download_count>v.maximum_downloads||[v.valid_from,v.valid_until].some(t=>t!==null&&!clock(t))||!await verifyDeidentificationReview(review,source,{auditOnly:review.audit_only,current}))return false;
 if(v.original===null)return v.artifact===null&&v.manual_review===null&&!v.eligible&&!v.can_manual_review&&!v.can_review;
 const o=v.original,r=o.request,b=o.review_binding;
 if(!keys(o,['schema_version','release_id','review_id','created_by','recorded_at','review_binding','request','artifact_hash','artifact_bytes','limitations'])||o.schema_version!=='deidentification_release_v1'||o.release_id!==v.release_id||o.review_id!==v.review_id||!positive(o.created_by)||o.recorded_at!==v.recorded_at||!requestValid('ReleaseCreate',r)||r.review_id!==v.review_id||r.expected_content_hash!==review.content_hash||r.expected_governance_hash!==b.governance_hash||!keys(b,['review_id','content_hash','governance_hash','output_hash','manual_review_hash'])||b.review_id!==review.review_id||b.content_hash!==review.content_hash||!sha(b.governance_hash)||b.output_hash!==review.original?.output_hash||b.manual_review_hash!==await textHash(canonical(review.manual_review))||!same(pick(r,['valid_from','valid_until','maximum_downloads']),pick(v,['valid_from','valid_until','maximum_downloads']))||!same(o.limitations,policy.limitations)||await digest(o)!==v.content_hash)return false;
 const artifact={schema_version:'deidentification_single_export_v1',release_id:v.release_id,review_id:v.review_id,source_id:source.source_id,source_content_hash:source.content_hash,review_content_hash:review.content_hash,selected_output_hash:await digest(review.output),documents:review.output.documents,coverage:'complete_explicitly_selected_output_only',limitations:[...policy.limitations],anonymity_guaranteed:false};
 return same(artifact,v.artifact)&&await digest(artifact)===o.artifact_hash&&bytes(canonical(artifact))===o.artifact_bytes&&manualValid(v.manual_review,v,'release')&&(!v.current||review.eligible)&&(!v.eligible||v.download_count<v.maximum_downloads)&&current();
}catch{return false;}}
const id=v=>{if(!uuid(v))throw new Error('明确原件标识无效');return v;};
const read=(url,params)=>request({url:BASE+url,method:'get',params,retry:0});
const write=(url,data,model)=>{if(!requestValid(model,data))throw new Error('完整75输入、逐字位置或明确依据不符');return request({url:BASE+url,method:'post',data:JSON.stringify(data),headers:{'Content-Type':'application/json'},retry:0});};
export const getDeidentificationFields=data=>write('/fields',data,'PatientScopeRequest');
export const getDeidentificationCases=data=>write('/cases/directory',data,'PatientScopeRequest');
export const previewDeidentificationCase=data=>write('/cases/preview',data,'CaptureRequest');
export const createDeidentificationCase=data=>write('/cases',data,'CaseCreate');
export const getDeidentificationCase=(value,{audit_only=false}={})=>read('/cases/'+id(value),{audit_only});
export const reviewDeidentificationCase=(value,data)=>write('/cases/'+id(value)+'/review',data,'GovernanceReview');
export const revokeDeidentificationCase=(value,data)=>write('/cases/'+id(value)+'/revoke',data,'GovernanceRevoke');
export const createDeidentificationReview=data=>write('/reviews',data,'ReviewCreate');
export const getDeidentificationReview=(value,{audit_only=false}={})=>read('/reviews/'+id(value),{audit_only});
export const residualDeidentificationReview=(value,data)=>write('/reviews/'+id(value)+'/residual-review',data,'ResidualReview');
export const publishDeidentificationReview=(value,data)=>write('/reviews/'+id(value)+'/review',data,'GovernanceReview');
export const revokeDeidentificationReview=(value,data)=>write('/reviews/'+id(value)+'/revoke',data,'GovernanceRevoke');
export const createDeidentificationRelease=data=>write('/releases',data,'ReleaseCreate');
export const getDeidentificationRelease=(value,{audit_only=false}={})=>read('/releases/'+id(value),{audit_only});
export const authorityDeidentificationRelease=(value,data)=>write('/releases/'+id(value)+'/authority-review',data,'ReleaseAuthorityReview');
export const publishDeidentificationRelease=(value,data)=>write('/releases/'+id(value)+'/review',data,'GovernanceReview');
export const revokeDeidentificationRelease=(value,data)=>write('/releases/'+id(value)+'/revoke',data,'GovernanceRevoke');
export const downloadDeidentificationRelease=value=>request({url:BASE+'/releases/'+id(value)+'/download',method:'post',data:'{}',headers:{'Content-Type':'application/json'},responseType:'arraybuffer',retry:0});
export async function verifyDeidentificationDownload(raw,release,review,source,{current=()=>true}={}){try{
 if(!current()||!await verifyDeidentificationRelease(release,review,source,{auditOnly:false,current})||!release.eligible||release.original===null)return false;
 const wire=raw instanceof ArrayBuffer?new Uint8Array(raw):raw;if(!(wire instanceof Uint8Array)||wire.length>MAX||await textHash(wire)!==release.original.artifact_hash||!current())return false;
 const text=new TextDecoder('utf-8',{fatal:true,ignoreBOM:true}).decode(wire),value=JSON.parse(text);
 return bounded(value)&&canonical(value)===text&&same(value,release.artifact)&&current();
}catch{return false;}}
export function deidentificationTransitionValid(after,before,action,body){
 const kind=before.review_id&&before.schema_version==='deidentification_review_metadata_v1'?'review':before.release_id?'release':'case',idKey=kind+'_id';
 if(after[idKey]!==before[idKey]||after.content_hash!==before.content_hash||body.expected_content_hash!==before.content_hash||body.expected_revision!==before.revision)return false;
 if(action==='manual')return before.status==='draft'&&before.revision===1&&after.status==='draft'&&after.revision===1&&before.manual_status==='unknown'&&after.manual_status===body.decision&&same(after.manual_review?.request,body);
 return ['review','revoke'].includes(action)&&after.revision===before.revision+1&&after.status===(action==='revoke'?'revoked':body.decision==='publish'?'published':'rejected');
}
