import {supportCanonical as canonical,supportDigest as digest,supportId as uuid,supportHash as hash} from '../inpatientSupport';
import {documentClock,documentUtf8} from './documentEvidence';
import {scalarJsonValue} from './researchCohortOriginalJson';
import {researchCohortBasis as basis,researchCohortRequestValid as requestValid} from './researchCohortSources';

const object=v=>v!==null&&typeof v==='object'&&!Array.isArray(v),same=(a,b)=>canonical(a)===canonical(b);
const keys=(v,n)=>object(v)&&same(Object.keys(v).sort(),[...n].sort()),pick=(v,n)=>Object.fromEntries(n.map(k=>[k,v[k]]));
const positive=v=>Number.isSafeInteger(v)&&v>0&&v<=2147483647;
const IDENTITY=['source_kind','source_record_id','scope_id','schema_version','created_by','created_at','valid_from','valid_until'];
const GOV=['status','revision','reviewed_by','reviewed_at','review_basis_note','revoked_by','revoked_at','revoke_reason'];
const MANUAL=['authorization_review_status','authorization_reviewed_by','authorization_reviewed_at','authorization_review_basis'];
const PROOF=['schema_version','identity','payload','parent_binding','content_hash','governance','authorization_review','governance_hash'];
const definitions={scope:{kind:'study_scope',schema:'research_study_scope_v1',proof:'research_scope_original_proof_v1',model:'ScopeCreate',prefix:'scope',extra:[]},acl:{kind:'acl',schema:'research_project_acl_v1',proof:'research_registry_original_proof_v1',model:'ProjectACLCreate',prefix:'acl',extra:['user_id','permission']},authorization:{kind:'authorization',schema:'research_patient_auth_v1',proof:'research_registry_original_proof_v1',model:'PatientAuthorizationCreate',prefix:'authorization',extra:['patient_id','authorization_kind','access_basis']}};
function governance(identity,g,manual){
 if(!keys(g,GOV)||!['draft','published','rejected','revoked'].includes(g.status))return false;
 const reviewed=g.reviewed_by!==null,revoked=g.revoked_by!==null;
 if(g.status==='draft'?(g.revision!==1||reviewed||revoked):g.status==='revoked'?(!revoked||g.revision!==(reviewed?3:2)):(g.revision!==2||!reviewed||revoked))return false;
 for(const [prefix,present]of [['reviewed',reviewed],['revoked',revoked]]){
  const by=g[prefix+'_by'],at=g[prefix+'_at'],note=g[prefix==='reviewed'?'review_basis_note':'revoke_reason'];
  if(present?(!positive(by)||!documentClock(at)||at<identity.created_at||!basis(note,prefix==='revoked'?1000:4000)):(at!==null||note!==''))return false;
 }
 if(reviewed&&revoked&&g.revoked_at<g.reviewed_at)return false;
 if(manual===null)return identity.source_kind==='acl';
 if(!keys(manual,MANUAL))return false;
 const state=manual.authorization_review_status,by=manual.authorization_reviewed_by,at=manual.authorization_reviewed_at,note=manual.authorization_review_basis;
 if(state==='unknown')return by===null&&at===null&&note==='';
 return ['recorded_reviewed','not_confirmed'].includes(state)&&positive(by)&&by!==identity.created_by&&documentClock(at)&&at>=identity.created_at&&(!reviewed||at<=g.reviewed_at)&&basis(note);
}
async function verifyProof(value,kind,current){
 const d=definitions[kind];if(!d||!current()||!keys(value,PROOF)||value.schema_version!==d.proof||!scalarJsonValue(value)||documentUtf8(canonical(value)).length>8388608)return false;
 const {identity:i,payload:p,parent_binding:parent,governance:g,authorization_review:manual}=value;
 if(!keys(i,[...IDENTITY,...d.extra])||i.source_kind!==d.kind||i.schema_version!==d.schema||!uuid(i.source_record_id)||!uuid(i.scope_id)||!positive(i.created_by)||!documentClock(i.created_at)||!requestValid(d.model,p)||i.valid_from!==p.valid_from||i.valid_until!==p.valid_until||!governance(i,g,manual))return false;
 if(kind==='scope'){
  if(i.source_record_id!==i.scope_id||!keys(parent,['declared_patients','declared_users'])||!same(parent,{declared_patients:p.patient_ids.map(patient_id=>({patient_id})),declared_users:p.proposed_user_ids.map(user_id=>({user_id}))}))return false;
 }else{
  if(!keys(parent,['scope','subject'])||!await verifyProof(parent.scope,'scope',current)||!current())return false;
  const s=parent.scope;if(s.governance.status!=='published'||s.governance.reviewed_at>i.created_at||p.scope_id!==s.identity.scope_id||p.scope_id!==i.scope_id||p.scope_content_hash!==s.content_hash||p.scope_governance_hash!==s.governance_hash)return false;
  if(kind==='acl'?(i.user_id!==p.user_id||i.permission!==p.permission||!same(parent.subject,{user_id:p.user_id})||!s.payload.proposed_user_ids.includes(p.user_id)):(i.patient_id!==p.patient_id||i.authorization_kind!==p.authorization_kind||i.access_basis!==p.access_basis||!same(parent.subject,{patient_id:p.patient_id})||!s.payload.patient_ids.includes(p.patient_id)))return false;
 }
 if(!hash(value.content_hash)||!hash(value.governance_hash)||await digest({identity:i,payload:p,parent_binding:parent})!==value.content_hash||!current())return false;
 return await digest({governance:g,authorization_review:manual})===value.governance_hash&&current();
}
export async function verifyResearchRegistryProof(value,{kind='scope',current=()=>true}={}){try{return await verifyProof(value,kind,current);}catch{return false;}}

