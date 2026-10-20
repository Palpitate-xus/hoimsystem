import request from '@/utils/request';
import registry from './bedSourceSchemas.json';
import {decodeGeneratedSchemas,generatedSchemaMatches} from './sofaSchema';
import {supportCanonical,supportDigest,supportHash,supportId,supportUtc} from './inpatientSupport';

const schemas=decodeGeneratedSchemas(registry),base='ai/bed-sources';
export const bedSourceKinds=Object.freeze({census:{label:'原物理占床日界观测',prefix:'bed_census',model:'CensusPayload'},flow_day:{label:'原病区物理日事件',prefix:'bed_flow_day',model:'FlowDayPayload'},capacity_interval:{label:'原可运营容量或未来场景',prefix:'bed_capacity_interval',model:'CapacityIntervalPayload'}});
export const bedSourceStates=Object.freeze({draft:'待审核草稿',published:'已审核发布',rejected:'审核拒绝',revoked:'已撤销'});
const read=(url,params)=>request({url,method:'get',params,retry:0}),write=(url,data)=>request({url,method:'post',data:JSON.stringify(data),headers:{'Content-Type':'application/json'},retry:0});
const kindPath=kind=>{if(typeof kind!=='string'||!Object.hasOwn(bedSourceKinds,kind))throw new Error('床位原来源类型无效');return kind;},segment=id=>{if(!supportId(id))throw new Error('床位原来源标识须为规范UUID');return id;};
export const getBedSourceOptions=params=>read(`${base}/options`,params);
export const getBedSources=(kind,params)=>read(`${base}/${kindPath(kind)}`,params);
export const getBedSource=(kind,id)=>read(`${base}/${kindPath(kind)}/${segment(id)}`);
export const createBedSource=(kind,data)=>write(`${base}/${kindPath(kind)}`,data);
export const reviewBedSource=(kind,id,data)=>write(`${base}/${kindPath(kind)}/${segment(id)}/review`,data);
export const revokeBedSource=(kind,id,data)=>write(`${base}/${kindPath(kind)}/${segment(id)}/revoke`,data);
export const getAdminBedSources=params=>read('ai/admin/bed-sources',params);
export const getAdminBedSource=id=>read(`ai/admin/bed-sources/${segment(id)}`);
export const bedSchemaMatches=(name,value,definition=null)=>generatedSchemaMatches(schemas,name,value,definition);
const object=value=>value!==null&&typeof value==='object'&&!Array.isArray(value),same=(a,b)=>supportCanonical(a)===supportCanonical(b),keys=(value,fields)=>object(value)&&same(Object.keys(value).sort(),[...fields].sort()),pick=(value,fields)=>Object.fromEntries(fields.map(key=>[key,value[key]])),bytes=value=>new TextEncoder().encode(typeof value==='string'?value:supportCanonical(value)).length;
export const bedPositive=value=>Number.isSafeInteger(value)&&value>0&&value<=2147483647;
export const bedClock=value=>{try{return typeof value==='string'&&Number(value.slice(0,4))>=1000&&supportUtc(value)===value;}catch{return false;}};
export const bedDate=value=>{try{return typeof value==='string'&&/^[1-9]\d{3}-\d\d-\d\d$/.test(value)&&new Date(`${value}T00:00:00.000Z`).toISOString().slice(0,10)===value;}catch{return false;}};
export const bedBasisValid=value=>typeof value==='string'&&Array.from(value).length<=4000&&Array.from(value).filter(char=>!/[\s\u0085\u001c-\u001f]/u.test(char)).length>=20;
export const bedReviewBasisValid=value=>bedBasisValid(value)&&bytes(value)<=4000;
const quantity=value=>value.value===null?['unknown','not_recorded'].includes(value.absent_reason):value.absent_reason===null;
function midnight(value,zone,date){
  if(!bedClock(value)||!value.endsWith('.000000Z'))return false;
  const parts=Object.fromEntries(new Intl.DateTimeFormat('en-GB',{timeZone:zone,year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',second:'2-digit',hourCycle:'h23'}).formatToParts(new Date(value)).filter(row=>row.type!=='literal').map(row=>[row.type,row.value]));
  return `${parts.year}-${parts.month}-${parts.day}`===date&&parts.hour==='00'&&parts.minute==='00'&&parts.second==='00';
}
export function bedPayloadValid(kind,value){
  try{
    if(typeof kind!=='string'||!Object.hasOwn(bedSourceKinds,kind)||!bedSchemaMatches('SourceCreate',value,bedSourceKinds[kind].model)||bytes(value)>262144||Object.entries(value).some(([key,v])=>key.endsWith('_note')&&!bedBasisValid(v)))return false;
    if(kind==='capacity_interval')return bedClock(value.start_at)&&bedClock(value.end_at)&&value.start_at<value.end_at&&quantity(value.operational_total_beds)&&quantity(value.immediate_admittable_slots)&&(value.basis_kind==='observed_operational_capacity'?bedClock(value.observed_at)&&value.observed_at>=value.end_at:value.observed_at===null&&value.immediate_admittable_slots.value===null&&value.immediate_slots_observed_at===null)&&(value.immediate_admittable_slots.value===null?value.immediate_slots_observed_at===null:bedClock(value.immediate_slots_observed_at));
    if(!bedDate(value.business_date)||!bedClock(value.observed_at)||(value.external_record_key===null?value.external_record_key_absent_reason===null:value.external_record_key_absent_reason!==null||!value.external_record_key.trim()))return false;
    const next=new Date(Date.parse(`${value.business_date}T00:00:00.000Z`)+86400000).toISOString().slice(0,10);if(!bedDate(next))return false;
    return kind==='census'?quantity(value.occupied_beds)&&midnight(value.census_at,value.business_timezone,next)&&value.observed_at>=value.census_at:midnight(value.day_start_at,value.business_timezone,value.business_date)&&midnight(value.day_end_at,value.business_timezone,next)&&value.observed_at>=value.day_end_at&&['admission_events','discharge_events','transfer_in_events','transfer_out_events'].every(key=>quantity(value[key]));
  }catch{return false;}
}
const identity=['source_record_id','source_kind','department_id','ward_id','schema_version','recorded_at','created_by'],governance=['status','revision','reviewed_by','reviewed_at','review_basis_note','revoked_by','revoked_at','revoke_reason'];
const parentReasons=['original_department_missing','original_ward_missing','ward_department_binding_changed'],summary=[...identity,'source_id','content_hash','status','revision','reviewed_by','reviewed_at','revoked_by','revoked_at','governance_hash','parent_current','eligible','exclusion_reasons','can_record','can_review','can_revoke','audit_only','eligibility_basis'],full=[...summary,'review_basis_note','revoke_reason','payload','parent_binding'];
function governanceMetadataValid(row){const reviewed=row.reviewed_at!==null;return(reviewed?bedPositive(row.reviewed_by)&&bedClock(row.reviewed_at)&&row.reviewed_at>=row.recorded_at:row.reviewed_by===null)&&(row.status==='draft'?row.revision===1&&!reviewed:['published','rejected'].includes(row.status)?row.revision===2&&reviewed:row.revision===(reviewed?3:2))&&(row.status==='revoked'?bedPositive(row.revoked_by)&&bedClock(row.revoked_at)&&row.revoked_at>=(row.reviewed_at||row.recorded_at):row.revoked_at===null&&row.revoked_by===null);}
export function bedMetadataValid(row,kind=null,departmentId=null,wardId=null){
  try{return(keys(row,summary)||keys(row,full))&&bedSchemaMatches('FrozenIdentity',pick(row,identity))&&(!kind||row.source_kind===kind)&&(departmentId===null||row.department_id===departmentId)&&(wardId===null||row.ward_id===wardId)&&bedClock(row.recorded_at)&&supportId(row.source_record_id)&&bedPositive(row.department_id)&&bedPositive(row.ward_id)&&bedPositive(row.created_by)&&supportHash(row.content_hash)&&row.source_id===`${bedSourceKinds[row.source_kind].prefix}:${row.source_record_id}:${row.content_hash.slice(0,12)}`&&Object.hasOwn(bedSourceStates,row.status)&&supportHash(row.governance_hash)&&[row.parent_current,row.eligible,row.can_record,row.can_review,row.can_revoke,row.audit_only].every(value=>typeof value==='boolean')&&Array.isArray(row.exclusion_reasons)&&new Set(row.exclusion_reasons).size===row.exclusion_reasons.length&&row.exclusion_reasons.every(value=>parentReasons.includes(value)||value===`source_${row.status}`&&row.status!=='published')&&row.parent_current===!row.exclusion_reasons.some(value=>parentReasons.includes(value))&&row.eligible===(row.parent_current&&row.status==='published')&&row.eligible===(row.exclusion_reasons.length===0)&&(row.status==='published'||row.exclusion_reasons.includes(`source_${row.status}`))&&row.can_record===row.parent_current&&(!row.can_review||row.parent_current&&row.status==='draft')&&(!row.can_revoke||['draft','published'].includes(row.status))&&governanceMetadataValid(row)&&row.eligibility_basis==='published_governance_and_current_ward_department_not_census_coverage_capacity_readiness_or_forecast_validation';}catch{return false;}
}
export async function verifyBedSource(row,kind=null,departmentId=null,wardId=null,{auditOnly=false}={}){
  try{
    if(!keys(row,full)||!bedMetadataValid(row,kind,departmentId,wardId)||auditOnly&&!row.audit_only)return false;
    const visible=row.audit_only||row.parent_current&&['draft','published'].includes(row.status);
    if(!visible)return !auditOnly&&['payload','parent_binding','review_basis_note','revoke_reason'].every(key=>row[key]===null);
    if(!bedPayloadValid(row.source_kind,row.payload)||!bedSchemaMatches('ParentBinding',row.parent_binding)||!same(row.parent_binding,{department:{department_id:row.department_id},ward:{ward_id:row.ward_id,department_id:row.department_id}})||bytes(row.parent_binding)>32768||['observed_at','immediate_slots_observed_at'].some(key=>row.payload[key]!==undefined&&row.payload[key]!==null&&row.payload[key]>row.recorded_at))return false;
    const reviewed=row.reviewed_at!==null;
    if(reviewed?!bedReviewBasisValid(row.review_basis_note):row.review_basis_note!=='')return false;
    if(row.status==='revoked'?!bedSchemaMatches('SourceRevoke',{expected_revision:row.revision-1,reason:row.revoke_reason})||!row.revoke_reason.trim():row.revoke_reason!=='')return false;
    return await supportDigest(pick(row,governance))===row.governance_hash&&await supportDigest({...pick(row,identity),payload:row.payload,parent_binding:row.parent_binding})===row.content_hash;
  }catch{return false;}
}
export async function verifyBedTransition(row,original,action,body){
  try{
    if(!['publish','reject','revoke'].includes(action)||row.source_record_id!==original.source_record_id||identity.some(key=>row[key]!==original[key])||row.content_hash!==original.content_hash||row.source_id!==original.source_id||row.status!==(action==='publish'?'published':action==='reject'?'rejected':'revoked')||row.revision!==original.revision+1)return false;
    const fields=action==='revoke'?{status:row.status,revision:row.revision,reviewed_by:original.reviewed_by,reviewed_at:original.reviewed_at,review_basis_note:original.review_basis_note,revoked_by:row.revoked_by,revoked_at:row.revoked_at,revoke_reason:body.reason}:{status:row.status,revision:row.revision,reviewed_by:row.reviewed_by,reviewed_at:row.reviewed_at,review_basis_note:body.review_basis_note,revoked_by:null,revoked_at:null,revoke_reason:''};
    return body.expected_revision===original.revision&&(action==='revoke'||body.expected_content_hash===original.content_hash&&body.decision===action)&&await supportDigest(fields)===row.governance_hash;
  }catch{return false;}
}
