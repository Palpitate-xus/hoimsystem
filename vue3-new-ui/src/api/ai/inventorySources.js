import request from '@/utils/request';
import registry from './inventorySourceSchemas.json';
import {decodeGeneratedSchemas,generatedSchemaMatches} from '../sofaSchema';
import {supportCanonical,supportDigest,supportHash,supportId} from '../inpatientSupport';
import {supplyDayBounds,supplyLocalDate,supplySourceClock,supplySourceBasis,supplySourcePositive,verifySupplyOriginalProof,verifySupplySourceWrapper} from './supplySources';

const schemas=decodeGeneratedSchemas(registry),base='ai/inventory-native-sources',object=v=>v!==null&&typeof v==='object'&&!Array.isArray(v),same=(a,b)=>supportCanonical(a)===supportCanonical(b),pick=(v,n)=>Object.fromEntries(n.map(k=>[k,v[k]])),keys=(v,n)=>object(v)&&same(Object.keys(v).sort(),[...n].sort()),bytes=v=>new TextEncoder().encode(typeof v==='string'?v:supportCanonical(v)).length,unique=v=>new Set(v).size===v.length;
const identity=['source_record_id','source_kind','item_kind','item_id','scope','unit_definition_id','date_from','date_to','timezone','schema_version','recorded_at','created_by'],governance=['status','revision','reviewed_by','reviewed_at','review_basis_note','revoked_by','revoked_at','revoke_reason'],hidden=['payload','parent_binding','review_basis_note','revoke_reason'],reasons=['source_not_published','original_sku_changed','original_sku_unavailable','professional_signature_changed','unit_definition_changed','legacy_inventory_changed'];
export const inventorySourceKinds=Object.freeze({inventory_observation:'原独立实盘或技术库存采集',future_quantity_scenario:'明确未来出库情景原件',purchase_candidate_plan:'完整不可拆分采购候选'}),inventorySourceStates=Object.freeze({draft:'待技术审核',published:'已审核发布',rejected:'审核拒绝',revoked:'已撤销'});
export const inventorySourceBasis=supplySourceBasis,inventoryRevokeBasis=v=>supplySourceBasis(v,1000),inventorySourcePositive=supplySourcePositive;
export const inventorySourceSchemaMatches=(model,value)=>generatedSchemaMatches(schemas,model,value);
export function inventorySourceSchema(model){return ['SourceCreate','SourceReview','SourceRevoke','CapturePeriod','LegacyCaptureRequest'].includes(model)?JSON.parse(JSON.stringify(schemas[model])):null;}
const day=v=>{try{return typeof v==='string'&&/^\d{4}-\d{2}-\d{2}$/.test(v)&&new Date(v+'T00:00:00Z').toISOString().slice(0,10)===v;}catch{return false;}},addDay=(d,n)=>new Date(Date.parse(d+'T00:00:00Z')+n*86400000).toISOString().slice(0,10);
function period(v){try{if(!day(v.date_from)||!day(v.date_to)||v.date_to<v.date_from||v.date_to>addDay(v.date_from,30))return false;for(let d=v.date_from;d<=v.date_to;d=addDay(d,1))supplyDayBounds(d,v.timezone);return true;}catch{return false;}}
function professional(v){return v.status==='confirmed'?supplySourcePositive(v.signer_user_id)&&supplySourceBasis(v.basis_note):v.status==='unknown'&&v.signer_user_id===null&&v.basis_note===null;}
function walk(v,fn){if(object(v)){if(!fn(v))return false;return Object.values(v).every(x=>walk(x,fn));}return !Array.isArray(v)||v.every(x=>walk(x,fn));}
function quantities(v){const out=[];walk(v,x=>{if(keys(x,['value','absent_reason','original_unit_text','unit_review']))out.push(x);return true;});return out;}
function payloadValid(p){
 if(!object(p)||!Object.hasOwn(inventorySourceKinds,p.kind)||!professional(p.professional_attestation))return false;
 const confirmed=p.professional_attestation.status==='confirmed';
 if(!walk(p,x=>{for(const[k,v]of Object.entries(x)){
  if(k.endsWith('_basis_note')||k==='definition_basis_note'){if(!supplySourceBasis(v))return false;}
  if(k==='professional_attestation')continue;
  if(!confirmed&&((k.endsWith('_review')||['physical_reconciliation','legacy_reconciliation'].includes(k))&&v==='confirmed'||['coverage','completeness'].includes(k)&&v==='attested_complete'))return false;
  if(['valid_through','arrival_date'].includes(k)&&(!object(v)||(v.value===null)!==(v.absent_reason!==null)||v.value!==null&&!day(v.value)))return false;
 }
 if(Object.hasOwn(x,'value')&&Object.hasOwn(x,'absent_reason')&&(x.value===null)!==(x.absent_reason!==null))return false;
 for(const k of ['original_unit_text','currency_text','original_cost_unit_text','original_order_key','original_lot_key'])if(Object.hasOwn(x,k)&&x[k]!==null&&!x[k].trim())return false;
 if(Object.hasOwn(x,'currency_text')&&x.unit_review==='confirmed'&&(x.currency_text===null||x.original_cost_unit_text===null))return false;
 if(Object.hasOwn(x,'original_unit_text')&&x.unit_review==='confirmed'&&x.original_unit_text===null)return false;
 return true;}))return false;
 if(p.kind==='inventory_observation')return (p.method==='independent_count')===(p.observed_at!==null)&&(p.observed_at===null||supplySourceClock(p.observed_at))&&unique(p.lots.map(l=>l.lot_id));
 if(!period(p))return false;
 if(p.kind==='future_quantity_scenario'){
  const expected=[];for(let d=p.date_from;d<=p.date_to;d=addDay(d,1)){const[start,end]=supplyDayBounds(d,p.timezone);expected.push([d,start,end]);}
  return same(expected,p.days.map(d=>[d.date,d.day_start_at,d.day_end_at]));
 }
 const lots=p.orders.flatMap(o=>o.lines);return lots.length<=8192&&unique(p.orders.map(o=>o.order_id))&&unique(lots.map(l=>l.lot_id))&&lots.every(l=>l.arrival_date.value===null||p.date_from<=l.arrival_date.value&&l.arrival_date.value<=p.date_to);
}
export function inventorySourceRequestValid(model,v){try{
 if(!inventorySourceSchemaMatches(model,v)||bytes(v)>8388608)return false;
 if(['SourceReview','SourceRevoke'].includes(model))return supplySourceBasis(v.basis_note,model==='SourceRevoke'?1000:4000);
 if(model==='CapturePeriod')return period(v)&&supplySourceClock(v.as_of)&&v.date_from>supplyLocalDate(v.as_of,v.timezone);
 if(model==='LegacyCaptureRequest')return true;
 if(model!=='SourceCreate'||!payloadValid(v.payload))return false;
 const absent=v.unit_definition_id===null,anchor=v.expected_legacy_digest??null;
 if(v.payload.kind==='inventory_observation'?v.payload.legacy_reconciliation==='confirmed'&&!supportHash(anchor):anchor!==null)return false;
 return absent===(v.expected_unit_content_hash===null)&&absent===(v.expected_unit_governance_hash===null)&&!(absent&&(quantities(v.payload).some(q=>q.unit_review==='confirmed')||v.payload.legacy_quantity_unit_review==='confirmed'));
}catch{return false;}}
function path(kind){if(!Object.hasOwn(inventorySourceKinds,kind))throw new Error('库存原件种类无效');return `${base}/${kind}`;}
const id=v=>{if(!supportId(v))throw new Error('库存原件须为规范UUID');return v;},read=(url,params)=>request({url,method:'get',params,retry:0}),write=(url,data,model)=>{if(!inventorySourceRequestValid(model,data))throw new Error('原件单位、全量、时钟或明确依据无法核对');return request({url,method:'post',data:JSON.stringify(data),headers:{'Content-Type':'application/json'},retry:0});};
export const getInventorySourceOptions=params=>read(`${base}/options`,params);
export const getInventorySources=(kind,params)=>read(path(kind),params);
export const getInventorySource=(kind,key,params={})=>read(`${path(kind)}/${id(key)}`,params);
export const createInventorySource=(kind,data)=>{if(data?.payload?.kind!==kind)throw new Error('URL与原件种类必须一致');return write(path(kind),data,'SourceCreate');};
export const reviewInventorySource=(kind,key,data)=>write(`${path(kind)}/${id(key)}/review`,data,'SourceReview');
export const revokeInventorySource=(kind,key,data)=>write(`${path(kind)}/${id(key)}/revoke`,data,'SourceRevoke');
export const getAdminInventorySources=params=>read('ai/admin/inventory-native-sources',params);
export const getAdminInventorySource=key=>read(`ai/admin/inventory-native-sources/${id(key)}`);
export const previewInventorySources=data=>write(`${base}/preview`,data,'CapturePeriod');
export const captureInventoryLegacy=data=>write(`${base}/legacy-capture`,data,'LegacyCaptureRequest');
function state(v,redacted=false){const reviewed=v.reviewed_at!==null;if(reviewed?!supplySourceClock(v.reviewed_at)||v.reviewed_at<v.recorded_at||!supplySourcePositive(v.reviewed_by):v.reviewed_by!==null)return false;if(v.status==='draft'?v.revision!==1||reviewed:['published','rejected'].includes(v.status)?v.revision!==2||!reviewed:v.status!=='revoked'||v.revision!==(reviewed?3:2))return false;if(v.status==='revoked'?!supplySourcePositive(v.revoked_by)||!supplySourceClock(v.revoked_at)||v.revoked_at<(v.reviewed_at||v.recorded_at):v.revoked_by!==null||v.revoked_at!==null)return false;return redacted?v.review_basis_note===null&&v.revoke_reason===null:(reviewed?supplySourceBasis(v.review_basis_note):v.review_basis_note==='')&&(v.status==='revoked'?inventoryRevokeBasis(v.revoke_reason):v.revoke_reason==='');}
function header(v){return v.source_kind==='inventory_observation'?['date_from','date_to','timezone'].every(k=>v[k]===null):period(v);}
function skuValid(s,v){if(!keys(s,['item_kind','item_id','scope','identity'])||['item_kind','item_id','scope'].some(k=>s[k]!==v[k]))return false;const n=v.item_kind==='pharmaceutical'?['name','status','barcode']:['name','status','category','catalog_unit'];return keys(s.identity,n)&&Object.entries(s.identity).every(([k,x])=>k==='status'?x===null||Number.isSafeInteger(x):x===null||typeof x==='string'&&bytes(x)<=4000);}
export function inventorySourceMetadataValid(v,{kind=null,itemKind=null,itemId=null}={}){try{
 const n=Object.keys(schemas.SourceMetadata.properties),x=pick(v,n);
 return inventorySourceSchemaMatches('SourceMetadata',x)&&supplySourceClock(v.recorded_at)&&header(v)&&v.source_id===`inventory_fact:${v.source_record_id}:${v.content_hash.slice(0,12)}`&&(kind===null||v.source_kind===kind)&&(itemKind===null||v.item_kind===itemKind)&&(itemId===null||v.item_id===itemId)&&state({...x,review_basis_note:null,revoke_reason:null},true);
}catch{return false;}}
const legacyKeys={sku:['name','status','stock','price','unit','barcode','category','expiry_date','purchasing_time_legacy','time_basis'],batch:['batch_id','pharmaceutical_id','stock','status','expiry_date','create_time_legacy','update_time_legacy','time_basis'],ledger:['ledger_id','batch_id','pharmaceutical_id','transaction_type','quantity','before_stock','after_stock','create_time_legacy','time_basis'],open_purchase_item:['item_id','purchase_id','item_type','item_id_ref','quantity','unit_price','total_price','expiry_date','received_quantity','order_status','order_create_time_legacy','order_approve_time_legacy','time_basis']},legacyInt=new Set(['status','stock','batch_id','pharmaceutical_id','ledger_id','quantity','before_stock','after_stock','item_id','purchase_id','item_id_ref','received_quantity','order_status']),legacyDecimal=new Set(['price','unit_price','total_price']),legacyScope=['item_kind','item_id','scope','sku','batches','ledger_entries','open_purchase_items'];
function naive(v){try{return typeof v==='string'&&/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}$/.test(v)&&supplySourceClock(v+'Z');}catch{return false;}}
function legacyProjection(kind,p){if(!keys(p,legacyKeys[kind])||p.time_basis!=='legacy_naive_unknown_not_utc_evidence')return false;return Object.entries(p).every(([k,v])=>v===null||legacyInt.has(k)?v===null||Number.isSafeInteger(v):legacyDecimal.has(k)?typeof v==='string'&&v.length<=64&&/^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[Ee][+-]?\d+)?$/.test(v):k.endsWith('_legacy')?naive(v):k==='expiry_date'?day(v):typeof v==='string'&&bytes(v)<=4000);}
export async function verifyInventoryLegacyCapture(v){try{
 if(!keys(v,['schema_version','item_kind','item_id','scope','captured_at','sku','batches','ledger_entries','open_purchase_items','row_count','collection_digest'])||v.schema_version!=='inventory_legacy_capture_v1'||!['pharmaceutical','consumable'].includes(v.item_kind)||!supplySourcePositive(v.item_id)||v.scope!=='hospital_inventory'||!supplySourceClock(v.captured_at)||bytes(v)>4194304||!['batches','ledger_entries','open_purchase_items'].every(k=>Array.isArray(v[k]))||v.row_count!==1+v.batches.length+v.ledger_entries.length+v.open_purchase_items.length||v.row_count>4096||v.item_kind==='consumable'&&(v.batches.length||v.ledger_entries.length))return false;
 for(const[group,kind]of[['sku','sku'],['batches','batch'],['ledger_entries','ledger'],['open_purchase_items','open_purchase_item']]){let previous=0;for(const x of group==='sku'?[v.sku]:v[group]){
  if(!keys(x,['schema_version','record_kind','record_id','item_kind','item_id','scope','projection','projection_hash','original_row_hash','source_id'])||x.schema_version!=='inventory_legacy_capsule_v1'||x.record_kind!==kind||!supplySourcePositive(x.record_id)||x.record_id<=previous||['item_kind','item_id','scope'].some(k=>x[k]!==v[k])||!supportHash(x.original_row_hash)||x.source_id!==`inventory_legacy:${kind}:${x.record_id}:${x.original_row_hash.slice(0,12)}`||!legacyProjection(kind,x.projection)||await supportDigest(x.projection)!==x.projection_hash)return false;
  previous=x.record_id;const p=x.projection;if(kind==='sku'?(x.record_id!==v.item_id||v.item_kind==='pharmaceutical'&&(p.unit!==null||p.category!==null)||v.item_kind==='consumable'&&(p.barcode!==null||p.expiry_date!==null||p.purchasing_time_legacy!==null)):kind==='batch'?p.batch_id!==x.record_id||p.pharmaceutical_id!==v.item_id:kind==='ledger'?p.ledger_id!==x.record_id||p.pharmaceutical_id!==v.item_id:p.item_id!==x.record_id||p.item_id_ref!==v.item_id||p.item_type!==(v.item_kind==='pharmaceutical'?'drug':'consumable')||[2,3].includes(p.order_status))return false;
 }}return await supportDigest(pick(v,legacyScope))===v.collection_digest;
}catch{return false;}}
async function originalProof(v){
 if(!keys(v,[...identity,...governance,'source_id','content_hash','governance_hash','payload','parent_binding'])||!inventorySourceMetadataValid(v)||!state(v)||!inventorySourceRequestValid('SourceCreate',{...pick(v,['item_kind','item_id','scope','unit_definition_id']),expected_unit_content_hash:v.parent_binding?.unit_definition?.content_hash??null,expected_unit_governance_hash:v.parent_binding?.unit_definition?.governance_hash??null,expected_legacy_digest:v.source_kind==='inventory_observation'?v.parent_binding?.legacy_snapshot?.collection_digest??null:null,payload:v.payload}))return false;
 const p=v.payload,b=v.parent_binding;if(!keys(b,['scope','sku','signer','unit_definition','legacy_snapshot'])||b.scope!==v.scope||!skuValid(b.sku,v)||bytes(b)>4194304||bytes(p)>1048576||p.kind!==v.source_kind)return false;
 if(['date_from','date_to','timezone'].some(k=>v[k]!== (Object.hasOwn(p,k)?p[k]:null)))return false;
 const a=p.professional_attestation;if(a.status==='confirmed'?!same(b.signer,{user_id:v.created_by,user_role:'pharmacist'})||a.signer_user_id!==v.created_by:b.signer!==null)return false;
 const u=b.unit_definition,unitIdentity=['record_kind','source_kind','source_record_id','unit_definition_id','schema_version','item_kind','item_id','scope','target','date','day_start_at','day_end_at','observed_at','recorded_at','created_by'];
 if(v.unit_definition_id===null?u!==null:!u||!keys(u,[...unitIdentity,...governance,'source_id','content_hash','governance_hash','payload','parent_binding'])||!await verifySupplyOriginalProof(u)||u.record_kind!=='unit'||u.status!=='published'||['unit_definition_id','item_kind','item_id','scope'].some(k=>u[k]!==v[k]))return false;
 if(quantities(p).some(q=>q.unit_review==='confirmed')||p.legacy_quantity_unit_review==='confirmed'){
  if(!u||u.payload.professional_attestation.status!=='confirmed'||quantities(p).some(q=>q.unit_review==='confirmed'&&q.original_unit_text!==u.payload.original_unit_text))return false;
 }
 if(p.kind==='inventory_observation'){
  const l=b.legacy_snapshot;if(!await verifyInventoryLegacyCapture(l)||['item_kind','item_id','scope'].some(k=>l[k]!==v[k])||l.captured_at>v.recorded_at||p.observed_at!==null&&p.observed_at>v.recorded_at)return false;
  const raw=l.sku.projection,expected={name:raw.name,status:raw.status,...(v.item_kind==='pharmaceutical'?{barcode:raw.barcode}:{category:raw.category,catalog_unit:raw.unit})};if(!same(b.sku.identity,expected)||p.legacy_quantity_unit_review==='confirmed'&&raw.unit!==null&&raw.unit!==u.payload.original_unit_text)return false;
 }else if(b.legacy_snapshot!==null||p.date_from<=supplyLocalDate(v.recorded_at,p.timezone))return false;
 return await supportDigest({...pick(v,identity),payload:p,parent_binding:b})===v.content_hash&&await supportDigest(pick(v,governance))===v.governance_hash;
}
export async function verifyInventorySourceWrapper(v,{auditOnly=false,capture=false,itemKind=null,itemId=null}={}){try{
 if(!inventorySourceSchemaMatches(capture?'CaptureSourceWrapper':'SourceWrapper',v)||!inventorySourceMetadataValid(v,{itemKind,itemId})||bytes(v)>8388608||v.audit_only!==auditOnly||capture&&(auditOnly||['can_record','can_review','can_revoke'].some(k=>v[k])))return false;
 if(!unique(v.exclusion_reasons)||v.exclusion_reasons.some(r=>!reasons.includes(r))||v.parent_current!==!v.exclusion_reasons.some(r=>r!=='source_not_published')||v.eligible!==(v.status==='published'&&v.parent_current)||(v.status!=='published')!==v.exclusion_reasons.includes('source_not_published')||v.can_review&&!(v.status==='draft'&&v.parent_current)||v.can_revoke&&!['draft','published'].includes(v.status))return false;
 const visible=capture?v.eligible:auditOnly||v.eligible||v.status==='draft'&&v.parent_current;
 if(!visible)return hidden.every(k=>v[k]===null)&&state(v,true)&&!v.eligible;
 const proof=pick(v,[...identity,...governance,'source_id','content_hash','governance_hash','payload','parent_binding']);
 return await originalProof(proof)&&v.payload.professional_attestation.status===v.professional_status&&v.payload.professional_attestation.signer_user_id===v.signer_user_id&&v.signed_at===(v.professional_status==='confirmed'?v.recorded_at:null);
}catch{return false;}}
export async function verifyInventorySourceTransition(row,before,action,body){try{
 if(!['publish','reject','revoke'].includes(action)||!inventorySourceRequestValid(action==='revoke'?'SourceRevoke':'SourceReview',body)||action!=='revoke'&&body.decision!==action||!await verifyInventorySourceWrapper(before,{auditOnly:before.audit_only})||!await verifyInventorySourceWrapper(row,{auditOnly:row.audit_only})||row.source_record_id!==before.source_record_id||!same(pick(row,identity),pick(before,identity))||row.content_hash!==before.content_hash||body.expected_revision!==before.revision||body.expected_content_hash!==before.content_hash||row.revision!==before.revision+1)return false;
 const revoke=action==='revoke';if(row.status!==(revoke?'revoked':body.decision==='publish'?'published':'rejected'))return false;
 if(revoke){if(row.reviewed_by!==before.reviewed_by||row.reviewed_at!==before.reviewed_at||row.payload!==null&&row.revoke_reason!==body.basis_note)return false;if(before.review_basis_note===null)return row.payload===null&&row.governance_hash!==before.governance_hash;return await supportDigest({...pick(before,governance),status:'revoked',revision:row.revision,revoked_by:row.revoked_by,revoked_at:row.revoked_at,revoke_reason:body.basis_note})===row.governance_hash;}
 return row.reviewed_by!==null&&row.reviewed_at!==null&&row.review_basis_note===body.basis_note&&await supportDigest({status:row.status,revision:row.revision,reviewed_by:row.reviewed_by,reviewed_at:row.reviewed_at,review_basis_note:body.basis_note,revoked_by:null,revoked_at:null,revoke_reason:''})===row.governance_hash;
}catch{return false;}}
const locator=s=>({...pick(s,['source_kind','source_record_id','item_kind','item_id','scope']),...(s.source_kind==='unit_definition'?{}:pick(s,['date_from','date_to','timezone']))}),member=s=>pick(s,['source_kind','source_record_id','item_kind','item_id','scope','content_hash','governance_hash','status','revision','recorded_at','reviewed_at','revoked_at','eligible','parent_current','professional_status','eligibility_basis']);
export async function verifyInventoryCapture(v){try{
 if(!keys(v,['schema_version','request','as_of','captured_at','sku_binding','unit_definitions','source_records','legacy_snapshot','historical_collection_digest','current_membership_digest','collection_digest'])||v.schema_version!=='inventory_capture_all_sku_v1'||bytes(v)>8388608||!inventorySourceRequestValid('CapturePeriod',v.request)||v.as_of!==v.request.as_of||!supplySourceClock(v.captured_at)||v.captured_at<v.as_of||!await verifyInventoryLegacyCapture(v.legacy_snapshot)||v.legacy_snapshot.captured_at>v.captured_at||!skuValid(v.sku_binding,v.request)||!['unit_definitions','source_records'].every(k=>Array.isArray(v[k]))||v.unit_definitions.length+v.source_records.length>4096)return false;
 const raw=v.legacy_snapshot.sku.projection,expected={name:raw.name,status:raw.status,...(v.request.item_kind==='pharmaceutical'?{barcode:raw.barcode}:{category:raw.category,catalog_unit:raw.unit})};if(raw.status!==0||!same(v.sku_binding.identity,expected)||['item_kind','item_id','scope'].some(k=>v.legacy_snapshot[k]!==v.request[k]))return false;
 const seen=new Set();for(const[unit,group]of[[true,'unit_definitions'],[false,'source_records']]){let previous=null;for(const e of v[group]){const s=e?.source;
  if(!keys(e,['source','locator','locator_hash'])||!s||seen.has(s.source_record_id)||previous!==null&&previous>s.source_record_id||['item_kind','item_id','scope'].some(k=>s[k]!==v.request[k]))return false;
  if(unit?!await verifySupplySourceWrapper(s,{capture:true,kind:'unit',itemKind:v.request.item_kind,itemId:v.request.item_id})||s.source_kind!=='unit_definition'||['audit_only','can_record','can_review','can_revoke'].some(k=>s[k]):!await verifyInventorySourceWrapper(s,{capture:true,itemKind:v.request.item_kind,itemId:v.request.item_id}))return false;
  if(['recorded_at','reviewed_at','revoked_at'].some(k=>s[k]!==null&&s[k]>v.as_of)||s.payload!==null&&!same(s.parent_binding.sku,v.sku_binding)||!same(e.locator,locator(s))||await supportDigest(e.locator)!==e.locator_hash)return false;
  seen.add(s.source_record_id);previous=s.source_record_id;
 }}const hist=await supportDigest({...pick(v,['request','sku_binding','unit_definitions','source_records']),legacy_content:pick(v.legacy_snapshot,legacyScope)}),current=await supportDigest({sku_binding:v.sku_binding,legacy_content_digest:v.legacy_snapshot.collection_digest,members:[...v.unit_definitions,...v.source_records].map(e=>member(e.source))});
 return hist===v.historical_collection_digest&&current===v.current_membership_digest&&await supportDigest({request:v.request,sku_binding:v.sku_binding,historical_collection_digest:hist,current_membership_digest:current})===v.collection_digest;
}catch{return false;}}

