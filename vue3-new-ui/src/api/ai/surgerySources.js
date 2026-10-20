import request from '@/utils/request';
import registry from './surgerySourceSchemas.json';
import {decodeGeneratedSchemas,generatedSchemaMatches} from '../sofaSchema';
import {supportCanonical,supportDigest,supportHash,supportId,supportUtc} from '../inpatientSupport';

const schemas=decodeGeneratedSchemas(registry);
export const surgerySourceKinds=Object.freeze({case_requirements:'病例明确需求',duration_observation:'原实际时长观测',case_duration_estimate:'病例审核阶段时长',operating_room_identity_capability:'手术室身份与能力',person_identity_qualification:'自然人身份与岗位资格',resource_availability_busy:'资源可用/职责/安全忙时',resource_occupation_policy:'资源占用与工时政策',equipment_identity_capability:'具体设备身份与能力'});
export const surgeryRegistryKinds=Object.freeze({pool:'资源池',resource:'全局物理资源',person_account:'自然人账号关联',room_alias:'明确手术室别名',pool_membership:'资源池成员声明'});
export const surgerySourceStates=Object.freeze({draft:'待审核草稿',published:'已审核发布',rejected:'审核拒绝',revoked:'已撤销'});
export const surgerySchemaMatches=(name,value,definition=null)=>generatedSchemaMatches(schemas,name,value,definition);
export function surgeryFormSchema(name,type=null){
 if(!['SourceCreate','RegistryCreate','SourceReview','SourceRevoke','ProtectedCapsuleCreate'].includes(name))return null;
 const schema=JSON.parse(JSON.stringify(schemas[name]));
 if(type!==null){
  const accepts=branch=>{if(branch.$ref){const key=branch.$ref.split('/').at(-1);return accepts(schema.$defs[key]);}if(branch.oneOf)return branch.oneOf.some(accepts);return branch.properties?.kind?.const===type;};
  const filter=value=>{if(Array.isArray(value.oneOf))value.oneOf=value.oneOf.filter(accepts).map(filter);return value;};
  filter(schema.properties.payload);
 }
 return schema;
}
export const surgeryPositive=value=>Number.isSafeInteger(value)&&value>0&&value<=2147483647;
export const surgeryClock=value=>{try{return typeof value==='string'&&Number(value.slice(0,4))>=1000&&supportUtc(value)===value;}catch{return false;}};
export const surgeryBasis=value=>typeof value==='string'&&Array.from(value).length<=4000&&Array.from(value).filter(c=>!/[\s\u0085\u001c-\u001f]/u.test(c)).length>=20&&new TextEncoder().encode(value).length<=4000;
const object=v=>v!==null&&typeof v==='object'&&!Array.isArray(v),same=(a,b)=>supportCanonical(a)===supportCanonical(b),pick=(v,names)=>Object.fromEntries(names.map(k=>[k,v[k]])),keys=(v,names)=>object(v)&&same(Object.keys(v).sort(),[...names].sort()),bytes=v=>new TextEncoder().encode(supportCanonical(v)).length,unique=v=>new Set(v).size===v.length;
const segment=id=>{if(!supportId(id))throw new Error('手术原件标识须为规范小写UUID');return id;},kind=(v,values)=>{if(typeof v!=='string'||!Object.hasOwn(values,v))throw new Error('手术来源或登记类型无效');return v;};
const read=(url,params)=>request({url,method:'get',params,retry:0}),write=(url,data,model)=>{if(model&&!surgeryRequestValid(model,data))throw new Error('手术原件请求与明确类型、原量、UTC或缺项声明不一致');return request({url,method:'post',data:JSON.stringify(data),headers:{'Content-Type':'application/json'},retry:0});};
export const getSurgerySourceOptions=()=>read('ai/surgery-sources/options');
export const getSurgerySources=(type,params)=>read(`ai/surgery-sources/${kind(type,surgerySourceKinds)}`,params);
export const getSurgerySource=(type,id)=>read(`ai/surgery-sources/${kind(type,surgerySourceKinds)}/${segment(id)}`);
export const createSurgerySource=(type,body)=>{if(body?.payload?.kind!==kind(type,surgerySourceKinds))throw new Error('来源正文与路径类型不一致');return write(`ai/surgery-sources/${type}`,body,'SourceCreate');};
export const reviewSurgerySource=(type,id,body)=>write(`ai/surgery-sources/${kind(type,surgerySourceKinds)}/${segment(id)}/review`,body,'SourceReview');
export const revokeSurgerySource=(type,id,body)=>write(`ai/surgery-sources/${kind(type,surgerySourceKinds)}/${segment(id)}/revoke`,body,'SourceRevoke');
export const createSurgeryProtectedCapsule=body=>write('ai/surgery-protected-capsules',body,'ProtectedCapsuleCreate');
export const getSurgeryRegistry=(type,params)=>read(`ai/surgery-registry/${kind(type,surgeryRegistryKinds)}`,params);
export const getSurgeryRegistryRecord=(type,id,params)=>read(`ai/surgery-registry/${kind(type,surgeryRegistryKinds)}/${segment(id)}`,params);
export const createSurgeryRegistry=(type,body)=>{if(body?.payload?.kind!==kind(type,surgeryRegistryKinds))throw new Error('登记正文与路径类型不一致');return write(`ai/surgery-registry/${type}`,body,'RegistryCreate');};
export const reviewSurgeryRegistry=(type,id,body)=>write(`ai/surgery-registry/${kind(type,surgeryRegistryKinds)}/${segment(id)}/review`,body,'SourceReview');
export const revokeSurgeryRegistry=(type,id,body)=>write(`ai/surgery-registry/${kind(type,surgeryRegistryKinds)}/${segment(id)}/revoke`,body,'SourceRevoke');
// Read every actual page before presenting a complete registry candidate set.
export async function getCompleteSurgeryRegistry(type,params={}){
 let rows=[],total=null;
 for(let page=1;page<=200;page++){
  const data=(await getSurgeryRegistry(type,{...params,page,page_size:100})).data;
  if(!data||!Array.isArray(data.items)||!Number.isSafeInteger(data.total)||data.total<0||data.total>20000||data.page!==page||data.page_size!==100||data.items.length>100||total!==null&&total!==data.total||data.items.some(r=>r.registry_kind!==type||!supportId(r.registry_record_id)||!supportHash(r.content_hash)||typeof r.eligible_for_new_use!=='boolean'))throw new Error('资源登记完整分页、类型或总量变化，请重新读取');
  total=data.total;rows.push(...data.items);
  if(rows.length===total){if(!unique(rows.map(r=>r.registry_record_id)))throw new Error('完整登记目录存在重复原件标识');return rows;}
  if(!data.items.length||rows.length>total)break;
 }
 throw new Error('资源登记目录未完整读取，未使用截断候选');
}
// Existing authenticated identity directories, read only. Their status/role/name
// never establishes surgical competence, actual care or all-location coverage.
export const getSurgeryDepartments=(page=1)=>read('departmentManagement/getList',{page,page_size:100});
export const getSurgeryUsers=(page=1)=>read('user/getList',{page,page_size:100});
export const getSurgeryEquipment=()=>read('equipment/list');
export const getSurgeryCssd=(keyword='')=>read('cssd/getList',{keyword});
export async function getSurgeryIdentityDirectories(cssdKeyword=''){
 async function pages(fetch,id,name){let rows=[],total=null;for(let page=1;page<=200;page++){const response=await fetch(page);if(!Array.isArray(response.data)||!Number.isSafeInteger(response.total)||response.total<0||response.total>20000||response.data.length>100||total!==null&&total!==response.total)throw new Error('身份目录完整分页或总量已变化，请重新读取');total=response.total;rows.push(...response.data);if(rows.length===total){if(rows.some(r=>!surgeryPositive(r[id])||typeof r[name]!=='string')||!unique(rows.map(r=>r[id])))throw new Error('真实身份目录存在错误或重复标识');return rows.map(r=>({value:r[id],label:r[name]+' · #'+r[id]}));}if(!response.data.length||rows.length>total)break;}throw new Error('身份目录未完整读取，不能把首批结果当全名单');}
 const [departments,users,equipment,cssd]=await Promise.all([pages(getSurgeryDepartments,'id','name'),pages(getSurgeryUsers,'user_id','username'),getSurgeryEquipment(),getSurgeryCssd(cssdKeyword)]);
 if(!Array.isArray(equipment.data)||!Array.isArray(cssd.data)||equipment.data.some(r=>!surgeryPositive(r.equipment_id)||typeof r.name!=='string')||cssd.data.some(r=>!surgeryPositive(r.instrument_id)||typeof r.package_name!=='string')||!unique(equipment.data.map(r=>r.equipment_id))||!unique(cssd.data.map(r=>r.instrument_id)))throw new Error('真实设备或CSSD检索候选格式不一致');
 return{department_id:departments,user_id:users,equipment_id:equipment.data.map(r=>({value:r.equipment_id,label:r.name+' · '+r.asset_no+' · #'+r.equipment_id})),cssd_instrument_id:cssd.data.map(r=>({value:r.instrument_id,label:r.package_name+' · '+r.package_code+' · #'+r.instrument_id})),cssd_scope:'原包名/编号匹配候选，旧接口最多返回2000条；此检索不是完整CSSD名单或资源覆盖声明。'};
}

