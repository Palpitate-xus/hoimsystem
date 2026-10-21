import {supportCanonical as canonical,supportId as uuid,supportHash as hash} from '../inpatientSupport';
import {documentClock} from './documentEvidence';
const common=['schema_version','created_by','created_at','status','revision','reviewed_by','reviewed_at','revoked_by','revoked_at','valid_from','valid_until','content_hash','governance_hash','source_kind','source_record_id','source_id','detail_required','candidate_reference_only'];
const manual=['authorization_review_status','authorization_reviewed_by','authorization_reviewed_at'];
const definitions={scope:{kind:'study_scope',pk:'scope_id',schema:'research_study_scope_v1',extra:manual},acl:{kind:'acl',pk:'acl_id',schema:'research_project_acl_v1',extra:['scope_id','user_id','permission']},authorization:{kind:'authorization',pk:'authorization_id',schema:'research_patient_auth_v1',extra:['scope_id','patient_id','authorization_kind','access_basis',...manual]}};
const positive=v=>Number.isSafeInteger(v)&&v>0&&v<=2147483647,object=v=>v!==null&&typeof v==='object'&&!Array.isArray(v),same=(a,b)=>canonical(a)===canonical(b),keys=(v,n)=>object(v)&&same(Object.keys(v).sort(),[...n].sort());
export function researchRegistryMetadataValid(value,kind,{scopeId=null}={}){try{
 const d=definitions[kind];if(!d||!keys(value,[...common,d.pk,...d.extra])||value.source_kind!==d.kind||value.schema_version!==d.schema||!uuid(value[d.pk])||value[d.pk]!==value.source_record_id||!uuid(value.scope_id)||scopeId!==null&&value.scope_id!==scopeId||!positive(value.created_by)||!documentClock(value.created_at)||!hash(value.content_hash)||!hash(value.governance_hash)||value.source_id!==`research_${kind}:${value.source_record_id}:${value.content_hash.slice(0,12)}`||value.detail_required!==true||value.candidate_reference_only!==true)return false;
 if(kind==='scope'&&value.scope_id!==value.source_record_id)return false;
 const reviewed=value.reviewed_by!==null,revoked=value.revoked_by!==null;
 if(!['draft','published','rejected','revoked'].includes(value.status)||(value.status==='draft'?(value.revision!==1||reviewed||revoked):value.status==='revoked'?(!revoked||value.revision!==(reviewed?3:2)):(value.revision!==2||!reviewed||revoked)))return false;
 for(const name of ['reviewed','revoked']){const who=value[name+'_by'],at=value[name+'_at'];if(who===null?at!==null:!positive(who)||!documentClock(at)||at<value.created_at)return false;}
 if(reviewed&&revoked&&value.revoked_at<value.reviewed_at)return false;
 if(value.valid_from===null?kind!=='authorization'||value.valid_until!==null:!documentClock(value.valid_from)||!documentClock(value.valid_until)||value.valid_from>=value.valid_until)return false;
 if(kind!=='acl'){
  const state=value.authorization_review_status,who=value.authorization_reviewed_by,at=value.authorization_reviewed_at;
  if(state==='unknown'?who!==null||at!==null:!['recorded_reviewed','not_confirmed'].includes(state)||!positive(who)||who===value.created_by||!documentClock(at)||at<value.created_at||reviewed&&at>value.reviewed_at)return false;
 }
 if(kind==='acl'&&(!positive(value.user_id)||!['read_only','read_capture'].includes(value.permission)))return false;
 if(kind==='authorization'&&(!positive(value.patient_id)||!['permission_recorded','waiver_recorded','unknown','withdrawn','denied'].includes(value.authorization_kind)||!['explicit_project_acl','current_care_or_grant'].includes(value.access_basis)))return false;
 return true;
}catch{return false;}}
export function researchRegistryDirectoryValid(value,kind,{scopeId=null,page=1,size=20}={}){try{
 return keys(value,['items','page','size','total'])&&Number.isSafeInteger(page)&&page>0&&page<=100000&&Number.isSafeInteger(size)&&size>0&&size<=100&&value.page===page&&value.size===size&&Number.isSafeInteger(value.total)&&value.total>=0&&Array.isArray(value.items)&&value.items.length===Math.max(0,Math.min(size,value.total-(page-1)*size))&&new Set(value.items.map(v=>v.source_record_id)).size===value.items.length&&value.items.every(v=>researchRegistryMetadataValid(v,kind,{scopeId}));
}catch{return false;}}
export function researchRegistryMetadataMatches(record,metadata,kind){try{
 if(!researchRegistryMetadataValid(metadata,kind))return false;
 const aliases={acl_id:'source_record_id',authorization_id:'source_record_id'};
 return Object.keys(metadata).filter(k=>!['detail_required','candidate_reference_only'].includes(k)).every(k=>{const key=aliases[k]||k,value=kind!=='scope'&&manual.includes(k)?record.authorization_review?.[k]:record[key];return same(value,metadata[k]);});
}catch{return false;}}
