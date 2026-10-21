import {supportCanonical as canonical,supportDigest as digest,supportId as uuid,supportHash as hash} from '../inpatientSupport';
import {documentClock,documentUtf8} from './documentEvidence';
import {scalarJsonValue} from './researchCohortOriginalJson';
import {researchCohortRequestValid as requestValid,researchCohortSchemaMatches as schemaMatches,researchCohortBasis as basis} from './researchCohortSources';
import {verifyResearchCapture,evaluateResearchCriteria} from './researchCohortCapture';
import policy from './researchCohortRecipe.json';
const object=v=>v!==null&&typeof v==='object'&&!Array.isArray(v),same=(a,b)=>canonical(a)===canonical(b),keys=(v,n)=>object(v)&&same(Object.keys(v).sort(),[...n].sort()),positive=v=>Number.isSafeInteger(v)&&v>0&&v<=2147483647;
const metadata=['case_id','scope_id','schema_version','created_by','created_at','content_hash','collection_digest','scope_binding_hash','member_manifest_hash','status','revision','reviewed_by','reviewed_at','review_basis_hash','revoked_by','revoked_at','revoke_reason_hash','projection_hash'];
const govKeys=['status','revision','reviewed_by','reviewed_at','review_basis_note','revoked_by','revoked_at','revoke_reason'];
const envelope=[...metadata,'governance_hash','governance','snapshot','public_source','local_resolution','safe_manifest','protected_original_integrity_verified','parent_current','eligible','exclusion_reasons','can_record','can_review','can_revoke','audit_only','access_basis','authorization_limitation'];
const pick=(v,n)=>Object.fromEntries(n.map(k=>[k,v[k]]));
function metadataValid(v){
 if(!uuid(v.case_id)||!uuid(v.scope_id)||v.schema_version!=='research_cohort_case_v1'||!positive(v.created_by)||!documentClock(v.created_at)||!['content_hash','collection_digest','scope_binding_hash','member_manifest_hash','review_basis_hash','revoke_reason_hash'].every(k=>hash(v[k]))||v.projection_hash!==null&&!hash(v.projection_hash)||!['draft','published','rejected','revoked'].includes(v.status))return false;
 const reviewed=v.reviewed_by!==null,revoked=v.revoked_by!==null;
 if(v.status==='draft'?(v.revision!==1||reviewed||revoked):v.status==='revoked'?(!revoked||v.revision!==(reviewed?3:2)):(v.revision!==2||!reviewed||revoked))return false;
 for(const name of ['reviewed','revoked'])if(v[name+'_by']===null?v[name+'_at']!==null:!positive(v[name+'_by'])||!documentClock(v[name+'_at'])||v[name+'_at']<v.created_at)return false;
 return !(reviewed&&revoked&&v.revoked_at<v.reviewed_at)&&!(v.status==='published'&&v.projection_hash===null)&&!(['draft','rejected'].includes(v.status)&&v.projection_hash!==null);
}
export function researchCaseMetadataValid(v){try{return keys(v,[...metadata,'detail_required','no_clinical_body_in_directory'])&&metadataValid(v)&&v.detail_required===true&&v.no_clinical_body_in_directory===true;}catch{return false;}}
export function researchCaseDirectoryValid(v,{scopeId,page=1,size=20}={}){try{return uuid(scopeId)&&keys(v,['items','page','size','total'])&&v.page===page&&v.size===size&&Number.isSafeInteger(page)&&page>=1&&page<=100000&&Number.isSafeInteger(size)&&size>=1&&size<=100&&Number.isSafeInteger(v.total)&&v.total>=0&&Array.isArray(v.items)&&v.items.length===Math.max(0,Math.min(size,v.total-(page-1)*size))&&new Set(v.items.map(r=>r.case_id)).size===v.items.length&&v.items.every(r=>researchCaseMetadataValid(r)&&r.scope_id===scopeId);}catch{return false;}}
export function researchCaseMetadataMatches(row,meta){try{return researchCaseMetadataValid(meta)&&same(pick(row,metadata),pick(meta,metadata));}catch{return false;}}
function governanceValid(row,g){
 if(!keys(g,govKeys)||!same(pick(row,['status','revision','reviewed_by','reviewed_at','revoked_by','revoked_at']),pick(g,['status','revision','reviewed_by','reviewed_at','revoked_by','revoked_at'])))return false;
 return (g.reviewed_by===null?g.review_basis_note==='':basis(g.review_basis_note))&&(g.revoked_by===null?g.revoke_reason==='':basis(g.revoke_reason,1000));
}
async function opaqueFactory(secret,current){
 if(!hash(secret)||!current())throw new Error('科研身份锚无效');const bytes=Uint8Array.from(secret.match(/../gu),v=>parseInt(v,16)),key=await crypto.subtle.importKey('raw',bytes,{name:'HMAC',hash:'SHA-256'},false,['sign']);
 return async(namespace,raw)=>{if(!current())throw new Error('科研核对上下文已变化');const signed=await crypto.subtle.sign('HMAC',key,documentUtf8(canonical([namespace,raw])));if(!current())throw new Error('科研核对上下文已变化');return Array.from(new Uint8Array(signed),v=>v.toString(16).padStart(2,'0')).join('');};
}
async function project(snapshot,publicationHash,current){
 const opaque=await opaqueFactory(snapshot.identity_secret,current),captured=snapshot.capture,manifest=[],outcomes=[];
 for(const m of captured.member_manifest)manifest.push({family:m.family,patient_token:await opaque('patient',m.patient_id),record_token:await opaque('record',[m.family,m.record_id]),original_hash:await opaque('original_hash',m.content_hash),parent_binding_hash:await opaque('parent_binding_hash',m.parent_binding_hash),window_status:m.window_status});
 for(const o of snapshot.evaluation.outcomes){const leaves=[];for(const l of o.leaves){const evidence=[];for(const e of l.evidence)evidence.push({...Object.fromEntries(Object.entries(e).filter(([k])=>!['record_id','original_hash','field_hash'].includes(k))),record_token:await opaque('record',[e.family,e.record_id]),original_hash:await opaque('original_hash',e.original_hash),field_hash:await opaque('field_hash',e.field_hash)});leaves.push({...Object.fromEntries(Object.entries(l).filter(([k])=>k!=='evidence')),evidence});}outcomes.push({patient_token:await opaque('patient',o.patient_id),truth:o.truth,interpretation:o.interpretation,leaves});}
 const counts={declared_patients:outcomes.length,recorded_true:outcomes.filter(v=>v.truth==='true').length,recorded_false:outcomes.filter(v=>v.truth==='false').length,unknown:outcomes.filter(v=>v.truth==='unknown').length};
 const contentHash=await digest(snapshot),result={schema_version:'research_cohort_source_v1',source_id:`research_cohort:${snapshot.case_id}:${contentHash.slice(0,12)}`,content_hash:contentHash,governance_hash:publicationHash,captured_at:snapshot.captured_at,scope_token:await opaque('scope',snapshot.scope_id),authorization_binding_hash:await opaque('authorization_binding',snapshot.scope_binding_hash),collection_digest:await opaque('collection',snapshot.collection_digest),data_families:captured.scope_original.payload.data_families,record_window:captured.scope_original.payload.record_window,member_manifest:manifest,member_manifest_hash:await digest(manifest),recipe:snapshot.recipe,criteria:snapshot.request.criteria,outcomes,counts,limitations:snapshot.evaluation.limitations,privacy_basis:'project_authorized_identifier_minimization_not_anonymity',external_model_use:captured.scope_original.payload.external_model_use};
 return {result,opaque};
}
function safeManifestValid(value){return value===null||Array.isArray(value)&&value.length<=policy.max_roots&&new Set(value.map(v=>v.family+':'+v.record_token)).size===value.length&&value.every(v=>keys(v,['family','record_token','original_hash'])&&Object.hasOwn(policy.family_columns,v.family)&&hash(v.record_token)&&hash(v.original_hash));}
export async function verifyResearchCase(value,{caseId=null,scopeId=null,auditOnly=false,execution=false,allowMetadata=false,current=()=>true}={}){try{
 if(typeof auditOnly!=='boolean'||typeof execution!=='boolean'||!current()||!keys(value,envelope)||!scalarJsonValue(value)||documentUtf8(canonical(value)).length>33554432||!metadataValid(value)||!hash(value.governance_hash)||caseId!==null&&value.case_id!==caseId||scopeId!==null&&value.scope_id!==scopeId||value.audit_only!==auditOnly||value.access_basis!=='current_project_acl_and_each_patient_permission_even_super'||value.authorization_limitation!=='technical_audit_does_not_restore_withdrawn_clinical_body'||value.can_record!==false||!['parent_current','eligible','can_review','can_revoke','protected_original_integrity_verified'].every(k=>typeof value[k]==='boolean')||!Array.isArray(value.exclusion_reasons)||value.exclusion_reasons.some(v=>typeof v!=='string')||new Set(value.exclusion_reasons).size!==value.exclusion_reasons.length||value.eligible!==(value.exclusion_reasons.length===0)||!safeManifestValid(value.safe_manifest))return null;
 if(value.snapshot===null){
  if(!allowMetadata||execution||value.governance!==null||value.public_source!==null||value.local_resolution!==null||value.eligible)return null;
  return current()?{level:'technical_metadata',fullOriginalVerified:false,evaluationReproduced:false,selectable:false}:null;
 }
 const s=value.snapshot;
 if(!keys(s,['schema_version','case_id','scope_id','created_by','captured_at','identity_secret','creation_basis_note','request','capture','collection_digest','scope_binding_hash','member_manifest_hash','recipe','evaluation'])||s.schema_version!==value.schema_version||s.case_id!==value.case_id||s.scope_id!==value.scope_id||s.created_by!==value.created_by||s.captured_at!==value.created_at||!hash(s.identity_secret)||!basis(s.creation_basis_note)||!requestValid('CaptureRequest',s.request)||s.scope_id!==s.request.scope_id||!same(s.recipe,policy.recipe)||documentUtf8(canonical(s)).length>policy.max_bytes||!await verifyResearchCapture(s.capture,{current})||!current())return null;
 const c=s.capture;
 if(!same(pick(s.request,['scope_id','scope_content_hash','scope_governance_hash']),c.request)||s.created_by!==c.actor_id||s.captured_at!==c.captured_at||s.collection_digest!==c.collection_digest||s.member_manifest_hash!==c.manifest_hash||s.scope_binding_hash!==await digest({scope:c.scope_original,acl:c.actor_acl,patient_authorizations:c.patient_authorizations})||!same(pick(s,['collection_digest','member_manifest_hash','scope_binding_hash']),pick(value,['collection_digest','member_manifest_hash','scope_binding_hash']))||await digest(s)!==value.content_hash||!same(s.evaluation,await evaluateResearchCriteria(c,s.request.criteria,{current})))return null;
 const g=value.governance;
 if(!governanceValid(value,g)||await digest(g.review_basis_note)!==value.review_basis_hash||await digest(g.revoke_reason)!==value.revoke_reason_hash||await digest({case_id:value.case_id,content_hash:value.content_hash,governance:g})!==value.governance_hash||!current())return null;
 const opaque=await opaqueFactory(s.identity_secret,current),safe=[],patients=[];
 for(const m of c.member_manifest)safe.push({family:m.family,record_token:await opaque('record',[m.family,m.record_id]),original_hash:await opaque('original_hash',m.content_hash)});
 for(const patient_id of c.scope_original.payload.patient_ids)patients.push({patient_token:await opaque('patient',patient_id),patient_id});
 if(!same(value.safe_manifest,safe)||!same(value.local_resolution,{patients})||!value.protected_original_integrity_verified)return null;
 if(value.projection_hash===null){if(value.public_source!==null||value.status==='published')return null;}
 else{
  if(!['published','revoked'].includes(value.status)||g.reviewed_at===null)return null;
  const publication={...g,status:'published',revision:2,revoked_by:null,revoked_at:null,revoke_reason:''},pubHash=await digest({case_id:value.case_id,content_hash:value.content_hash,governance:publication}),projected=(await project(s,pubHash,current)).result;
  if(!schemaMatches('ResearchCohortSource',value.public_source)||documentUtf8(canonical(value.public_source)).length>policy.max_bytes||!same(projected,value.public_source)||await digest(projected)!==value.projection_hash)return null;
 }
 if(!auditOnly&&(!value.parent_current||!['draft','published'].includes(value.status))||value.eligible&&(!value.parent_current||value.status!=='published')||execution&&(auditOnly||!value.eligible||value.public_source===null))return null;
 return current()?{level:'full_current_recipe',fullOriginalVerified:true,evaluationReproduced:true,selectable:!auditOnly&&value.eligible&&value.public_source!==null}:null;
}catch{return null;}}
export async function verifyResearchPreview(value,request,{current=()=>true}={}){try{
 if(!current()||!keys(value,['schema_version','request','capture','evaluation','expected_collection_digest','can_create','no_business_write'])||value.schema_version!=='research_cohort_preview_v1'||!requestValid('CaptureRequest',request)||!same(request,value.request)||value.can_create!==true||value.no_business_write!==true||documentUtf8(canonical(value)).length>33554432||!await verifyResearchCapture(value.capture,{current})||!same(pick(request,['scope_id','scope_content_hash','scope_governance_hash']),value.capture.request)||value.expected_collection_digest!==value.capture.collection_digest)return false;
 return same(value.evaluation,await evaluateResearchCriteria(value.capture,request.criteria,{current}))&&current();
}catch{return false;}}
// A technical-only transition verifies recorded columns and the submitted basis
// commitment. It never asserts that inaccessible clinical originals were read.
export async function verifyResearchCaseTransition(after,before,action,body,{beforeAuditOnly=false,afterAuditOnly=false,current=()=>true}={}){try{
 if(!['review','revoke'].includes(action)||!requestValid(action==='review'?'SourceReview':'SourceRevoke',body)||body.expected_revision!==before.revision||!current())return null;
 const oldProof=await verifyResearchCase(before,{caseId:before.case_id,auditOnly:beforeAuditOnly,allowMetadata:true,current}),nextProof=await verifyResearchCase(after,{caseId:before.case_id,auditOnly:afterAuditOnly,allowMetadata:true,current});
 if(!oldProof||!nextProof||!current()||!same(pick(before,['case_id','scope_id','schema_version','created_by','created_at','content_hash','collection_digest','scope_binding_hash','member_manifest_hash']),pick(after,['case_id','scope_id','schema_version','created_by','created_at','content_hash','collection_digest','scope_binding_hash','member_manifest_hash'])))return null;
 let g=null;
 if(action==='review'){
  if(before.status!=='draft'||before.revision!==1||after.status!==(body.decision==='publish'?'published':'rejected')||after.revision!==2||!positive(after.reviewed_by)||!documentClock(after.reviewed_at)||after.reviewed_at<before.created_at||after.revoked_by!==null||after.revoked_at!==null||after.review_basis_hash!==await digest(body.basis_note)||after.revoke_reason_hash!==await digest(''))return null;
  g={status:after.status,revision:2,reviewed_by:after.reviewed_by,reviewed_at:after.reviewed_at,review_basis_note:body.basis_note,revoked_by:null,revoked_at:null,revoke_reason:''};
 }else{
  if(!['draft','published'].includes(before.status)||after.status!=='revoked'||after.revision!==before.revision+1||!same(pick(before,['reviewed_by','reviewed_at','review_basis_hash','projection_hash']),pick(after,['reviewed_by','reviewed_at','review_basis_hash','projection_hash']))||!positive(after.revoked_by)||!documentClock(after.revoked_at)||after.revoked_at<(before.reviewed_at||before.created_at)||after.revoke_reason_hash!==await digest(body.basis_note))return null;
  if(before.governance!==null)g={...before.governance,status:'revoked',revision:after.revision,revoked_by:after.revoked_by,revoked_at:after.revoked_at,revoke_reason:body.basis_note};
  else if(before.status==='draft'&&before.review_basis_hash===await digest(''))g={status:'revoked',revision:2,reviewed_by:null,reviewed_at:null,review_basis_note:'',revoked_by:after.revoked_by,revoked_at:after.revoked_at,revoke_reason:body.basis_note};
 }
 if(g!==null&&await digest({case_id:after.case_id,content_hash:after.content_hash,governance:g})!==after.governance_hash||!current())return null;
 if(before.snapshot!==null&&after.snapshot!==null&&!same(before.snapshot,after.snapshot))return null;
 return {level:g!==null?'complete_governance_transition':'technical_governance_columns',fullOriginalVerified:oldProof.fullOriginalVerified&&nextProof.fullOriginalVerified,fullGovernanceVerified:g!==null,basisCommitmentVerified:true,selectable:false};
}catch{return null;}}
