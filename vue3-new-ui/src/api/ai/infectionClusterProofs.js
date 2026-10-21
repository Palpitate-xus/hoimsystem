import {supportCanonical as canonical,supportDigest as digest,supportId as uuid,supportHash as hash} from '../inpatientSupport';
import {decodeGeneratedSchemas,generatedSchemaMatches} from '../sofaSchema';
import {scalarJsonValue} from './nativeOriginalJson';
import packed from './infectionClusterSchemas.json';
import fixed from './infectionClusterFixed.json';

const schemas=decodeGeneratedSchemas(packed),encoder=new TextEncoder();
export {canonical,digest,uuid,hash,fixed};
export const object=v=>v!==null&&typeof v==='object'&&!Array.isArray(v);
export const same=(a,b)=>canonical(a)===canonical(b);
export const keys=(v,names)=>object(v)&&same(Object.keys(v).sort(),[...names].sort());
export const bytes=v=>encoder.encode(typeof v==='string'?v:canonical(v)).length;
export const unique=v=>Array.isArray(v)&&new Set(v).size===v.length;
export const state=v=>v===null?'null':v===''?'empty':'present';
const whitespace=/[\u0009-\u000d\u001c-\u001f\u0020\u0085\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000]/gu;
export const nonblank=v=>typeof v==='string'&&v.replace(whitespace,'').length>0;
export const basis=v=>typeof v==='string'&&scalarJsonValue(v)&&nonblank(v)&&Array.from(v).length<=1000&&bytes(v)<=4000;
export function day(v){try{return typeof v==='string'&&/^\d{4}-\d\d-\d\d$/.test(v)&&!v.startsWith('0000-')&&new Date(v+'T00:00:00Z').toISOString()===v+'T00:00:00.000Z';}catch{return false;}}
export function clock(v,kind='utc6'){try{if(typeof v!=='string'||!day(v.slice(0,10)))return false;const pattern=kind==='utc6'?/^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{6}Z$/:kind==='second'?/^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d$/:/^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d{1,6})?$/;return pattern.test(v)&&Number(v.slice(11,13))<24&&Number(v.slice(14,16))<60&&Number(v.slice(17,19))<60;}catch{return false;}}
export const windowValid=v=>object(v)&&day(v.date_from)&&day(v.date_to)&&v.date_from<=v.date_to;
export function modelValid(name,v){try{return scalarJsonValue(v)&&bytes(v)<=8388608&&generatedSchemaMatches(schemas,name,v);}catch{return false;}}
export const schema=name=>Object.hasOwn(schemas,name)?structuredClone(schemas[name]):null;
export async function textDigest(v){if(typeof v!=='string'||!scalarJsonValue(v))throw new Error('须保留完整Unicode原文');const raw=await crypto.subtle.digest('SHA-256',encoder.encode(v));return Array.from(new Uint8Array(raw),b=>b.toString(16).padStart(2,'0')).join('');}
export function governanceValid(g,parameters=false){try{
 if(!clock(g.recorded_at)||g.reviewed_at!==null&&(!clock(g.reviewed_at)||g.reviewed_at<g.recorded_at)||g.revoked_at!==null&&(!clock(g.revoked_at)||g.revoked_at<(g.reviewed_at??g.recorded_at)))return false;
 const flags=[g.privacy_review,g.faithfulness_review,...(parameters?[g.parameters_review]:[])],reviewed=g.reviewed_by!==null,revoked=g.revoked_by!==null;
 if(reviewed){if(g.reviewed_by===g.created_by||g.review_event_id===null||g.reviewed_at===null||!basis(g.review_basis)||flags.includes('unknown'))return false;}else if(g.reviewed_at!==null||g.review_event_id!==null||g.review_basis!==''||flags.some(f=>f!=='unknown'))return false;
 if(revoked){if(g.status!=='revoked'||g.revoke_event_id===null||g.revoked_at===null||!basis(g.revoke_basis)||g.revision!==(reviewed?3:2))return false;}else if(g.revoked_at!==null||g.revoke_event_id!==null||g.revoke_basis!==''||g.status==='revoked')return false;
 if(parameters&&((g.reviewer_epoch_hash===null)!==!reviewed))return false;
 return g.status==='draft'?g.revision===1&&!reviewed&&!revoked:g.status==='published'?g.revision===2&&reviewed&&!revoked&&flags.every(f=>f==='confirmed'):g.status==='rejected'?g.revision===2&&reviewed&&!revoked&&flags.includes('not_confirmed'):g.status==='revoked'&&revoked;
}catch{return false;}}
export async function verifyRegistryRecord(v,{kind=null,current=()=>true,requirePublished=false}={}){try{
 if(!current()||!modelValid('RegistryRecord',v)||kind!==null&&v.kind!==kind||!governanceValid(v.governance)||v.content_hash!==await digest(v.payload)||!current()||v.governance_hash!==await digest(v.governance)||!current())return false;
 const p=v.payload,g=v.governance,id={grant:'grant_id',definition:'definition_id',review:'review_id'}[v.kind];
 if(p[id]!==v.record_id||(v.kind==='definition'?p.authored_by:p.created_by)!==g.created_by||p.recorded_at!==g.recorded_at||!clock(p.recorded_at))return false;
 if(v.kind==='definition'&&(!nonblank(p.version_label)||!nonblank(p.definition_text)||!unique(p.infection_type_codes)||!unique(p.pathogen_codes)))return false;
 if(v.kind==='grant'&&(!basis(p.basis_note)||!clock(p.valid_from)||!clock(p.valid_to)||p.valid_from>=p.valid_to))return false;
 if(v.kind==='review'&&(!basis(p.basis_note)||!['infection_type','pathogen'].every(f=>{const x=p[f];return basis(x.basis_note)&&(x.assessment==='mapped')===(x.reviewed_code!==null)&&(x.assessment!=='mapped'||x.original_state==='present');})))return false;
 return current()&&(!v.eligible||g.status==='published')&&(!requirePublished||v.eligible&&g.status==='published');
}catch{return false;}}
async function stampValid(v){const fields=[v.reviewed_by,v.reviewed_at,v.basis_note,v.basis_hash];return fields.every(x=>x===null)||fields.every(x=>x!==null)&&clock(v.reviewed_at)&&typeof v.basis_note==='string'&&nonblank(v.basis_note)&&bytes(v.basis_note)<=16000&&await textDigest(v.basis_note)===v.basis_hash;}
export async function verifyPrivateCollection(v,{current=()=>true}={}){try{
 if(!current()||!modelValid('PrivateCollection',v)||!clock(v.captured_at)||!windowValid(v.window)||!unique(v.patient_ids)||!unique(v.originals.map(x=>x.original.case_id))||!unique(v.reviews.map(x=>x.case_id))||!same(v.originals.map(x=>x.original.case_id).sort(),v.reviews.map(x=>x.case_id).sort()))return false;
 const d=v.definition,g=d.governance;
 if(d.content_hash!==await digest(d.payload)||!current()||d.governance_hash!==await digest(g)||!current()||g.definition_content_hash!==d.content_hash||d.payload.authored_by===g.published_by||!clock(d.payload.recorded_at)||!clock(g.published_at)||g.published_at<d.payload.recorded_at||g.published_at>v.captured_at||!nonblank(g.publication_basis_note)||bytes(g.publication_basis_note)>16000||await textDigest(g.publication_basis_note)!==g.publication_basis_hash||!current()||!unique(d.payload.infection_type_codes)||!unique(d.payload.pathogen_codes))return false;
 const reviews=new Map(v.reviews.map(r=>[r.case_id,r]));
 for(const proof of v.originals){
  const row=proof.original,r=reviews.get(row.case_id);
  if(!current()||proof.content_hash!==await digest(row)||!current()||!v.patient_ids.includes(row.patient_id)||!day(row.onset_date)||row.onset_date<v.window.date_from||row.onset_date>v.window.date_to||!clock(row.create_time.text,'naive')||!clock(row.update_time.text,'naive')||r.original_content_hash!==proof.content_hash||r.definition_content_hash!==d.content_hash||r.definition_governance_hash!==d.governance_hash||!await stampValid(r.review)||!current()||r.assessment!=='not_assessed'&&r.review.reviewed_by===null)return false;
  for(const field of ['infection_type','pathogen']){const m=r[field];if(m.field!==field||m.original_state!==state(row[field])||m.original_value_hash!==await digest(row[field])||!current()||(m.assessment==='mapped')!==(m.reviewed_code!==null)||m.assessment==='mapped'&&m.original_state!=='present'||m.reviewed_code!==null&&!d.payload[field+'_codes'].includes(m.reviewed_code)||m.assessment!=='not_assessed'&&m.review.reviewed_by===null||!await stampValid(m.review)||!current())return false;}
  if([r.review,r.infection_type.review,r.pathogen.review].some(s=>s.reviewed_at!==null&&(s.reviewed_at<g.published_at||s.reviewed_at>v.captured_at)))return false;
 }
 return current();
}catch{return false;}}
export async function verifyPublicSource(v,{current=()=>true}={}){try{
 if(!current()||!modelValid('InfectionClusterSource',v)||!clock(v.captured_at)||!windowValid(v.scope.window)||!unique(v.scope.patient_tokens)||!unique(v.reports.map(r=>r.case_token))||!same(v.limitations,fixed.source_limitations)||v.automatic_actions!==false||v.source_id.split(':')[2]!==v.private_collection_hash.slice(0,12))return false;
 const count={meets_definition:0,does_not_meet:0,undetermined:0,not_assessed:0};
 for(const r of v.reports){if(!day(r.onset_date)||r.onset_date<v.scope.window.date_from||r.onset_date>v.scope.window.date_to||!v.scope.patient_tokens.includes(r.patient_token)||!unique(r.missing_basis)||r.recorded_status_meaning!==({0:'reported',1:'investigating',2:'closed_recorded'}[r.recorded_status]??'unknown')||r.human_assessment!=='not_assessed'&&r.assessment_basis_hash===null)return false;count[r.human_assessment]++;
  for(const field of ['infection_type','pathogen']){const m=r[field];if((m.assessment==='mapped')!==(m.reviewed_code!==null)||m.assessment==='mapped'&&(m.original_state!=='present'||m.basis_hash===null)||m.assessment==='not_mapped'&&m.basis_hash===null)return false;}
 }
 return current()&&v.counts.distinct_records===v.reports.length&&v.counts.distinct_subjects_with_records===new Set(v.reports.map(r=>r.patient_token)).size&&v.counts.declared_subjects===v.scope.patient_tokens.length&&Object.entries(count).every(([key,n])=>v.counts[key]===n);
}catch{return false;}}
export async function verifyStatisticsInput(v,{current=()=>true}={}){try{
 if(!current()||!modelValid('StatisticsInput',v)||!await verifyPublicSource(v.source,{current})||!current())return false;
 const s=v.scenario,b=s.source_binding;
 return unique(s.department_tokens)&&unique(s.windows.map(w=>canonical(w)))&&s.windows.every(w=>windowValid(w)&&w.date_from>=v.source.scope.window.date_from&&w.date_to<=v.source.scope.window.date_to)&&s.department_tokens.length*s.windows.length<=256&&/^0\.[0-9]{1,12}$/.test(s.alpha_decimal)&&/[1-9]/.test(s.alpha_decimal.slice(2))&&b.source_id===v.source.source_id&&b.private_collection_hash===v.source.private_collection_hash&&b.public_source_hash===await digest(v.source)&&current()&&v.scenario_content_hash===await digest(s)&&current()&&v.recipe_hash===fixed.recipe_hash;
}catch{return false;}}
export async function verifyScenario(v,{current=()=>true,requirePublished=false}={}){try{
 if(!current()||!modelValid('ScenarioRecord',v)||!governanceValid(v.governance,true)||v.payload.scenario_id!==v.scenario_id||v.content_hash!==await digest(v.payload)||!current()||v.governance_hash!==await digest(v.governance)||!current())return false;
 const p=v.payload;
 if(!clock(p.recorded_at)||p.created_by!==p.author_epoch.user_id||p.author_epoch.token_invalid_before!==null&&!clock(p.author_epoch.token_invalid_before,'naive')||p.created_by!==v.governance.created_by||p.recorded_at!==v.governance.recorded_at||p.plan_hash!==await digest(p.plan)||!current()||p.recipe_hash!==fixed.recipe_hash||(v.eligible||requirePublished)&&p.implementation_hash!==await digest(fixed.implementation)||!current()||!basis(p.basis_note)||!same(p.limitations,fixed.statistics_limitations)||!same(p.source_binding,p.plan.source_binding)||p.scenario_id!==p.plan.scenario_id||!unique(p.departments.map(d=>d.department_id))||!same(p.plan.department_tokens,p.departments.map(d=>d.department_token))||p.directory_hash!==await digest(p.departments)||!current())return false;
 for(const d of p.departments)if(d.directory_hash!==await digest({department_id:d.department_id,name:d.recorded_name})||!current())return false;
 return current()&&(!v.eligible||v.governance.status==='published')&&unique(p.plan.department_tokens)&&unique(p.plan.windows.map(w=>canonical(w)))&&p.plan.windows.every(windowValid)&&p.plan.department_tokens.length*p.plan.windows.length<=256&&/^0\.[0-9]{1,12}$/.test(p.plan.alpha_decimal)&&/[1-9]/.test(p.plan.alpha_decimal.slice(2))&&(!requirePublished||v.eligible&&v.governance.status==='published');
}catch{return false;}}
export async function verifyProfile(v,{current=()=>true,requirePublished=false}={}){try{
 if(!current()||!modelValid('ProfileRecord',v)||!governanceValid(v.governance,true)||v.profile_id!==v.payload.profile_id||v.content_hash!==await digest(v.payload)||!current()||v.governance_hash!==await digest(v.governance)||!current()||v.eligible!==(v.current_issues.length===0)||!unique(v.current_issues))return false;
 const p=v.payload;
 if(p.created_by!==v.governance.created_by||p.recorded_at!==v.governance.recorded_at||!clock(p.recorded_at)||p.created_by!==p.author_epoch.user_id||p.expected_implementation_hash!==await digest(p.implementation_descriptor)||!current()||!keys(p.implementation_descriptor.code_hashes,Object.keys(fixed.implementation.code_hashes))||p.implementation_descriptor.recipe_hash!==fixed.recipe_hash||(v.eligible||requirePublished)&&!same(p.implementation_descriptor,fixed.implementation)||!same(p.limitations,fixed.statistics_limitations)||!basis(p.validation_basis_note)||!basis(p.basis_note)||!same(p.scope.department_ids,p.departments.map(d=>d.department_id))||p.directory_hash!==await digest(p.departments)||!current()||!windowValid(p.scope.source_window)||!unique(p.scope.pathogen_codes)||!unique(p.scope.alpha_decimals)||p.scope.alpha_decimals.some(a=>!/^0\.[0-9]{1,12}$/.test(a)||!/[1-9]/.test(a.slice(2))))return false;
 for(const d of p.departments)if(d.directory_hash!==await digest({department_id:d.department_id,name:d.recorded_name})||!current())return false;
 return current()&&((v.governance.status!=='published')===v.current_issues.includes('not_published'))&&(!v.eligible||v.governance.status==='published')&&unique(p.scope.department_ids)&&(!['pilot','validated'].includes(p.validation_status)||p.validation_evidence_reference!==null)&& (p.validation_evidence_reference===null||nonblank(p.validation_evidence_reference)&&bytes(p.validation_evidence_reference)<=4000)&&(!requirePublished||v.eligible&&v.governance.status==='published');
}catch{return false;}}
