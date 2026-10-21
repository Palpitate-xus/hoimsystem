import request from '@/utils/request';
import {supportCanonical as canonical,supportDigest as digest,supportHash as sha,supportId as uuid} from '@/api/inpatientSupport';
import {decodeGeneratedSchemas,generatedSchemaMatches} from '@/api/sofaSchema';
import {supplySourceBasis} from './supplySources';
import packed from './codingEvidenceSchemas.json';

const schemas=decodeGeneratedSchemas(packed),object=v=>v!==null&&typeof v==='object'&&!Array.isArray(v),same=(a,b)=>canonical(a)===canonical(b),pick=(v,ks)=>Object.fromEntries(ks.map(k=>[k,v[k]]));
const keys=(v,ks)=>object(v)&&same(Object.keys(v).sort(),[...ks].sort()),positive=v=>Number.isSafeInteger(v)&&v>0&&v<=2147483647;
const encoder=new TextEncoder(),bytes=v=>encoder.encode(typeof v==='string'?v:canonical(v)).length;
const scalar=s=>typeof s==='string'&&!/[\uD800-\uDBFF](?![\uDC00-\uDFFF])|(?<![\uD800-\uDBFF])[\uDC00-\uDFFF]/u.test(s);
const clock=v=>{try{return typeof v==='string'&&/^[1-9]\d{3}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{6}Z$/.test(v)&&new Date(v.slice(0,23)+'Z').toISOString()===v.slice(0,23)+'Z';}catch{return false;}};
export const codingEvidenceBasis=v=>scalar(v)&&supplySourceBasis(v);
export const codingEvidenceRevokeBasis=v=>scalar(v)&&supplySourceBasis(v,1000);
export const codingCaseReferencesValid=v=>keys(v,['coding_case_id'])&&uuid(v.coding_case_id);
export const codingScopeValid=v=>keys(v,['patient_id','admission_id','home_id'])&&positive(v.patient_id)&&uuid(v.admission_id)&&uuid(v.home_id);
export const codingEvidenceSchema=n=>Object.hasOwn(schemas,n)?structuredClone(schemas[n]):null;
export function codingEvidenceRequestValid(model,v){try{
 if(!generatedSchemaMatches(schemas,model,v)||bytes(v)>8388608)return false;
 if(model==='SourceReview')return codingEvidenceBasis(v.basis_note);
 if(model==='SourceRevoke')return codingEvidenceRevokeBasis(v.basis_note);
 if(model==='RulePackageCreate')return codingEvidenceBasis(v.basis_note)&&new Set(v.rule_ids).size===v.rule_ids.length;
 const r=model==='CaseCreate'?v.request:v;
 if(!['CaptureRequest','CaseCreate'].includes(model)||!codingScopeValid(pick(r,['patient_id','admission_id','home_id'])))return false;
 const absent=[r.rule_package_id,r.expected_rule_package_content_hash,r.expected_rule_package_governance_hash].map(x=>x===null);if(new Set(absent).size!==1)return false;
 return model!=='CaseCreate'||scalar(v.note)&&bytes(v.note)<=4000;
}catch{return false;}}
const read=(url,params={})=>request({url,method:'get',params,retry:0});
const write=(url,data,model)=>{if(!codingEvidenceRequestValid(model,data))throw new Error('须完整核对实际病案、全部原件与明确治理依据');return request({url,method:'post',data:JSON.stringify(data),headers:{'Content-Type':'application/json'},retry:0});};
const id=v=>{if(!uuid(v))throw new Error('编码依据标识须为规范UUID');return v;};
export const getCodingEvidenceOptions=params=>read('/ai/coding-evidence/options',params);
export const getCodingEvidenceHomes=params=>read('/ai/coding-evidence/homes',params);
export const getCodingEvidenceCases=params=>read('/ai/coding-evidence/cases',params);
export const getCodingEvidenceCase=(identifier,{auditOnly=false}={})=>read(`/ai/coding-evidence/cases/${id(identifier)}`,{audit_only:auditOnly});
export const previewCodingEvidence=data=>write('/ai/coding-evidence/cases/preview',data,'CaptureRequest');
export const createCodingEvidenceCase=data=>write('/ai/coding-evidence/cases',data,'CaseCreate');
export const reviewCodingEvidenceCase=(identifier,data)=>write(`/ai/coding-evidence/cases/${id(identifier)}/review`,data,'SourceReview');
export const revokeCodingEvidenceCase=(identifier,data)=>write(`/ai/coding-evidence/cases/${id(identifier)}/revoke`,data,'SourceRevoke');
export const getCodingEvidencePackages=params=>read('/ai/coding-evidence/packages',params);
export const getCodingEvidencePackage=(identifier,{auditOnly=false}={})=>read(`/ai/coding-evidence/packages/${id(identifier)}`,{audit_only:auditOnly});
export const createCodingEvidencePackage=data=>write('/ai/coding-evidence/packages',data,'RulePackageCreate');
export const reviewCodingEvidencePackage=(identifier,data)=>write(`/ai/coding-evidence/packages/${id(identifier)}/review`,data,'SourceReview');
export const revokeCodingEvidencePackage=(identifier,data)=>write(`/ai/coding-evidence/packages/${id(identifier)}/revoke`,data,'SourceRevoke');