// Schema constraints remain separate from model-validator semantics. This walks
// original text/amounts without rounding, inference or clinical default values.
function semantics(v,key=''){
 if(Array.isArray(v))return v.every(item=>semantics(item,key));
 if(!object(v))return true;
 if(Object.hasOwn(v,'value')&&Object.hasOwn(v,'absent_reason')&&((v.value===null)!==(v.absent_reason!==null)))return false;
 if(Object.hasOwn(v,'counted_as_work')&&Object.hasOwn(v,'absent_reason')&&((v.counted_as_work===null)!==(v.absent_reason!==null)))return false;
 if(key.endsWith('_offset_us')&&v.value!==null&&(BigInt(v.value)<-31622400000000n||BigInt(v.value)>31622400000000n))return false;
 if(v.start_at!==undefined&&v.end_at!==undefined&&v.end_at!==null&&v.start_at>=v.end_at)return false;
 if(v.kind==='known'&&!surgeryClock(v.at))return false;
 if(v.breaks){let end=null;for(const item of v.breaks){if(end!==null&&item.start_at<end)return false;end=item.end_at;}if(v.time_accounting_status==='verified'&&(v.counted_as_work===null||!v.breaks_complete||v.breaks.some(item=>item.counted_as_work===null)))return false;}
 for(const [name,value]of Object.entries(v)){
  if(name==='basis_note'&&value!==null&&!surgeryBasis(value)||name.endsWith('_at')&&value!==null&&!surgeryClock(value)||!semantics(value,name))return false;
 }
 return true;
}
function payloadValid(v){
 if(!semantics(v))return false;
 if(v.kind==='case_requirements')return(v.procedure_group_key===null)===(v.procedure_group_absent_reason!==null)&&(v.required===null)===(v.required_absent_reason!==null)&&unique(v.patient_segment_ids)&&unique([v.room.slot_id,...v.roles.map(x=>x.slot_id),...v.equipment.map(x=>x.slot_id)])&&[v.room,...v.roles,...v.equipment].every(x=>unique(x.occupation.segment_ids)&&(x.occupation.transition_class_key===null)===(x.occupation.transition_class_absent_reason!==null)&&(x.occupation.counted_as_work===null)===(x.occupation.counted_as_work_absent_reason!==null))&&v.roles.every(x=>(x.role_kind==='other')===(x.other_role_key!==null));
 if(v.kind==='duration_observation')return v.observed_start_at<v.observed_end_at&&v.observed_end_at<=v.observed_at&&(v.clock_interpretation==='reviewed_legacy_clock_mapping')===(v.legacy_schedule_id!==null);
 if(v.kind==='case_duration_estimate')return unique(v.segments.map(x=>x.segment_id));
 if(v.kind==='resource_availability_busy'){
  if(v.record_type==='duty')return v.accounting.breaks.every(x=>x.start_at>=v.start_at&&x.end_at<=v.end_at);
  if(v.record_type==='busy_capsule')return(v.end_at===null)===(v.end_absent_reason!==null)&&(v.transition_class_key===null)===(v.transition_class_absent_reason!==null)&&(v.verified_until_at===null||v.verified_until_at>=v.start_at&&(v.end_at===null||v.verified_until_at<=v.end_at))&&(v.basis_code==='protected_legacy_witness')===(v.protected_witness_hash!==null);
 }
 if(v.kind==='resource_occupation_policy'&&v.policy_type==='transition')return unique(v.pairs.map(x=>x.from_class_key+'\0'+x.to_class_key));
 return true;
}
function registryPayloadValid(v){
 if(!semantics(v))return false;
 if(v.kind==='resource')return Number(v.equipment_id!==null)+Number(v.cssd_instrument_id!==null)===(v.resource_kind==='equipment'?1:0);
 if(v.kind==='room_alias')return v.alias_scope==='namespace'?v.alias_namespace!==null&&v.legacy_schedule_id===null:v.alias_namespace===null&&v.legacy_schedule_id!==null;
 return true;
}
export function surgeryRequestValid(model,v){
 try{
  if(!surgerySchemaMatches(model,v)||bytes(v)>(model==='RegistryCreate'?262144:8388608)||!semantics(v))return false;
  if(model==='SourceCreate'){
   const clinical=['case_requirements','duration_observation','case_duration_estimate'].includes(v.payload.kind),a=v.professional_attestation;
   return payloadValid(v.payload)&&(clinical?v.application_id!==null&&v.resource_id===null:v.resource_id!==null&&v.application_id===null&&a.status==='unknown')&&(a.status==='confirmed'?a.signer_doctor_id!==null&&a.basis_note!==null:a.signer_doctor_id===null&&a.basis_note===null);
  }
  if(model==='ProtectedCapsuleCreate')return(v.participant_kind==='room')===(v.room_alias_id!==null)&&(v.participant_kind==='assistant')===(v.assistant_doctor_id!==null)&&surgeryBasis(v.clock_basis_note);
  return model!=='RegistryCreate'||registryPayloadValid(v.payload);
 }catch{return false;}
}
const identity=['source_record_id','source_kind','pool_id','resource_id','application_id','patient_id','admission_id','professional_status','signed_by_doctor_id','signed_by_user_id','signed_at','schema_version','recorded_at','created_by'];
const governance=['status','revision','reviewed_by','reviewed_at','review_basis_note','revoked_by','revoked_at','revoke_reason'];
const reasons=['source_not_published','protected_original_changed','original_parent_changed','original_parent_unavailable','case_not_currently_applicable','admission_not_currently_inpatient','original_not_available_at_as_of'];
function stateValid(v,recordedAt,redacted=false){
 const reviewed=v.reviewed_at!==null;
 if(reviewed?!surgeryPositive(v.reviewed_by)||!surgeryClock(v.reviewed_at)||v.reviewed_at<recordedAt:v.reviewed_by!==null)return false;
 if(v.status==='draft'?v.revision!==1||reviewed:['published','rejected'].includes(v.status)?v.revision!==2||!reviewed:v.status!=='revoked'||v.revision!==(reviewed?3:2))return false;
 if(v.status==='revoked'?!surgeryPositive(v.revoked_by)||!surgeryClock(v.revoked_at)||v.revoked_at<(v.reviewed_at||recordedAt):v.revoked_by!==null||v.revoked_at!==null)return false;
 return redacted?v.review_basis_note===null&&v.revoke_reason===null:(reviewed?surgeryBasis(v.review_basis_note):v.review_basis_note==='')&&(v.status==='revoked'?surgeryBasis(v.revoke_reason):v.revoke_reason==='');
}
export function surgerySourceMetadataValid(row,type=null,poolId=null){
 try{
  const omit=['payload','parent_binding','review_basis_note','revoke_reason'],full={...row,...Object.fromEntries(omit.map(k=>[k,null]))};
  if(!surgerySchemaMatches('SourceWrapper',full)||type!==null&&row.source_kind!==type||poolId!==null&&row.pool_id!==poolId||!surgeryClock(row.recorded_at)||row.source_id!==`surgery_fact:${row.source_record_id}:${row.content_hash.slice(0,12)}`||!unique(row.exclusion_reasons)||row.exclusion_reasons.some(x=>!reasons.includes(x))||row.eligible_for_new_use!==(row.exclusion_reasons.length===0)||(row.status!=='published')!==row.exclusion_reasons.includes('source_not_published'))return false;
  return stateValid(full,row.recorded_at,true)&&(!row.can_review||row.audit_only&&row.status==='draft'&&row.exclusion_reasons.every(x=>x==='source_not_published'))&&(!row.can_revoke||['draft','published'].includes(row.status));
 }catch{return false;}
}
export async function verifySurgerySource(row,type=null,poolId=null,{auditOnly=false}={}){
 try{
  if(!surgerySchemaMatches('SourceWrapper',row)||!surgerySourceMetadataValid(row,type,poolId)||auditOnly&&!row.audit_only)return false;
  const visible=row.audit_only||row.status==='draft'&&row.exclusion_reasons.every(x=>x==='source_not_published')||row.eligible_for_new_use;
  if(!visible)return !auditOnly&&['payload','parent_binding','review_basis_note','revoke_reason'].every(k=>row[k]===null);
  const p=row.parent_binding,clinical=['case_requirements','duration_observation','case_duration_estimate'].includes(row.source_kind),signature=p?.professional_signature;
  if(!p||!surgerySchemaMatches('SourceParentBinding',p)||!payloadValid(row.payload)||row.payload.kind!==row.source_kind||p.pool.pool_id!==row.pool_id||bytes(p)>262144||!stateValid(row,row.recorded_at))return false;
  const attestation={status:row.professional_status,signer_doctor_id:row.signed_by_doctor_id,basis_note:signature?.basis_note??null};
  if(!surgeryRequestValid('SourceCreate',{pool_id:row.pool_id,resource_id:row.resource_id,application_id:row.application_id,payload:row.payload,professional_attestation:attestation}))return false;
  if(clinical?!p.case||['application_id','patient_id','admission_id'].some(k=>p.case[k]!==row[k])||p.resource!==null:!p.resource||p.resource.resource_id!==row.resource_id||p.case!==null||row.patient_id!==null||row.admission_id!==null)return false;
  if(clinical){
   if(p.case.department_id!==p.pool.department_id||p.qualification_doctor!==null||p.person_account_hash!==null||p.physical_condition!==null)return false;
   const legacy=row.source_kind==='duration_observation'?row.payload.legacy_schedule_id:null;
   if(legacy===null?p.legacy_clock!==null:p.legacy_clock?.schedule_id!==legacy)return false;
  }else{
   const required=row.source_kind==='operating_room_identity_capability'?'room':row.source_kind==='equipment_identity_capability'?'equipment':row.source_kind==='person_identity_qualification'||row.payload.record_type==='duty'||row.payload.policy_type==='work'?'person':null;
   if(required!==null&&p.resource.resource_kind!==required||p.legacy_clock!==null||(p.resource.resource_kind==='equipment'?!p.physical_condition||Number(p.physical_condition.equipment_id!==null)+Number(p.physical_condition.cssd_instrument_id!==null)!==1:p.physical_condition!==null))return false;
   if(row.source_kind==='person_identity_qualification'){
    if(!supportHash(p.person_account_hash)||(row.payload.doctor_id===null?p.qualification_doctor!==null:!p.qualification_doctor||p.qualification_doctor.doctor_id!==row.payload.doctor_id||p.qualification_doctor.user_id!==row.payload.user_id))return false;
   }else if(p.qualification_doctor!==null||p.person_account_hash!==null)return false;
  }
  if(row.professional_status==='confirmed'?!signature||signature.doctor_id!==row.signed_by_doctor_id||signature.user_id!==row.signed_by_user_id||signature.signed_at!==row.signed_at||row.signed_at!==row.recorded_at||row.signed_by_user_id!==row.created_by:signature!==null||row.signed_by_user_id!==null||row.signed_at!==null)return false;
  const body={...pick(row,identity),payload:row.payload,parent_binding:p};
  return bytes(body)<=8388608&&await supportDigest(body)===row.content_hash&&await supportDigest(pick(row,governance))===row.governance_hash;
 }catch{return false;}
}
const registryFields={pool:['pool_id','department_id'],resource:['resource_id','resource_kind','equipment_id','cssd_instrument_id'],person_account:['binding_id','resource_id','resource_kind','user_id'],room_alias:['alias_id','resource_id','resource_kind','alias_scope','alias_namespace','legacy_schedule_id','raw_text_hash','alias_key'],pool_membership:['membership_id','pool_id','resource_id','pair_key']};
const registryIds={pool:'pool_id',resource:'resource_id',person_account:'binding_id',room_alias:'alias_id',pool_membership:'membership_id'};
export async function verifySurgeryRegistry(row,type=null,{auditOnly=false}={}){
 try{
  const k=kind(row.registry_kind,surgeryRegistryKinds),fields=['registry_kind','registry_record_id',...registryFields[k],'schema_version','recorded_at','created_by'],extra=['content_hash','governance','governance_hash','payload','parent_binding','eligible_for_new_use','exclusion_reasons','audit_only','can_review','can_revoke'];
  if(!keys(row,[...fields,...extra])||type!==null&&k!==type||auditOnly&&!row.audit_only||row.schema_version!=='surgery_registry_private_v1'||!supportId(row.registry_record_id)||row.registry_record_id!==row[registryIds[k]]||!surgeryClock(row.recorded_at)||!surgeryPositive(row.created_by)||!supportHash(row.content_hash)||![row.audit_only,row.eligible_for_new_use,row.can_review,row.can_revoke].every(x=>typeof x==='boolean')||!Array.isArray(row.exclusion_reasons)||!unique(row.exclusion_reasons)||row.exclusion_reasons.some(x=>!['registry_not_published','original_parent_changed','original_parent_unavailable'].includes(x))||row.eligible_for_new_use!==(row.exclusion_reasons.length===0))return false;
  for(const field of registryFields[k]){const v=row[field];if(v===null)continue;if(field.endsWith('_id')&&(['department_id','equipment_id','cssd_instrument_id','user_id'].includes(field)?!surgeryPositive(v):!supportId(v))||['raw_text_hash','alias_key','pair_key'].includes(field)&&!supportHash(v))return false;}
  const governed=['pool','room_alias','pool_membership'].includes(k),visible=row.audit_only||row.eligible_for_new_use||row.governance?.status==='draft'&&row.exclusion_reasons.every(x=>x==='registry_not_published');
  if(governed?!keys(row.governance,governance)||!supportHash(row.governance_hash)||!stateValid(row.governance,row.recorded_at,!visible)||(row.governance.status!=='published')!==row.exclusion_reasons.includes('registry_not_published'):row.governance!==null||row.governance_hash!==null||row.can_review||row.can_revoke)return false;
  if(row.can_review&&(!row.audit_only||row.governance?.status!=='draft'||!visible)||row.can_revoke&&(!row.audit_only||!['draft','published'].includes(row.governance?.status)))return false;
  if(!visible)return !auditOnly&&row.payload===null&&row.parent_binding===null;
  const p=row.payload,b=row.parent_binding;
  if(!surgeryRequestValid('RegistryCreate',{payload:p})||p.kind!==k||!surgerySchemaMatches('RegistryParentBinding',b)||bytes(b)>262144)return false;
  const shared=registryFields[k].filter(x=>Object.hasOwn(p,x));if(shared.some(x=>p[x]!==row[x]))return false;
  if(k==='pool'?!same(b,{department:{department_id:row.department_id},resource:null,pool:null,user:null,equipment:null,cssd_instrument:null,legacy_schedule:null}):false)return false;
  if(k==='resource'&&(b.resource!==null||b.pool!==null||b.user!==null||b.department!==null||b.legacy_schedule!==null||!same(b.equipment,row.equipment_id===null?null:{equipment_id:row.equipment_id})||!same(b.cssd_instrument,row.cssd_instrument_id===null?null:{instrument_id:row.cssd_instrument_id})))return false;
  if(['person_account','room_alias','pool_membership'].includes(k)&&(!b.resource||b.resource.resource_id!==row.resource_id))return false;
  if(k==='person_account'&&['department','pool','equipment','cssd_instrument','legacy_schedule'].some(key=>b[key]!==null)||k==='room_alias'&&['department','pool','user','equipment','cssd_instrument'].some(key=>b[key]!==null)||k==='pool_membership'&&['department','user','equipment','cssd_instrument','legacy_schedule'].some(key=>b[key]!==null))return false;
  if(k==='person_account'&&(row.resource_kind!=='person'||b.resource.resource_kind!=='person'||!same(b.user,{user_id:row.user_id})))return false;
  if(k==='pool_membership'&&(!b.pool||b.pool.pool_id!==row.pool_id||await supportDigest({pool_id:row.pool_id,resource_id:row.resource_id})!==row.pair_key))return false;
  if(k==='room_alias'&&(row.resource_kind!=='room'||b.resource.resource_kind!=='room'||await supportDigest(p.raw_original_text)!==row.raw_text_hash||await supportDigest({scope:row.alias_scope,namespace:row.alias_namespace,legacy_schedule_id:row.legacy_schedule_id,raw_text_hash:row.raw_text_hash})!==row.alias_key||(row.alias_scope==='legacy_schedule'?!same(b.legacy_schedule,{schedule_id:row.legacy_schedule_id,raw_text_hash:row.raw_text_hash}):b.legacy_schedule!==null)))return false;
  const body={...pick(row,fields),payload:p,parent_binding:b};
  return bytes(body)<=262144&&await supportDigest(body)===row.content_hash&&(!governed||await supportDigest(row.governance)===row.governance_hash);
 }catch{return false;}
}
export async function verifySurgeryBusyCapsule(row,resourceId=null,sourceRecordId=null,asOf=null){
 try{
  if(!surgerySchemaMatches('SafeBusyCapsuleWrapper',row)||!payloadValid(row.payload)||resourceId!==null&&row.resource_id!==resourceId||sourceRecordId!==null&&row.source_record_id!==sourceRecordId||!surgeryClock(row.recorded_at)||row.published_at!==null&&(!surgeryClock(row.published_at)||row.published_at<row.recorded_at)||row.status==='published'&&(row.published_at===null||row.revision!==2)||row.eligible_for_new_use!==(row.exclusion_reasons.length===0)||!unique(row.exclusion_reasons)||row.exclusion_reasons.some(x=>!reasons.includes(x))||(row.status!=='published')!==row.exclusion_reasons.includes('source_not_published'))return false;
  if(row.status==='draft'&&(row.revision!==1||row.published_at!==null)||row.status==='rejected'&&(row.revision!==2||row.published_at!==null)||row.status==='revoked'&&(row.revision!==(row.published_at===null?2:3)))return false;
  if(asOf!==null&&(!surgeryClock(asOf)||row.eligible_for_new_use&&(row.recorded_at>asOf||row.published_at>asOf)))return false;
  const {capsule_hash,...capsule}=row;
  // source_content_hash authenticates an undisclosed server-side original. It
  // is deliberately never equated with this separate complete safe-envelope SHA.
  return bytes(capsule)<=8388608&&await supportDigest(capsule)===capsule_hash;
 }catch{return false;}
}
export async function projectSurgerySafeResourcePayload(payload){
 if(!payload||['case_requirements','duration_observation','case_duration_estimate'].includes(payload.kind)||!Object.hasOwn(surgerySourceKinds,payload.kind))throw new Error('病例专业原件不转换为跨范围资源胶囊');
 async function project(value){
  if(Array.isArray(value))return Promise.all(value.map(project));if(!object(value))return value;
  const result={};for(const[key,item]of Object.entries(value)){
   if(['user_id','doctor_id'].includes(key))continue;
   if(key.endsWith('_note'))result[key.slice(0,-5)+'_hash']=await supportDigest(item);
   else if(key==='capability_keys')result.capability_hashes=await Promise.all(item.map(supportDigest));
   else if(['transition_class_key','from_class_key','to_class_key'].includes(key))result[key.slice(0,-4)+'_hash']=item===null?null:await supportDigest(item);
   else if(key==='policy_reference')result.policy_reference_hash=await supportDigest(item);
   else result[key]=await project(item);
  }return result;
 }return project(payload);
}
export async function verifySurgerySafeResourceOriginal(row,expectedOriginal=null,{resourceId=null,sourceRecordId=null,asOf=null}={}){
 try{
  if(!surgerySchemaMatches('SafeResourceOriginalWrapper',row)||resourceId!==null&&row.resource_id!==resourceId||sourceRecordId!==null&&row.source_record_id!==sourceRecordId||!surgeryClock(row.recorded_at)||row.reviewed_at!==null&&(!surgeryClock(row.reviewed_at)||row.reviewed_at<row.recorded_at)||row.published_at!==null&&(row.published_at!==row.reviewed_at)||row.redacted!==(row.payload===null)||row.redacted===row.eligible_for_new_use||row.eligible_for_new_use!==(row.exclusion_reasons.length===0)||!unique(row.exclusion_reasons)||row.exclusion_reasons.some(x=>!reasons.includes(x))||(row.status!=='published')!==row.exclusion_reasons.includes('source_not_published'))return false;
  if(row.status==='draft'&&(row.revision!==1||row.reviewed_at!==null||row.published_at!==null)||row.status==='published'&&(row.revision!==2||row.published_at===null)||row.status==='rejected'&&(row.revision!==2||row.reviewed_at===null||row.published_at!==null)||row.status==='revoked'&&(row.revision!==(row.reviewed_at===null?2:3)||row.published_at!==row.reviewed_at))return false;
  if(asOf!==null&&(!surgeryClock(asOf)||row.eligible_for_new_use&&(row.recorded_at>asOf||row.published_at>asOf)))return false;
  if(row.payload!==null){const p=row.payload;if(p.kind!==row.source_kind||!semantics(p)||p.record_type==='duty'&&p.accounting.breaks.some(b=>b.start_at<p.start_at||b.end_at>p.end_at)||p.record_type==='busy_capsule'&&((p.end_at===null)!==(p.end_absent_reason!==null)||(p.transition_class_hash===null)!==(p.transition_class_absent_reason!==null)||p.verified_until_at!==null&&(p.verified_until_at<p.start_at||p.end_at!==null&&p.verified_until_at>p.end_at)||(p.basis_code==='protected_legacy_witness')!==(p.protected_witness_hash!==null))||p.policy_type==='transition'&&!unique(p.pairs.map(x=>x.from_class_hash+'\0'+x.to_class_hash)))return false;}
  if(expectedOriginal!==null){const e=expectedOriginal;if(!await verifySurgerySource(e)||['source_record_id','source_kind','resource_id','recorded_at','status','revision','reviewed_at'].some(k=>row[k]!==e[k])||row.source_content_hash!==e.content_hash||row.source_governance_hash!==e.governance_hash||row.payload!==null&&!same(row.payload,await projectSurgerySafeResourcePayload(e.payload)))return false;}
  const {capsule_hash,...body}=row;return bytes(body)<=8388608&&await supportDigest(body)===capsule_hash;
 }catch{return false;}
}
export async function verifySurgeryTransition(row,original,action,body,{registryKind=null}={}){
 try{
  if(!['publish','reject','revoke'].includes(action)||!surgeryRequestValid(action==='revoke'?'SourceRevoke':'SourceReview',body)||body.expected_revision!==(registryKind?original.governance.revision:original.revision)||body.expected_content_hash!==original.content_hash||action!=='revoke'&&body.decision!==action||row.content_hash!==original.content_hash)return false;
  const before=registryKind?original.governance:original,after=registryKind?row.governance:row;
  if(registryKind?!await verifySurgeryRegistry(row,registryKind)||!await verifySurgeryRegistry(original,registryKind):!await verifySurgerySource(row)||!await verifySurgerySource(original))return false;
  if(after.status!==(action==='revoke'?'revoked':action==='publish'?'published':'rejected')||after.revision!==before.revision+1)return false;
  const state=action==='revoke'?{...pick(before,governance),status:'revoked',revision:after.revision,revoked_by:after.revoked_by,revoked_at:after.revoked_at,revoke_reason:body.basis_note}:{status:after.status,revision:after.revision,reviewed_by:after.reviewed_by,reviewed_at:after.reviewed_at,review_basis_note:body.basis_note,revoked_by:null,revoked_at:null,revoke_reason:''};
  return registryKind?row.registry_record_id===original.registry_record_id&&await supportDigest(state)===row.governance_hash:identity.every(k=>row[k]===original[k])&&row.source_id===original.source_id&&await supportDigest(state)===row.governance_hash;
 }catch{return false;}
}