// A technical/redacted response is deliberately a separate outcome. Its opaque
// hashes cannot reconstruct private notes, assert complete governance, or make
// the object a selectable clinical source.
export async function verifyResearchRegistryRecord(value,{kind='scope',expectedId=null,auditOnly=false,allowRedacted=false,current=()=>true}={}){try{
 const d=definitions[kind];if(!d||!current()||!object(value)||!scalarJsonValue(value)||documentUtf8(canonical(value)).length>8388608)return null;
 const names=[...IDENTITY,...d.extra,'source_id','content_hash',...GOV,'governance_hash','original','parent_current','eligible','exclusion_reasons','can_record','can_authorization_review','can_review','can_revoke','audit_only','eligibility_basis',...(kind==='scope'?[...MANUAL,'authorization_reviewer_current']:['authorization_review'])];
 if(!keys(value,names)||value.source_kind!==d.kind||value.schema_version!==d.schema||!uuid(value.source_record_id)||!uuid(value.scope_id)||expectedId!==null&&value.source_record_id!==expectedId||!documentClock(value.created_at)||!positive(value.created_by)||!hash(value.content_hash)||!hash(value.governance_hash)||value.source_id!==`research_${d.prefix}:${value.source_record_id}:${value.content_hash.slice(0,12)}`||value.audit_only!==auditOnly||value.can_record!==false||value.eligibility_basis!==(kind==='scope'?'project_registry_only_not_patient_collection_permission':'recorded_project_permission_not_irb_certification_or_role_based_patient_access')||!['parent_current','eligible','can_authorization_review','can_review','can_revoke'].every(k=>typeof value[k]==='boolean')||!Array.isArray(value.exclusion_reasons)||value.exclusion_reasons.some(v=>typeof v!=='string')||new Set(value.exclusion_reasons).size!==value.exclusion_reasons.length||value.eligible!==(value.exclusion_reasons.length===0))return null;
 if(kind==='scope'?![true,false,null].includes(value.authorization_reviewer_current):value.authorization_review!==null&&!object(value.authorization_review))return null;
 if(value.original===null){
  if(!allowRedacted||value.eligible||value.can_authorization_review||value.can_review||value.review_basis_note!==null||value.revoke_reason!==null)return null;
  const m=kind==='scope'?pick(value,MANUAL):value.authorization_review;if(m!==null&&m.authorization_review_basis!==null)return null;
  return current()?{level:'technical_metadata',fullGovernanceVerified:false,selectable:false}:null;
 }
 const p=value.original;if(!await verifyProof(p,kind,current)||!current()||!same(p.identity,pick(value,[...IDENTITY,...d.extra]))||p.content_hash!==value.content_hash||p.governance_hash!==value.governance_hash||!same(p.governance,pick(value,GOV))||!same(p.authorization_review,kind==='scope'?pick(value,MANUAL):value.authorization_review))return null;
 return current()?{level:'full_registry_original',fullGovernanceVerified:true,selectable:false}:null;
}catch{return null;}}
