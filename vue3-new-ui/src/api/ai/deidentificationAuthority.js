// Mechanical frozen-original proof shared in meaning with the 74 registry.
// This checker grants no live project, patient, model or export permission.
import {deidentificationCanonical as canonical,deidentificationDigest as digest,deidentificationId as uuid,deidentificationHash as hash,deidentificationClock as documentClock,deidentificationUtf8 as documentUtf8,deidentificationBasis as basis,deidentificationRequestValid as requestValid,jsonScalars as scalarJsonValue,keys,pick,same,positive} from './deidentificationCore';
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
export async function verifyDeidentificationAuthority(value,{kind='scope',current=()=>true}={}){try{return await verifyProof(value,kind,current);}catch{return false;}}
