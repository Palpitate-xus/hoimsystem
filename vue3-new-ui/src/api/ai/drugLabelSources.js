import request from '@/utils/request';
import {supportCanonical as canonical,supportDigest as digest,supportId as uuid,supportHash as sha} from '../inpatientSupport';
import {decodeGeneratedSchemas,generatedSchemaMatches} from '../sofaSchema';
import {documentBasis,documentBytesHash,documentClock,documentUtf8,verifyDocumentOriginal,getDocumentOriginals,getDocumentOriginal,documentDirectoryValid,documentMetadataMatches} from './documentEvidence';
import registry from './drugLabelSourceSchemas.json';
import policy from './drugLabelSourcePolicy.json';
const schemas=decodeGeneratedSchemas(registry),base='/ai/drug-label-sources',same=(a,b)=>canonical(a)===canonical(b),object=v=>v!==null&&typeof v==='object'&&!Array.isArray(v),keys=(v,n)=>object(v)&&same(Object.keys(v).sort(),[...n].sort()),pick=(v,n)=>Object.fromEntries(n.map(k=>[k,v[k]]));
const bytes=v=>documentUtf8(typeof v==='string'?v:canonical(v)).length,positive=v=>Number.isSafeInteger(v)&&v>0&&v<=2147483647;
const validScalars=v=>{if(typeof v==='string'){documentUtf8(v);return true;}if(Array.isArray(v))return v.every(validScalars);if(object(v))return Object.entries(v).every(([k,x])=>{documentUtf8(k);return validScalars(x);});return v===null||typeof v==='boolean'||Number.isSafeInteger(v);};
const currentOptions={current:()=>true};
export const drugLabelBasis=(v,revocation=false)=>documentBasis(v,revocation?1000:4000);
export const drugLabelSchemaMatches=(name,value)=>Object.hasOwn(schemas,name)&&generatedSchemaMatches(schemas,name,value);
export const drugLabelSchema=name=>Object.hasOwn(schemas,name)?structuredClone(schemas[name]):null;
export const drugLabelSourcePolicy=Object.freeze(structuredClone(policy));
export function drugLabelRequestValid(model,v){try{
 if(!['SourceCreate','ProfessionalSign','SourceReview','RevokeRequest'].includes(model)||!drugLabelSchemaMatches(model,v)||!validScalars(v)||bytes(v)>policy.source_max_utf8_bytes||!drugLabelBasis(v.basis_note,model==='RevokeRequest'))return false;
 return model!=='SourceReview'||v.decision!=='approve'||v.professional!==null;
}catch{return false;}}
const read=(url,params={})=>request({url,method:'get',params,retry:0});
const id=v=>{if(!uuid(v))throw new Error('说明书来源需要规范UUID');return v;};
const write=(url,data,model)=>{if(!drugLabelRequestValid(model,data))throw new Error('请明确填写本次签署、完整原件版本和治理依据');return request({url,method:'post',data:JSON.stringify(data),headers:{'Content-Type':'application/json'},retry:0});};
export const getDrugLabelOptions=()=>read(base+'/options');
export const getDrugLabelCatalog=params=>read(base+'/catalog',params);
export const getDrugLabelSources=params=>read(base,params);
export const getDrugLabelSource=(value,{auditOnly=false}={})=>read(`${base}/${id(value)}`,{audit_only:auditOnly});
export const createDrugLabelSource=v=>write(base,v,'SourceCreate');
export const signDrugLabelSource=(value,v)=>write(`${base}/${id(value)}/professional-review`,v,'ProfessionalSign');
export const revokeDrugLabelProfessional=(value,v)=>write(`${base}/${id(value)}/professional-review/revoke`,v,'RevokeRequest');
export const reviewDrugLabelSource=(value,v)=>write(`${base}/${id(value)}/review`,v,'SourceReview');
export const revokeDrugLabelSource=(value,v)=>write(`${base}/${id(value)}/revoke`,v,'RevokeRequest');
export {getDocumentOriginals as getDrugLabelOriginals,getDocumentOriginal as getDrugLabelOriginal,documentDirectoryValid,documentMetadataMatches};
export const drugLabelCAS=v=>({expected_revision:v.governance.revision,expected_content_hash:v.content_hash,expected_governance_hash:v.governance_hash});
export function drugLabelOptionsValid(v,{role=null}={}){try{
 if(!keys(v,['schema_version','comparison_fields','can_release','can_technical_review','can_professional_sign','professional_signer_user_id','licensure_verification','clinical_validation','missing_evidence','source_max_utf8_bytes','automatic_extraction','automatic_clinical_rule'])||v.schema_version!=='drug_label_source_options_v1'||!same(v.comparison_fields,policy.comparison_fields)||!same(v.missing_evidence,policy.missing_evidence)||v.source_max_utf8_bytes!==policy.source_max_utf8_bytes||v.licensure_verification!=='not_provided'||v.clinical_validation!=='not_provided'||v.automatic_extraction!==false||v.automatic_clinical_rule!==false)return false;
 const pharmacist=v.can_professional_sign===true&&v.can_release===false&&v.can_technical_review===false&&positive(v.professional_signer_user_id),superAdmin=v.can_professional_sign===false&&v.can_release===true&&v.can_technical_review===true&&v.professional_signer_user_id===null;
 return (role===null||role===(pharmacist?'pharmacist':'super_admin'))&&(pharmacist||superAdmin);
}catch{return false;}}
export async function verifyDrugLabelCatalog(page,{afterId=0,pageSize=20,current=()=>true}={}){try{
 if(!current()||!keys(page,['items','next_cursor','complete'])||!Array.isArray(page.items)||page.items.length>pageSize||typeof page.complete!=='boolean'||(page.complete?page.next_cursor!==null:page.items.length!==pageSize||page.next_cursor!==page.items.at(-1)?.identity.pharmaceutical_id))return false;
 let last=afterId;for(const row of page.items){if(!keys(row,['identity','identity_hash'])||!drugLabelSchemaMatches('Identity',row.identity)||!sha(row.identity_hash)||row.identity.pharmaceutical_id<=last||await digest(row.identity)!==row.identity_hash)return false;last=row.identity.pharmaceutical_id;}
 return current();
}catch{return false;}}
const statuses=['draft','published','rejected','revoked'];
export function drugLabelDirectoryValid(page,{pharmaceuticalId=null,afterId=null,pageSize=20,auditOnly=false}={}){try{
 if(!keys(page,['items','next_cursor','complete','audit_only'])||!Array.isArray(page.items)||page.items.length>pageSize||page.audit_only!==auditOnly||typeof page.complete!=='boolean'||(page.complete?page.next_cursor!==null:page.items.length!==pageSize||page.next_cursor!==page.items.at(-1)?.source_binding_id))return false;
 let last=afterId;return page.items.every(v=>{if(!keys(v,['source_binding_id','source_id','pharmaceutical_id','original_id','recorded_at','content_hash','identity_hash','status','revision','governance_hash','detail_required'])||!uuid(v.source_binding_id)||!uuid(v.original_id)||!positive(v.pharmaceutical_id)||pharmaceuticalId!==null&&v.pharmaceutical_id!==pharmaceuticalId||!documentClock(v.recorded_at)||![v.content_hash,v.identity_hash,v.governance_hash].every(sha)||v.source_id!==`drug_label_source:${v.source_binding_id}:${v.content_hash.slice(0,12)}`||v.detail_required!==true||!statuses.includes(v.status)||(v.status==='draft'?v.revision!==1:v.status==='revoked'?![2,3].includes(v.revision):v.revision!==2)||last!==null&&v.source_binding_id<=last)return false;last=v.source_binding_id;return true;});
}catch{return false;}}
function sourceGovernance(g,recorded){
 const reviewed=g.reviewed_by!==null,revoked=g.revoked_by!==null;
 if(reviewed?g.reviewed_at===null||!documentClock(g.reviewed_at)||g.reviewed_at<recorded||!drugLabelBasis(g.review_basis_note):g.reviewed_at!==null||g.review_basis_note!=='')return false;
 if(revoked?g.revoked_at===null||!documentClock(g.revoked_at)||g.revoked_at<(g.reviewed_at||recorded)||!drugLabelBasis(g.revoke_reason,true):g.revoked_at!==null||g.revoke_reason!=='')return false;
 if(g.status==='draft')return g.revision===1&&!reviewed&&!revoked&&g.professional===null;
 if(g.status==='revoked')return revoked&&g.revision===(reviewed?3:2);
 return g.revision===2&&reviewed&&!revoked&&(g.status==='rejected'||g.status==='published'&&g.professional!==null);
}
async function professionalProof(v,snapshot,contentHash,current){
 if(!drugLabelSchemaMatches('ProfessionalRecord',v)||bytes(v.snapshot)>65535)return false;
 const p=v.snapshot,g=v.governance;
 if(!documentClock(p.signed_at)||p.signed_at<snapshot.recorded_at||[snapshot.created_by,snapshot.original.snapshot.created_by].includes(p.signed_by)||!drugLabelBasis(p.basis_note)||p.source_binding_id!==snapshot.source_binding_id||p.source_content_hash!==contentHash||p.original_content_hash!==snapshot.original.content_hash||p.original_governance_hash!==snapshot.original.governance_hash||p.identity_hash!==snapshot.identity_hash)return false;
 if(g.status==='signed'?(g.revision!==1||g.revoked_by!==null||g.revoked_at!==null||g.revoke_reason!==''):(g.revision!==2||g.revoked_by===null||!documentClock(g.revoked_at)||g.revoked_at<p.signed_at||!drugLabelBasis(g.revoke_reason,true)))return false;
 return current()&&await digest(p)===v.content_hash&&await digest(g)===v.governance_hash&&current();
}
export async function verifyDrugLabelSource(v,{pharmaceuticalId=null,auditOnly=false,role=null,actorId=null,execution=false,current=()=>true}={}){try{
 if(!current()||!drugLabelSchemaMatches('SourceRecord',v)||!validScalars(v)||bytes(v)>policy.source_max_utf8_bytes||v.audit_only!==auditOnly||pharmaceuticalId!==null&&v.snapshot.identity.pharmaceutical_id!==pharmaceuticalId||!same(v.missing_evidence,policy.missing_evidence))return false;
 const s=v.snapshot,g=v.governance,p=v.professional_review;
 if(!documentClock(s.recorded_at)||!same(s.comparison_fields,policy.comparison_fields)||!drugLabelBasis(s.basis_note)||!sourceGovernance(g,s.recorded_at)||!await verifyDocumentOriginal(s.original,{current})||!s.original.eligible||s.original.snapshot.metadata.document_kind!=='drug_label'||s.recorded_at<s.original.governance.reviewed_at||await digest(s.identity)!==s.identity_hash||await digest(s)!==v.content_hash||await digest(g)!==v.governance_hash||v.source_id!==`drug_label_source:${s.source_binding_id}:${v.content_hash.slice(0,12)}`)return false;
 if(p===null){if(v.signer_current||g.professional!==null)return false;}else{
  if(!await professionalProof(p,s,v.content_hash,current))return false;
  if(g.professional!==null){const q=p.snapshot,signed={status:'signed',revision:1,revoked_by:null,revoked_at:null,revoke_reason:''};if(g.professional.professional_review_id!==q.professional_review_id||g.professional.content_hash!==p.content_hash||g.professional.governance_hash!==await digest(signed)||g.reviewed_by===q.signed_by||g.reviewed_at<q.signed_at||q.catalog_match_review!=='confirmed'||q.provided_text_version_review!=='confirmed')return false;}
 }
 const reasons=[];for(const[condition,reason]of [[g.status==='published','source_not_published'],[v.identity_current,'identity_changed'],[v.original_current,'original_not_current'],[p!==null&&p.governance.status==='signed','professional_not_current'],[v.signer_current,'signer_not_current']])if(!condition)reasons.push(reason);if(auditOnly)reasons.push('audit_only');
 if(!same(v.exclusion_reasons,reasons)||v.eligible!==!reasons.length||auditOnly&&(v.can_sign||v.can_review||v.can_revoke)||execution&&(!v.eligible||auditOnly)||v.can_sign&&(!v.identity_current||!v.original_current||g.status!=='draft'||p!==null)||v.can_review&&(!v.identity_current||!v.original_current||g.status!=='draft')||v.can_revoke&&g.status==='revoked')return false;
 if(role!==null){if(!['pharmacist','super_admin'].includes(role)||auditOnly&&role!=='super_admin'||role==='super_admin'&&v.can_sign||role==='pharmacist'&&(v.can_review||v.can_revoke))return false;
  if(!auditOnly&&role==='super_admin'&&(v.can_review!==(v.identity_current&&v.original_current&&g.status==='draft')||v.can_revoke!==(g.status!=='revoked')))return false;
  if(!auditOnly&&role==='pharmacist'&&positive(actorId)){const expected=v.identity_current&&v.original_current&&g.status==='draft'&&p===null&&![s.created_by,s.original.snapshot.created_by].includes(actorId);if(v.can_sign!==expected)return false;}
 }
 return current();
}catch{return false;}}
export function drugLabelMetadataMatches(row,meta){try{return !meta||meta.source_binding_id===row.snapshot.source_binding_id&&meta.pharmaceutical_id===row.snapshot.identity.pharmaceutical_id&&meta.original_id===row.snapshot.original.snapshot.original_id&&meta.content_hash===row.content_hash&&meta.identity_hash===row.snapshot.identity_hash&&meta.governance_hash===row.governance_hash&&meta.status===row.governance.status&&meta.revision===row.governance.revision&&meta.recorded_at===row.snapshot.recorded_at;}catch{return false;}}
export async function verifyDrugLabelCreated(after,body,original,options=currentOptions){try{return drugLabelRequestValid('SourceCreate',body)&&await verifyDrugLabelSource(after,options)&&after.governance.status==='draft'&&after.professional_review===null&&after.snapshot.identity.pharmaceutical_id===body.pharmaceutical_id&&after.snapshot.identity_hash===body.expected_identity_hash&&after.snapshot.basis_note===body.basis_note&&same(after.snapshot.original,original)&&same(body.original,{original_id:original.snapshot.original_id,content_hash:original.content_hash,governance_hash:original.governance_hash});}catch{return false;}}
export async function verifyDrugLabelTransition(after,before,action,body,options={}){try{
 const model=action==='sign'?'ProfessionalSign':action==='review'?'SourceReview':'RevokeRequest';
 const previous=action==='professional_revoke'?before.professional_review:before;
 if(!previous||!drugLabelRequestValid(model,body)||!same(drugLabelCAS(previous),pick(body,['expected_revision','expected_content_hash','expected_governance_hash']))||!await verifyDrugLabelSource(after,options)||!same(after.snapshot,before.snapshot)||after.content_hash!==before.content_hash)return false;
 const a=after.governance,b=before.governance;
 if(action==='sign'){const p=after.professional_review;return before.professional_review===null&&same(a,b)&&p!==null&&p.governance.status==='signed'&&p.snapshot.catalog_match_review===body.catalog_match_review&&p.snapshot.provided_text_version_review===body.provided_text_version_review&&p.snapshot.basis_note===body.basis_note&&(!positive(options.actorId)||p.snapshot.signed_by===options.actorId);}
 if(action==='professional_revoke'){const p=after.professional_review,q=before.professional_review;return same(a,b)&&p!==null&&same(p.snapshot,q.snapshot)&&p.content_hash===q.content_hash&&p.governance.status==='revoked'&&p.governance.revision===q.governance.revision+1&&p.governance.revoke_reason===body.basis_note;}
 if(!same(after.professional_review,before.professional_review)||a.revision!==b.revision+1)return false;
 if(action==='review')return b.status==='draft'&&a.status===(body.decision==='approve'?'published':'rejected')&&a.review_basis_note===body.basis_note&&same(a.professional,body.decision==='approve'?body.professional:null);
 if(action==='revoke')return a.status==='revoked'&&a.revoke_reason===body.basis_note&&same(pick(a,['professional','reviewed_by','reviewed_at','review_basis_note']),pick(b,['professional','reviewed_by','reviewed_at','review_basis_note']));
 return false;
}catch{return false;}}