export function inventorySourceOptionsValid(v,requested={}){try{
 const names=['items','total','page','page_size','item_kinds','source_kinds','scope','can_record','can_confirm_professional','professional_signer_user_id','can_review','provider_required','unit_sources_path','scope_note'];
 if(!keys(v,names)||!Array.isArray(v.items)||!Number.isSafeInteger(v.total)||v.total<0||!supplySourcePositive(v.page)||!supplySourcePositive(v.page_size)||v.page_size>100||v.items.length>v.page_size||v.items.length>v.total||v.scope!=='hospital_inventory'||!same(v.item_kinds,['pharmaceutical','consumable'])||!same(v.source_kinds,Object.keys(inventorySourceKinds))||v.provider_required!==false||v.unit_sources_path!=='/ai/supply-sources/units'||typeof v.scope_note!=='string'||!['can_record','can_confirm_professional','can_review'].every(k=>typeof v[k]==='boolean')||(v.can_confirm_professional?!supplySourcePositive(v.professional_signer_user_id):v.professional_signer_user_id!==null))return false;
 const kind=requested.item_kind??requested.itemKind??null,id=requested.item_id??requested.itemId??null;if(requested.page!==undefined&&v.page!==requested.page||requested.page_size!==undefined&&v.page_size!==requested.page_size||kind===null&&v.items.length)return false;
 return unique(v.items.map(x=>x.item_kind+':'+x.item_id))&&v.items.every(x=>keys(x,['item_kind','item_id','name','status','scope','identity_hash'])&&v.item_kinds.includes(x.item_kind)&&supplySourcePositive(x.item_id)&&typeof x.name==='string'&&x.status===0&&x.scope===v.scope&&supportHash(x.identity_hash)&&(kind===null||x.item_kind===kind)&&(id===null||x.item_id===id));
}catch{return false;}}
