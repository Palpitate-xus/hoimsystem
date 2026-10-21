import request from '@/utils/request';
import registry from './supplySourceSchemas.json';
import {decodeGeneratedSchemas,generatedSchemaMatches} from '../sofaSchema';
import {supportCanonical,supportDigest,supportHash,supportId,supportUtc} from '../inpatientSupport';

const schemas=decodeGeneratedSchemas(registry),base='ai/supply-sources',object=v=>v!==null&&typeof v==='object'&&!Array.isArray(v),same=(a,b)=>supportCanonical(a)===supportCanonical(b),pick=(v,n)=>Object.fromEntries(n.map(k=>[k,v[k]])),keys=(v,n)=>object(v)&&same(Object.keys(v).sort(),[...n].sort()),bytes=v=>new TextEncoder().encode(typeof v==='string'?v:supportCanonical(v)).length,unique=a=>new Set(a).size===a.length;
export const supplySourceKinds=Object.freeze({unit:{label:'原库存计数单位定义',path:'units'},daily:{label:'原独立日数量',path:'daily'}}),supplySourceStates=Object.freeze({draft:'待审核草稿',published:'已审核发布',rejected:'审核拒绝',revoked:'已撤销'});
export const supplySourceTargets=Object.freeze({recorded_request_quantity:'原记录请求量',gross_fulfilled_issue_quantity:'原毛实发量',confirmed_consumed_quantity:'原确认实耗量'});
export const supplySourceSchemaMatches=(name,v)=>generatedSchemaMatches(schemas,name,v);
export function supplyFormSchema(name){return ['UnitCreate','SourceCreate','SourceReview','SourceRevoke','CapturePeriodRequest'].includes(name)?JSON.parse(JSON.stringify(schemas[name])):null;}
export const supplySourcePositive=v=>Number.isSafeInteger(v)&&v>0&&v<=2147483647;
export const supplySourceClock=v=>{try{return typeof v==='string'&&Number(v.slice(0,4))>=1000&&supportUtc(v)===v;}catch{return false;}};
export const supplySourceBasis=(v,max=4000)=>typeof v==='string'&&Array.from(v).length<=max&&Array.from(v).filter(c=>!/[\s\u0085\u001c-\u001f]/u.test(c)).length>=20&&bytes(v)<=4000;
const day=d=>{try{return typeof d==='string'&&/^[1-9][0-9]{3}-[0-9]{2}-[0-9]{2}$/.test(d)&&new Date(d+'T00:00:00Z').toISOString().slice(0,10)===d;}catch{return false;}},addDay=(d,n)=>new Date(Date.parse(d+'T00:00:00Z')+n*86400000).toISOString().slice(0,10),midnights=new Map();
function midnight(d,zone){
 if(!day(d))throw new Error('真实Gregorian日界无效');const cache=zone+'\0'+d;if(midnights.has(cache))return midnights.get(cache);
 const f=new Intl.DateTimeFormat('en-GB',{timeZone:zone,year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',second:'2-digit',hourCycle:'h23'}),parts=t=>Object.fromEntries(f.formatToParts(new Date(t)).filter(p=>p.type!=='literal').map(p=>[p.type,p.value])),center=Date.parse(d+'T00:00:00Z'),offsets=new Set(),found=new Set();
 for(let h=-48;h<=48;h++){const t=center+h*3600000,p=parts(t);offsets.add(Date.parse(`${p.year}-${p.month}-${p.day}T${p.hour}:${p.minute}:${p.second}Z`)-t);}
 for(const o of offsets){const t=center-o,p=parts(t);if(`${p.year}-${p.month}-${p.day}`===d&&p.hour==='00'&&p.minute==='00'&&p.second==='00')found.add(new Date(t).toISOString().replace('.000Z','.000000Z'));}
 if(found.size!==1)throw new Error('实际业务日界不是唯一原UTC');const result=[...found][0];if(midnights.size>4096)midnights.clear();midnights.set(cache,result);return result;
}
export const supplyDayBounds=(date,timezone)=>[midnight(date,timezone),midnight(addDay(date,1),timezone)];
export function supplyLocalDate(clock,timezone){if(!supplySourceClock(clock))throw new Error('实际UTC6时刻无效');const p=Object.fromEntries(new Intl.DateTimeFormat('en-GB',{timeZone:timezone,year:'numeric',month:'2-digit',day:'2-digit'}).formatToParts(new Date(clock)).filter(p=>p.type!=='literal').map(p=>[p.type,p.value]));return `${p.year}-${p.month}-${p.day}`;}
function attestation(v){return v.status==='confirmed'?supplySourcePositive(v.signer_user_id)&&supplySourceBasis(v.basis_note):v.signer_user_id===null&&v.basis_note===null;}
function payloadValid(kind,p){
 if(!attestation(p.professional_attestation)||!supplySourceBasis(p.definition_basis_note)||p.original_unit_text!==null&&(typeof p.original_unit_text!=='string'||!p.original_unit_text.trim()||Array.from(p.original_unit_text).length>120||bytes(p.original_unit_text)>480))return false;
 if(kind==='unit')return p.original_unit_text!==null;
 if(!same(supplyDayBounds(p.date,p.timezone),[p.day_start_at,p.day_end_at])||![p.day_start_at,p.day_end_at,p.observed_at].every(supplySourceClock)||!(p.day_start_at<p.day_end_at&&p.day_end_at<=p.observed_at)||!supplySourceBasis(p.coverage_basis_note)||!supplySourceBasis(p.stock_constraint_basis_note)||(p.quantity.value===null)!==(p.quantity.absent_reason!==null))return false;
 if(p.method==='external_register'?!p.external_record_key||!p.external_record_key.trim():p.external_record_key!==null)return false;
 if(p.unit_review==='confirmed'&&p.original_unit_text===null||p.professional_attestation.status==='unknown'&&(p.unit_review==='confirmed'||p.coverage==='attested_complete')||!unique(p.audit_refs.map(r=>supportCanonical(r))))return false;
 return p.audit_refs.every(r=>(r.kind==='pharmaceutical_ledger')===(r.ledger_id!==null)&&(r.kind==='consumable_trace')===(r.trace_id!==null));
}
export function supplySourceRequestValid(model,v){try{
 if(!supplySourceSchemaMatches(model,v)||bytes(v)>8388608)return false;
 if(['SourceReview','SourceRevoke'].includes(model))return supplySourceBasis(v.basis_note,model==='SourceRevoke'?1000:4000);
 if(['UnitCreate','SourceCreate'].includes(model)){
  const kind=model==='UnitCreate'?'unit':'daily';if(!payloadValid(kind,v.payload))return false;
  if(kind==='daily'){const absent=v.unit_definition_id===null;return absent===(v.expected_unit_content_hash===null)&&absent===(v.expected_unit_governance_hash===null)&&!(absent&&v.payload.unit_review==='confirmed')&&v.payload.audit_refs.every(r=>(r.kind==='pharmaceutical_ledger')===(v.item_kind==='pharmaceutical'));}
  return true;
 }
 if(model==='CapturePeriodRequest')return supplyCapturePeriodValid(v);
 return false;
}catch{return false;}}
function kindPath(kind){if(!Object.hasOwn(supplySourceKinds,kind))throw new Error('明确库存原件类型无效');return supplySourceKinds[kind].path;}
const segment=id=>{if(!supportId(id))throw new Error('库存原件标识须为规范小写UUID');return id;},read=(url,params)=>request({url,method:'get',params,retry:0}),write=(url,data,model)=>{if(!supplySourceRequestValid(model,data))throw new Error('库存原件请求、原量、单位、时钟或明确依据无法核对');return request({url,method:'post',data:JSON.stringify(data),headers:{'Content-Type':'application/json'},retry:0});};
export const getSupplySourceOptions=params=>read(`${base}/options`,params);
export const getSupplySources=(kind,params)=>read(`${base}/${kindPath(kind)}`,params);
export const getSupplySource=(kind,id,params={})=>read(`${base}/${kindPath(kind)}/${segment(id)}`,params);
export const createSupplySource=(kind,data)=>write(`${base}/${kindPath(kind)}`,data,kind==='unit'?'UnitCreate':'SourceCreate');
export const reviewSupplySource=(kind,id,data)=>write(`${base}/${kindPath(kind)}/${segment(id)}/review`,data,'SourceReview');
export const revokeSupplySource=(kind,id,data)=>write(`${base}/${kindPath(kind)}/${segment(id)}/revoke`,data,'SourceRevoke');
export const getAdminSupplySources=params=>read('ai/admin/supply-sources',params);
export const getAdminSupplySource=(id,recordKind)=>read(`ai/admin/supply-sources/${segment(id)}`,{record_kind:recordKind});
export const previewSupplySources=data=>write(`${base}/preview`,data,'CapturePeriodRequest');
const identity=['record_kind','source_kind','source_record_id','unit_definition_id','schema_version','item_kind','item_id','scope','target','date','day_start_at','day_end_at','observed_at','recorded_at','created_by'],governance=['status','revision','reviewed_by','reviewed_at','review_basis_note','revoked_by','revoked_at','revoke_reason'],hidden=['payload','parent_binding','review_basis_note','revoke_reason'];
function state(v,redacted=false){const reviewed=v.reviewed_at!==null;if(reviewed?!supplySourceClock(v.reviewed_at)||v.reviewed_at<v.recorded_at||!supplySourcePositive(v.reviewed_by):v.reviewed_by!==null)return false;if(v.status==='draft'?v.revision!==1||reviewed:['published','rejected'].includes(v.status)?v.revision!==2||!reviewed:v.status!=='revoked'||v.revision!==(reviewed?3:2))return false;if(v.status==='revoked'?!supplySourcePositive(v.revoked_by)||!supplySourceClock(v.revoked_at)||v.revoked_at<(v.reviewed_at||v.recorded_at):v.revoked_by!==null||v.revoked_at!==null)return false;return redacted?v.review_basis_note===null&&v.revoke_reason===null:(reviewed?supplySourceBasis(v.review_basis_note):v.review_basis_note==='')&&(v.status==='revoked'?supplySourceBasis(v.revoke_reason,1000):v.revoke_reason==='');}
export function supplySourceMetadataValid(v,{kind=null,itemKind=null,itemId=null,capture=false}={}){try{
 const full={...v,...Object.fromEntries(hidden.filter(k=>!Object.hasOwn(v,k)).map(k=>[k,null]))};
 if(!supplySourceSchemaMatches(capture?'CaptureSourceWrapper':'SourceWrapper',full)||kind!==null&&v.record_kind!==kind||itemKind!==null&&v.item_kind!==itemKind||itemId!==null&&v.item_id!==itemId||!supplySourceClock(v.recorded_at)||v.source_kind!==(v.record_kind==='unit'?'unit_definition':'daily_quantity')||v.schema_version!==(v.record_kind==='unit'?'supply_unit_private_v1':'supply_daily_private_v1')||v.source_id!==`${v.record_kind==='unit'?'supply_unit':'supply_day'}:${v.source_record_id}:${v.content_hash.slice(0,12)}`||!state({...full,review_basis_note:null,revoke_reason:null},true))return false;
 if(v.record_kind==='unit'?v.unit_definition_id!==v.source_record_id||['target','date','day_start_at','day_end_at','observed_at'].some(k=>v[k]!==null):!Object.hasOwn(supplySourceTargets,v.target)||!day(v.date)||![v.day_start_at,v.day_end_at,v.observed_at].every(supplySourceClock)||!(v.day_start_at<v.day_end_at&&v.day_end_at<=v.observed_at&&v.observed_at<=v.recorded_at))return false;
 const r=v.exclusion_reasons;if(!unique(r)||v.eligible!==(r.length===0)||(v.status!=='published')!==r.includes('source_not_published')||v.parent_current!==!r.some(x=>x!=='source_not_published'))return false;
 if(v.professional_status==='confirmed'?!supplySourcePositive(v.signer_user_id)||v.signed_at!==v.recorded_at:v.signer_user_id!==null||v.signed_at!==null)return false;
 return !(v.can_review&&(v.status!=='draft'||!v.parent_current)||v.can_revoke&&!['draft','published'].includes(v.status)||capture&&(v.audit_only||v.can_record||v.can_review||v.can_revoke));
}catch{return false;}}
function skuValid(v,scope){return keys(v,['item_kind','item_id','scope','identity'])&&['item_kind','item_id','scope'].every(k=>v[k]===scope[k])&&keys(v.identity,v.item_kind==='pharmaceutical'?['name','status','barcode']:['name','status','category','catalog_unit'])&&Object.entries(v.identity).every(([k,x])=>k==='status'?x===null||Number.isSafeInteger(x):x===null||typeof x==='string');}
async function originalProof(v){
 if(!supplySourceSchemaMatches('FrozenIdentity',pick(v,identity))||!supplySourceSchemaMatches('Governance',pick(v,governance))||!supplySourceClock(v.recorded_at)||v.source_kind!==(v.record_kind==='unit'?'unit_definition':'daily_quantity')||v.schema_version!==(v.record_kind==='unit'?'supply_unit_private_v1':'supply_daily_private_v1')||v.source_id!==`${v.record_kind==='unit'?'supply_unit':'supply_day'}:${v.source_record_id}:${v.content_hash.slice(0,12)}`||v.record_kind==='unit'&&(v.unit_definition_id!==v.source_record_id||['target','date','day_start_at','day_end_at','observed_at'].some(k=>v[k]!==null))||v.record_kind==='daily'&&(![v.day_start_at,v.day_end_at,v.observed_at].every(supplySourceClock)||!(v.day_start_at<v.day_end_at&&v.day_end_at<=v.observed_at&&v.observed_at<=v.recorded_at)))return false;
 const k=v.record_kind,p=v.payload,b=v.parent_binding;if(!supplySourceRequestValid(k==='unit'?'UnitCreate':'SourceCreate',k==='unit'?{...pick(v,['item_kind','item_id','scope']),payload:p}:{...pick(v,['item_kind','item_id','scope','unit_definition_id']),expected_unit_content_hash:b?.unit_definition?.content_hash??null,expected_unit_governance_hash:b?.unit_definition?.governance_hash??null,payload:p})||!state(v)||!keys(b,k==='unit'?['scope','sku','signer']:['scope','sku','signer','unit_definition','audit_originals'])||b.scope!=='hospital_inventory'||!skuValid(b.sku,v)||bytes(b)>262144||bytes(p)>262144)return false;
 const a=p.professional_attestation;if(a.status==='confirmed'?!same(b.signer,{user_id:a.signer_user_id,user_role:'pharmacist'})||a.signer_user_id!==v.created_by:b.signer!==null)return false;
 if(k==='daily'){
  if(['target','date','day_start_at','day_end_at','observed_at'].some(key=>v[key]!==p[key]))return false;
  const u=b.unit_definition;if(v.unit_definition_id===null?u!==null:!u||!keys(u,[...identity,...governance,'content_hash','source_id','governance_hash','payload','parent_binding'])||u.record_kind!=='unit'||u.status!=='published'||['unit_definition_id','item_kind','item_id','scope'].some(key=>u[key]!==v[key])||!await originalProof(u))return false;
  if(p.unit_review==='confirmed'&&(!u||u.payload.professional_attestation.status!=='confirmed'||u.payload.original_unit_text!==p.original_unit_text))return false;
  if(!Array.isArray(b.audit_originals)||b.audit_originals.length!==p.audit_refs.length)return false;
  for(let i=0;i<p.audit_refs.length;i++){const r=p.audit_refs[i],o=b.audit_originals[i],n=r.kind==='pharmaceutical_ledger'?['kind','ledger_id','pharmaceutical_id','batch_id','batch_pharmaceutical_id','transaction_type','quantity','before_stock','after_stock','create_time_legacy','time_basis']:['kind','trace_id','consumable_id','action','quantity','action_time_legacy','time_basis'],x=o?.projection,id=r.kind==='pharmaceutical_ledger'?'ledger_id':'trace_id';if(!keys(o,['reference','projection','projection_hash'])||!same(o.reference,r)||!keys(x,n)||x.kind!==r.kind||x[id]!==r[id]||x[r.kind==='pharmaceutical_ledger'?'pharmaceutical_id':'consumable_id']!==v.item_id||!Number.isSafeInteger(x.quantity)||x.time_basis!=='legacy_naive_unknown_not_utc_evidence'||await supportDigest(x)!==o.projection_hash)return false;}
 }
 return await supportDigest({...pick(v,identity),payload:p,parent_binding:b})===v.content_hash&&await supportDigest(pick(v,governance))===v.governance_hash;
}
export async function verifySupplySourceWrapper(v,{capture=false,kind=null,itemKind=null,itemId=null,auditOnly=false}={}){try{
 if(!supplySourceMetadataValid(v,{capture,kind,itemKind,itemId})||!supplySourceSchemaMatches(capture?'CaptureSourceWrapper':'SourceWrapper',v)||bytes(v)>540672||auditOnly&&!v.audit_only)return false;
 const visible=capture?v.eligible:v.audit_only||v.eligible||v.status==='draft'&&v.parent_current;
 if(!visible)return hidden.every(k=>v[k]===null)&&state(v,true);
 return await originalProof(v)&&v.payload.professional_attestation.status===v.professional_status&&v.payload.professional_attestation.signer_user_id===v.signer_user_id;
}catch{return false;}}
export async function verifySupplySourceTransition(row,original,action,body){try{
 if(!['publish','reject','revoke'].includes(action)||!supplySourceRequestValid(action==='revoke'?'SourceRevoke':'SourceReview',body)||body.expected_revision!==original.revision||body.expected_content_hash!==original.content_hash||action!=='revoke'&&body.decision!==action||!await verifySupplySourceWrapper(original)||!await verifySupplySourceWrapper(row)||identity.some(k=>row[k]!==original[k])||row.content_hash!==original.content_hash||row.revision!==original.revision+1||row.status!==(action==='revoke'?'revoked':action==='publish'?'published':'rejected'))return false;
 const g=action==='revoke'?{...pick(original,governance),status:'revoked',revision:row.revision,revoked_by:row.revoked_by,revoked_at:row.revoked_at,revoke_reason:body.basis_note}:{status:row.status,revision:row.revision,reviewed_by:row.reviewed_by,reviewed_at:row.reviewed_at,review_basis_note:body.basis_note,revoked_by:null,revoked_at:null,revoke_reason:''};return await supportDigest(g)===row.governance_hash;
}catch{return false;}}
export function supplyCapturePeriodValid(v){try{if(!supplySourceSchemaMatches('CapturePeriodRequest',v)||!supplySourceClock(v.as_of)||!day(v.date_from)||!day(v.date_to)||v.date_to<addDay(v.date_from,111)||v.date_to>addDay(v.date_from,365))return false;const p=Object.fromEntries(new Intl.DateTimeFormat('en-GB',{timeZone:v.timezone,year:'numeric',month:'2-digit',day:'2-digit'}).formatToParts(new Date(v.as_of)).filter(x=>x.type!=='literal').map(x=>[x.type,x.value]));if(v.date_to!==addDay(`${p.year}-${p.month}-${p.day}`,-1))return false;for(let d=v.date_from;d<=v.date_to;d=addDay(d,1))supplyDayBounds(d,v.timezone);return true;}catch{return false;}}
export async function verifySupplyCapture(v){try{
 const names=['schema_version','request','captured_at','as_of','sku_binding','scope_binding','unit_definitions','source_records','member_manifest','historical_collection_digest','current_membership_digest','collection_digest','max_available_at'];if(!keys(v,names)||v.schema_version!=='supply_capture_v1'||bytes(v)>8388608||!supplyCapturePeriodValid(v.request)||!supplySourceClock(v.captured_at)||v.as_of!==v.request.as_of||v.captured_at<v.as_of||!skuValid(v.sku_binding,v.request)||!same(v.scope_binding,{...pick(v.request,['item_kind','item_id','scope']),sku_identity_hash:await supportDigest(v.sku_binding)})||!['unit_definitions','source_records','member_manifest'].every(k=>Array.isArray(v[k]))||v.unit_definitions.length+v.source_records.length>4096)return false;
 const [start]=supplyDayBounds(v.request.date_from,v.request.timezone),[,end]=supplyDayBounds(v.request.date_to,v.request.timezone),seen=new Set(),manifest=[],clocks=[];
 for(const[group,kind]of[['unit_definitions','unit'],['source_records','daily']]){let previous=null;for(const e of v[group]){const s=e?.source;if(!keys(e,['source','locator','locator_hash'])||!await verifySupplySourceWrapper(s,{capture:true,kind,itemKind:v.request.item_kind,itemId:v.request.item_id})||s.payload!==null&&!same(s.parent_binding.sku,v.sku_binding)||seen.has(s.source_record_id)||previous!==null&&previous>s.source_record_id)return false;seen.add(s.source_record_id);previous=s.source_record_id;const l=pick(s,['record_kind','source_record_id','item_kind','item_id','scope']);if(kind==='daily'){if(!(v.request.date_from<=s.date&&s.date<=v.request.date_to||s.day_start_at<end&&s.day_end_at>start))return false;Object.assign(l,pick(s,['target','date','day_start_at','day_end_at','observed_at']),{timezone:e.locator.timezone});if(!same(supplyDayBounds(s.date,l.timezone),[s.day_start_at,s.day_end_at])||s.payload!==null&&s.payload.timezone!==l.timezone)return false;}if(!same(l,e.locator)||await supportDigest(l)!==e.locator_hash)return false;for(const k of['recorded_at','reviewed_at','revoked_at'])if(s[k]!==null){if(s[k]>v.as_of)return false;clocks.push(s[k]);}manifest.push(Object.fromEntries(Object.entries(s).filter(([k])=>!hidden.includes(k))));}}
 manifest.sort((a,b)=>a.record_kind.localeCompare(b.record_kind)||a.source_record_id.localeCompare(b.source_record_id));if(!same(manifest,v.member_manifest)||v.max_available_at!==(clocks.length?clocks.sort().at(-1):null))return false;
 return await supportDigest(pick(v,['request','scope_binding','unit_definitions','source_records','member_manifest']))===v.historical_collection_digest&&await supportDigest({scope_binding:v.scope_binding,current_sku_state_hash:await supportDigest(v.sku_binding),members:manifest})===v.current_membership_digest&&await supportDigest(Object.fromEntries(Object.entries(v).filter(([k])=>!['captured_at','collection_digest'].includes(k))))===v.collection_digest;
}catch{return false;}}

export const verifySupplyOriginalProof = originalProof;