export const codingProjectionPolicy={schema_version:'coding_projection_policy_v1',scope:'one_actual_home_and_admission',clinical_assessment:'awaits_human_clarification',dictionary_release:'unknown',historical_group_rule_basis:'unknown',official_grouper:'not_provided',minimization:'known_patient_identifiers_and_common_identity_phone_patterns_in_explicit_display_text_only_not_guaranteed_anonymous',citation_basis:'exact_model_visible_projected_text_unicode_codepoints_not_private_original_fulltext'};
const textFields=['admission_diagnosis','discharge_diagnosis','other_diagnosis','operation_summary','complication'];
function display(snapshot,value){if(value===null)return null;if(!scalar(value))throw new Error('Original display text must be Unicode scalars');let text=value;for(const key of ['name','identity','phone','address']){const item=snapshot.collection.minimization_basis[key];if(item&&Array.from(item).length>=2)text=text.split(item).join('[已隐藏直接标识]');}return text.replace(/(?<!\p{Decimal_Number})\p{Decimal_Number}{17}[\p{Decimal_Number}Xx](?!\p{Decimal_Number})/gu,'[证件号已隐藏]').replace(/(?<!\p{Decimal_Number})1[3-9]\p{Decimal_Number}{9}(?!\p{Decimal_Number})/gu,'[手机号已隐藏]');}
async function textDigest(v){return Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',encoder.encode(v))),b=>b.toString(16).padStart(2,'0')).join('');}
export async function projectCodingEvidenceSnapshot(snapshot,metadata){try{
 const c=snapshot.collection,key=await crypto.subtle.importKey('raw',Uint8Array.from(snapshot.identity_secret.match(/../g),x=>parseInt(x,16)),{name:'HMAC',hash:'SHA-256'},false,['sign']);
 const token=async(kind,value)=>`coding_${kind}:`+Array.from(new Uint8Array(await crypto.subtle.sign('HMAC',key,encoder.encode(kind+':'+String(value)))),b=>b.toString(16).padStart(2,'0')).join('');
 const documents=[],missing=[];
 for(const field of textFields){const value=c.home[field];if(value===null){missing.push(field);continue;}const text=display(snapshot,value);documents.push({source_id:await token('document',field),field,text,text_hash:await textDigest(text)});}
 const dictionary=new Map(c.dictionary_entries.map(r=>[canonical([r.kind,r.code]),r.entry]));
 const bindings=await Promise.all(c.code_bindings.map(async r=>{const e=dictionary.get(canonical([r.kind,r.icd_code])),state=e===null||e===undefined?'entry_unavailable':!Number.isInteger(e.status)||![0,1].includes(e.status)?'entry_status_unknown':e.status===0?'entry_inactive':r.icd_name!==e.name?'stored_name_differs':'matches_current_dictionary';return{binding_token:await token('binding',r.binding_id),code_token:await token('code',r.kind+':'+r.icd_code),kind:['diagnosis','operation'].includes(r.kind)?r.kind:'unknown',code_text:display(snapshot,r.icd_code),stored_name:display(snapshot,r.icd_name),is_primary:r.is_primary,current_dictionary_state:state,current_dictionary_name:e?display(snapshot,e.name):null};}));
 const entries=await Promise.all(c.dictionary_entries.map(async r=>({source_id:await token('dictionary',r.kind+':'+r.code),kind:['diagnosis','operation'].includes(r.kind)?r.kind:'unknown',code_text:display(snapshot,r.code),entry:r.entry===null?null:{code_text:display(snapshot,r.entry.code),name:display(snapshot,r.entry.name),category:display(snapshot,r.entry.category),status:r.entry.status,release_version:'unknown'}})));
 const ruleView=async r=>r===null?null:{source_id:await token('rule',r.rule_id),...Object.fromEntries(['payment_method','group_code','group_name','diagnosis_prefix','procedure_prefix','version'].map(k=>[k,display(snapshot,r[k])])),...pick(r,['priority','status','effective_from','effective_to']),rule_scope:'current_local_prefix_rule_not_official_grouper'};
 const groups=await Promise.all(c.recorded_groups.map(async r=>({source_id:await token('group',r.grouping_id),...Object.fromEntries(['group_code','payment_method','diagnosis','diagnosis_codes','procedure_codes','grouping_method'].map(k=>[k,display(snapshot,r[k])])),linked_current_rule:r.rule_id===null?null:await token('rule',r.rule_id),original_rule_version:'unknown'})));
 const primaries=c.code_bindings.filter(r=>r.kind==='diagnosis'&&Number.isInteger(r.is_primary)&&r.is_primary===1),checks={primary_diagnosis_state:primaries.length===1?'one_recorded_primary':!primaries.length?'not_recorded':'conflicting_multiple_primaries',malformed_primary_flags:c.code_bindings.filter(r=>!Number.isInteger(r.is_primary)||![0,1].includes(r.is_primary)).length,duplicate_codes:c.code_bindings.length-new Set(c.code_bindings.map(r=>canonical([r.kind,r.icd_code]))).size,home_document_state:c.home.status===1?'submitted':c.home.status===2?'archived':'draft_or_unknown',clinical_validity:'not_determined'};
 return{schema_version:'coding_evidence_public_v1',case_snapshot_id:metadata.case_snapshot_id,source_id:metadata.source_id,case_content_hash:metadata.content_hash,case_publication_governance_hash:metadata.governance_hash,policy:structuredClone(codingProjectionPolicy),captured_at:c.captured_at,original_clock_basis:'legacy_naive_unknown_not_utc_or_historical_availability_evidence',documents,missing_document_fields:missing,code_bindings:bindings,dictionary_entries:entries,recorded_groups:groups,linked_local_rules:await Promise.all(c.linked_rules.map(r=>ruleView(r.entry))),local_rule_package:c.rule_package===null?null:{source_id:await token('package',c.rule_package.package_id),package_kind:'local_prefix_snapshot',rules:await Promise.all(c.rule_package.snapshot.rules.map(ruleView)),official_release:'not_provided'},structural_checks:checks};
}catch{return null;}}

const governanceKeys=['status','revision','reviewed_at','reviewed_by','review_basis_note','revoked_at','revoked_by','revoke_reason'];
const caseIdentity=['case_snapshot_id','home_id','admission_id','patient_id','rule_package_id','schema_version','created_at','created_by','collection_digest'];
const packageIdentity=['package_id','package_kind','schema_version','created_at','created_by','collection_digest'];
const proofKeys=kind=>[...(kind==='package'?packageIdentity:caseIdentity),...governanceKeys,'content_hash','source_id','governance_hash','snapshot'];
function originalCalendar(row){try{for(const[k,v]of Object.entries(row)){if(v===null)continue;if(['create_time','update_time','submit_time','code_time'].includes(k)){if(typeof v!=='string'||!/^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{6}$/.test(v)||v.startsWith('0000-')||new Date(v.slice(0,23)+'Z').toISOString()!==v.slice(0,23)+'Z')return false;}if(['effective_from','effective_to'].includes(k)){if(typeof v!=='string'||!/^\d{4}-\d\d-\d\d$/.test(v)||v.startsWith('0000-')||new Date(v+'T00:00:00.000Z').toISOString()!==v+'T00:00:00.000Z')return false;}}return true;}catch{return false;}}
const compareText=(a,b)=>{const aa=Array.from(a),bb=Array.from(b);for(let i=0;i<Math.min(aa.length,bb.length);i++){const n=aa[i].codePointAt(0)-bb[i].codePointAt(0);if(n)return n;}return aa.length-bb.length;};
function scalars(value){if(typeof value==='string')return scalar(value);if(Array.isArray(value))return value.every(scalars);if(object(value))return Object.entries(value).every(([k,v])=>scalar(k)&&scalars(v));return value===null||typeof value==='boolean'||Number.isSafeInteger(value);}
function governanceValid(v){if(!clock(v.created_at))return false;const reviewed=v.reviewed_at!==null,revoked=v.revoked_at!==null;if(reviewed){if(!positive(v.reviewed_by)||!clock(v.reviewed_at)||v.reviewed_at<v.created_at||!codingEvidenceBasis(v.review_basis_note))return false;}else if(v.reviewed_by!==null||v.review_basis_note!=='')return false;if(revoked){if(!positive(v.revoked_by)||!clock(v.revoked_at)||v.revoked_at<(v.reviewed_at||v.created_at)||!codingEvidenceRevokeBasis(v.revoke_reason))return false;}else if(v.revoked_by!==null||v.revoke_reason!=='')return false;return v.status==='draft'?v.revision===1&&!reviewed&&!revoked:['published','rejected'].includes(v.status)?v.revision===2&&reviewed&&!revoked:v.status==='revoked'&&revoked&&v.revision===(reviewed?3:2);}
async function manifestFor(c){const members=[],add=async(kind,record_id,value)=>members.push({kind,record_id:String(record_id),content_hash:await digest(value)});await add('home',c.home.home_id,c.home);await add('admission_binding',c.admission_binding.admission_id,c.admission_binding);await add('minimization_basis','known_direct_identifiers',c.minimization_basis);for(const[key,kind,pk]of [['code_bindings','code_binding','binding_id'],['recorded_groups','recorded_group','grouping_id']])for(const r of c[key])await add(kind,r[pk],r);for(const r of c.dictionary_entries)await add('dictionary',r.kind+':'+r.code,r);for(const r of c.linked_rules)await add('local_rule',r.rule_id,r);if(c.rule_package!==null)await add('rule_package',c.rule_package.package_id,c.rule_package);return members.sort((a,b)=>compareText(a.kind,b.kind)||compareText(a.record_id,b.record_id));}
export async function verifyCodingEvidenceCapture(c,expected=null){try{
 if(!generatedSchemaMatches(schemas,'Collection',c)||!scalars(c)||bytes(c)>8388608||!clock(c.captured_at)||!codingEvidenceRequestValid('CaptureRequest',c.request)||expected&&!same(c.request,expected))return false;
 const req=c.request,h=c.home,a=c.admission_binding;
 if(![h,...c.code_bindings,...c.recorded_groups,...c.dictionary_entries.map(r=>r.entry).filter(Boolean),...c.linked_rules.map(r=>r.entry).filter(Boolean)].every(originalCalendar))return false;
 if(!same(pick(h,['home_id','patient_id','admission_id']),pick(req,['home_id','patient_id','admission_id']))||!same(pick(a,['patient_id','admission_id']),pick(req,['patient_id','admission_id'])))return false;
 for(const[name,pk]of [['code_bindings','binding_id'],['recorded_groups','grouping_id']]){const rows=c[name],ids=rows.map(r=>r[pk]);if(new Set(ids).size!==ids.length||!same(ids,[...ids].sort((x,y)=>typeof x==='number'?x-y:compareText(x,y)))||rows.some(r=>r.home_id!==req.home_id))return false;}
 if(c.recorded_groups.some(r=>r.patient_id!==req.patient_id))return false;
 const pairs=[...new Map(c.code_bindings.map(r=>[canonical([r.kind,r.icd_code]),[r.kind,r.icd_code]])).values()].sort((x,y)=>compareText(x[0],y[0])||compareText(x[1],y[1]));
 if(!same(c.dictionary_entries.map(r=>[r.kind,r.code]),pairs)||c.dictionary_entries.some(r=>r.entry!==null&&(r.entry.code!==r.code||r.kind==='diagnosis'&&!Object.hasOwn(r.entry,'diagnosis_id')||r.kind==='operation'&&!Object.hasOwn(r.entry,'operation_id'))))return false;
 const ruleIds=[...new Set(c.recorded_groups.map(r=>r.rule_id).filter(v=>v!==null))].sort((x,y)=>x-y);
 if(!same(c.linked_rules.map(r=>r.rule_id),ruleIds)||c.linked_rules.some(r=>r.entry!==null&&r.entry.rule_id!==r.rule_id))return false;
 const p=c.rule_package;if(req.rule_package_id===null){if(p!==null)return false;}else if(p===null||!await verifyCodingEvidenceOriginal(p,'package')||p.status!=='published'||p.package_id!==req.rule_package_id||p.content_hash!==req.expected_rule_package_content_hash||p.governance_hash!==req.expected_rule_package_governance_hash)return false;
 const manifest=await manifestFor(c);if(!same(manifest,c.member_manifest)||await digest(manifest)!==c.manifest_hash)return false;
 return await digest(Object.fromEntries(Object.entries(c).filter(([k])=>!['captured_at','collection_digest'].includes(k))))===c.collection_digest;
}catch{return false;}}
export async function verifyCodingEvidenceOriginal(v,kind='case'){try{
 if(!['case','package'].includes(kind)||!generatedSchemaMatches(schemas,kind==='package'?'PackageOriginalProof':'CaseOriginalProof',v)||!keys(v,proofKeys(kind))||!scalars(v)||bytes(v)>8388608||!governanceValid(v)||await digest(pick(v,governanceKeys))!==v.governance_hash)return false;
 const identity=kind==='package'?packageIdentity:caseIdentity,s=v.snapshot;
 if(kind==='package'){
  if(!s.rules.every(originalCalendar)||!codingEvidenceRequestValid('RulePackageCreate',{package_kind:v.package_kind,rule_ids:s.rule_ids,basis_note:s.basis_note})||!same(s.rule_ids,[...new Set(s.rule_ids)].sort((a,b)=>a-b))||!same(s.rules.map(r=>r.rule_id),s.rule_ids)||await digest(s.rules)!==v.collection_digest)return false;
 }else{
  if(!sha(s.identity_secret)||!scalar(s.note)||bytes(s.note)>4000||!same(s.projection_policy,codingProjectionPolicy)||!await verifyCodingEvidenceCapture(s.collection)||v.collection_digest!==s.collection.collection_digest||s.collection.captured_at>v.created_at||!same(pick(v,['patient_id','admission_id','home_id','rule_package_id']),pick(s.collection.request,['patient_id','admission_id','home_id','rule_package_id'])))return false;
 }
 const identifier=kind==='package'?v.package_id:v.case_snapshot_id,prefix=kind==='package'?'coding_package':'coding_case';
 return v.source_id===`${prefix}:${identifier}:${v.content_hash.slice(0,12)}`&&await digest({...pick(v,identity),snapshot:s})===v.content_hash;
}catch{return false;}}
function scopeMatches(row,{patientId=null,admissionId=null,homeId=null}={}){return(patientId===null||row.patient_id===patientId)&&(admissionId===null||row.admission_id===admissionId)&&(homeId===null||row.home_id===homeId);}
function wrapperState(row,kind,auditOnly){
 if(row.audit_only!==auditOnly||row.eligible!==(row.parent_current&&row.status==='published')||row.can_review&&(!row.parent_current||row.status!=='draft')||row.can_revoke&&!['draft','published'].includes(row.status))return false;
 const reasons=kind==='case'?['current_case_unavailable','case_members_changed','not_published']:['local_rule_changed','not_published'];
 if(new Set(row.exclusion_reasons).size!==row.exclusion_reasons.length||row.exclusion_reasons.some(r=>!reasons.includes(r))||row.parent_current&&row.exclusion_reasons.some(r=>r!=='not_published')||!row.parent_current&&!row.exclusion_reasons.some(r=>r!=='not_published')||(row.status!=='published')!==row.exclusion_reasons.includes('not_published'))return false;
 return true;
}
export async function verifyCodingEvidencePackage(row,{auditOnly=false}={}){try{
 if(!generatedSchemaMatches(schemas,'PackageWrapper',row)||!metadataValid(pick(row,[...packageIdentity,...governanceKeys.filter(k=>!['review_basis_note','revoke_reason'].includes(k)),'content_hash','source_id','governance_hash']),'package')||!wrapperState(row,'package',auditOnly)||!clock(row.created_at)||row.source_id!==`coding_package:${row.package_id}:${row.content_hash.slice(0,12)}`)return false;
 if(row.snapshot===null)return !auditOnly&&!(row.parent_current&&['draft','published'].includes(row.status))&&row.review_basis_note===null&&row.revoke_reason===null;
 return await verifyCodingEvidenceOriginal(pick(row,proofKeys('package')),'package');
}catch{return false;}}
export async function verifyCodingEvidenceCase(row,{patientId=null,admissionId=null,homeId=null,auditOnly=false}={}){try{
 if(!generatedSchemaMatches(schemas,'CaseWrapper',row)||!metadataValid(pick(row,[...caseIdentity,...governanceKeys.filter(k=>!['review_basis_note','revoke_reason'].includes(k)),'content_hash','source_id','governance_hash']),'case')||!scopeMatches(row,{patientId,admissionId,homeId})||!wrapperState(row,'case',auditOnly)||!clock(row.created_at)||row.source_id!==`coding_case:${row.case_snapshot_id}:${row.content_hash.slice(0,12)}`)return false;
 if(row.snapshot===null)return !auditOnly&&!(row.parent_current&&['draft','published'].includes(row.status))&&row.public_source===null&&row.review_basis_note===null&&row.revoke_reason===null;
 if(!await verifyCodingEvidenceOriginal(pick(row,proofKeys('case')),'case'))return false;
 const published=row.status==='published'||row.status==='revoked'&&row.revision===3;
 if(!published)return row.public_source===null&&row.projection_hash===null;
 if(!sha(row.projection_hash))return false;
 const metadata={...pick(row,[...caseIdentity,...governanceKeys,'content_hash','source_id','governance_hash']),status:'published',revision:2,revoked_at:null,revoked_by:null,revoke_reason:''};metadata.governance_hash=await digest(pick(metadata,governanceKeys));
 const projected=await projectCodingEvidenceSnapshot(row.snapshot,metadata);
 return projected!==null&&same(projected,row.public_source)&&await digest(projected)===row.projection_hash;
}catch{return false;}}
export async function verifyCodingEvidenceTransition(after,before,action,body,kind='case'){try{
 const verify=kind==='package'?verifyCodingEvidencePackage:verifyCodingEvidenceCase,idKey=kind==='package'?'package_id':'case_snapshot_id';
 if(!['publish','reject','revoke'].includes(action)||!await verify(after,{auditOnly:after.audit_only})||after[idKey]!==before[idKey]||after.content_hash!==before.content_hash||body.expected_content_hash!==before.content_hash||body.expected_revision!==before.revision||after.revision!==before.revision+1)return false;
 if(action==='revoke'){if(after.status!=='revoked'||!same(pick(after,['reviewed_at','reviewed_by']),pick(before,['reviewed_at','reviewed_by']))||after.revoke_reason!==null&&after.revoke_reason!==body.basis_note||after.review_basis_note!==null&&after.review_basis_note!==before.review_basis_note)return false;const expected={...pick(after,governanceKeys),review_basis_note:before.review_basis_note,revoke_reason:body.basis_note};return await digest(expected)===after.governance_hash;}
 return after.status===(action==='publish'?'published':'rejected')&&after.review_basis_note===body.basis_note&&body.decision===action;
}catch{return false;}}
export const getCodingEvidenceRules=params=>read('/ai/coding-evidence/rules',params);
const pageValid=(v,q,extra=[])=>keys(v,['items','total','page','page_size',...extra])&&Array.isArray(v.items)&&Number.isSafeInteger(v.total)&&v.total>=0&&positive(v.page)&&positive(v.page_size)&&v.page_size<=100&&v.page===(q.page||1)&&v.page_size===(q.page_size||20)&&v.items.length===Math.min(v.page_size,Math.max(0,v.total-(v.page-1)*v.page_size));
function metadataValid(row,kind){try{const identity=kind==='case'?caseIdentity:packageIdentity,metadataKeys=[...identity,...governanceKeys.filter(k=>!['review_basis_note','revoke_reason'].includes(k)),'content_hash','source_id','governance_hash'];if(!keys(row,metadataKeys)||!generatedSchemaMatches(schemas,kind==='case'?'CaseMetadata':'PackageMetadata',{...row,review_basis_note:'',revoke_reason:''})||!clock(row.created_at))return false;const reviewed=positive(row.reviewed_by)&&clock(row.reviewed_at)&&row.reviewed_at>=row.created_at,revoked=positive(row.revoked_by)&&clock(row.revoked_at)&&row.revoked_at>=(row.reviewed_at||row.created_at);if(row.reviewed_at===null&&row.reviewed_by!==null||row.revoked_at===null&&row.revoked_by!==null)return false;if(row.status==='draft'&&!(row.revision===1&&row.reviewed_at===null&&row.revoked_at===null)||['published','rejected'].includes(row.status)&&!(row.revision===2&&reviewed&&row.revoked_at===null)||row.status==='revoked'&&!(revoked&&row.revision===(reviewed?3:2)&&(!reviewed?row.reviewed_at===null&&row.reviewed_by===null:true)))return false;const idKey=kind==='case'?'case_snapshot_id':'package_id',prefix=kind==='case'?'coding_case':'coding_package';return row.source_id===`${prefix}:${row[idKey]}:${row.content_hash.slice(0,12)}`;}catch{return false;}}
export function codingEvidenceDirectoryValid(value,kind,query={}){try{return['case','package'].includes(kind)&&pageValid(value,query,['detail_required'])&&value.detail_required===true&&new Set(value.items.map(r=>kind==='case'?r.case_snapshot_id:r.package_id)).size===value.items.length&&value.items.every(r=>metadataValid(r,kind)&&(kind!=='case'||['patient_id','admission_id','home_id'].every(k=>query[k]===undefined||r[k]===query[k])))&&(kind!=='package'||query.audit_only===true||value.items.every(r=>r.status==='published'));}catch{return false;}}
export function codingEvidenceOptionsValid(v){return keys(v,['scope','can_record','can_review','can_manage_rule_packages','professional_qualification','official_grouper','historical_capture_supported','case_rows_require_patient_and_admission','max_bindings','max_groups','max_linked_rules','max_bytes'])&&v.scope==='one_actual_home_and_admission'&&v.can_record===true&&typeof v.can_review==='boolean'&&v.can_manage_rule_packages===v.can_review&&v.professional_qualification==='not_provided'&&v.official_grouper==='not_provided'&&v.historical_capture_supported===false&&v.case_rows_require_patient_and_admission===true&&v.max_bindings===4096&&v.max_groups===256&&v.max_linked_rules===4096&&v.max_bytes===8388608;}
export function codingEvidenceHomesValid(v,query){try{return keys(v,['items','total','patient_id','admission_id','can_record'])&&positive(v.patient_id)&&uuid(v.admission_id)&&v.patient_id===query.patient_id&&v.admission_id===query.admission_id&&v.can_record===true&&Array.isArray(v.items)&&v.total===v.items.length&&v.total<=1&&v.items.every(r=>keys(r,['home_id','patient_id','admission_id','status','update_time'])&&uuid(r.home_id)&&r.patient_id===v.patient_id&&r.admission_id===v.admission_id&&Number.isSafeInteger(r.status)&&originalCalendar(r));}catch{return false;}}
export function codingEvidenceRulesValid(v,query){try{return pageValid(v,query,['official_rules_seeded'])&&v.official_rules_seeded===false&&new Set(v.items.map(r=>r.rule_id)).size===v.items.length&&v.items.every(r=>keys(r,['rule_id','payment_method','group_code','group_name','diagnosis_prefix','procedure_prefix','priority','version','effective_from','effective_to','status','update_time','original_content_hash','rule_scope'])&&positive(r.rule_id)&&['payment_method','group_code','group_name','diagnosis_prefix','procedure_prefix','version'].every(k=>scalar(r[k]))&&Number.isSafeInteger(r.priority)&&Number.isSafeInteger(r.status)&&[r.effective_from,r.effective_to].every(x=>x===null||typeof x==='string'&&/^\d{4}-\d\d-\d\d$/.test(x))&&originalCalendar(r)&&sha(r.original_content_hash)&&r.rule_scope==='current_local_prefix_rule_not_official_grouper');}catch{return false;}}
export async function verifyCodingEvidenceFrozenCase(row,{patientId=null,admissionId=null,homeId=null}={}){try{
 if(!object(row)||row.frozen_task_view!==true||row.can_record!==false||row.can_review!==false||row.can_revoke!==false||!scopeMatches(row,{patientId,admissionId,homeId}))return false;
 const live={...row};delete live.frozen_task_view;
 if(Object.hasOwn(live,'audit_only'))return verifyCodingEvidenceCase(live,{patientId,admissionId,homeId,auditOnly:live.audit_only});
 if(!keys(row,[...proofKeys('case'),'public_source','projection_hash','frozen_task_view','can_record','can_review','can_revoke'])||!await verifyCodingEvidenceOriginal(pick(row,proofKeys('case')))||!['published','revoked'].includes(row.status)||row.reviewed_at===null||!sha(row.projection_hash))return false;
 const metadata={...pick(row,[...caseIdentity,...governanceKeys,'content_hash','source_id','governance_hash']),status:'published',revision:2,revoked_at:null,revoked_by:null,revoke_reason:''};metadata.governance_hash=await digest(pick(metadata,governanceKeys));
 const publicSource=await projectCodingEvidenceSnapshot(row.snapshot,metadata);return publicSource!==null&&same(publicSource,row.public_source)&&await digest(publicSource)===row.projection_hash;
}catch{return false;}}
