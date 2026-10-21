import request from '@/utils/request';
import {supportCanonical as canonical,supportDigest as digest,supportHash as hash,supportId as uuid} from '@/api/inpatientSupport';
import {decodeGeneratedSchemas,generatedSchemaMatches} from '@/api/sofaSchema';
import packed from './supplySeriesSchemas.json';
import {verifySupplyCapture,supplyDayBounds,supplyLocalDate,supplySourceBasis} from './supplySources';

const schemas=decodeGeneratedSchemas(packed),targets=['recorded_request_quantity','gross_fulfilled_issue_quantity','confirmed_consumed_quantity'];
const object=v=>v!==null&&typeof v==='object'&&!Array.isArray(v),same=(a,b)=>canonical(a)===canonical(b),own=(o,k)=>Object.hasOwn(o,k),positive=v=>Number.isSafeInteger(v)&&v>0&&v<=2147483647;
const keys=(v,ks)=>object(v)&&Object.keys(v).sort().join('|')===[...ks].sort().join('|');
const bytes=v=>new TextEncoder().encode(typeof v==='string'?v:canonical(v)).length;
const clock=v=>typeof v==='string'&&/^[1-9][0-9]{3}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{6}Z$/.test(v)&&new Date(v.slice(0,23)+'Z').toISOString()===v.slice(0,23)+'Z';
const govKeys=['status','revision','reviewed_by','reviewed_at','review_basis_note','revoked_by','revoked_at','revoke_reason'];
const technical=['series_id','item_kind','item_id','scope','unit_definition_id','schema_version','as_of','created_at','created_by','content_hash','collection_digest','projection_hash','source_id','status','revision','reviewed_by','reviewed_at','revoked_by','revoked_at','governance_hash'];
const live=[...technical,'snapshot','public_source','local_resolution','source_current','eligible','exclusion_reasons','can_review','can_revoke','review_basis_note','revoke_reason','audit_only','forecast_purpose'];
const frozen=[...technical,'snapshot','public_source','review_basis_note','revoke_reason','frozen_task_view','can_record','can_review','can_revoke'];
const pick=(v,ks)=>Object.fromEntries(ks.map(k=>[k,v[k]]));
export const supplySeriesTargets=targets;
export const supplySeriesBasis=v=>supplySourceBasis(v);
export const supplySeriesRevokeBasis=v=>supplySeriesBasis(v)&&Array.from(v).length<=1000;
export const supplySeriesReferencesValid=v=>keys(v,['supply_series_id'])&&uuid(v.supply_series_id);
export const getSupplySeries=(params={}, {auditOnly=false}={})=>request({url:auditOnly?'/ai/admin/supply-series':'/ai/supply-series',method:'get',params});
export const getSupplySeriesRecord=(id,{auditOnly=false}={})=>request({url:(auditOnly?'/ai/admin/supply-series/':'/ai/supply-series/')+id,method:'get'});
export const previewSupplySeries=data=>request({url:'/ai/supply-series/preview',method:'post',data});
export const createSupplySeries=data=>request({url:'/ai/supply-series',method:'post',data});
export const reviewSupplySeries=(id,data)=>request({url:`/ai/supply-series/${id}/review`,method:'post',data});
export const revokeSupplySeries=(id,data)=>request({url:`/ai/supply-series/${id}/revoke`,method:'post',data});
export const supplySeriesFormSchema=name=>own(schemas,name)?structuredClone(schemas[name]):null;
function addDay(date,offset){const d=new Date(date+'T00:00:00.000Z');d.setUTCDate(d.getUTCDate()+offset);return d.toISOString().slice(0,10);}
function periodDays(r){const days=[];for(let day=r.date_from;day<=r.date_to;day=addDay(day,1)){if(days.length>=366)throw new Error('Period cap');const [start,end]=supplyDayBounds(day,r.timezone);days.push({date:day,day_start_at:start,day_end_at:end});}return days;}
export function supplySeriesRequestValid(model,value,preview=null){try{
 if(!generatedSchemaMatches(schemas,model,value)||bytes(value)>8388608)return false;
 const period=model==='SeriesCreate'?value.request:value;
 if(['SeriesPeriodRequest','SeriesRequest','SeriesCreate'].includes(model)){
  const days=periodDays(period);for(let lead=1;lead<=14;lead++)supplyDayBounds(addDay(period.date_to,lead),period.timezone);if(days.length<112||period.date_to!==addDay(supplyLocalDate(period.as_of,period.timezone),-1))return false;
  if(model!=='SeriesPeriodRequest'){
   if(!same(period.days.map(d=>d.date),days.map(d=>d.date))||!same(period.target_coverage.map(t=>t.target),targets)||!period.days.every(d=>same(d.selections.map(s=>s.target),targets)))return false;
   for(const p of Object.values(period.parameters)){let n=BigInt(p.numerator),d=BigInt(p.denominator);if(n<=0n||n>d||d>1000n)return false;while(d){[n,d]=[d,n%d];}if(n!==1n)return false;}
   if(new Set(period.member_reviews.map(r=>r.source_kind+':'+r.source_record_id)).size!==period.member_reviews.length)return false;
   if(!period.target_coverage.every(r=>supplySeriesBasis(r.basis_note))||!period.member_reviews.every(r=>supplySeriesBasis(r.basis_note))||!period.days.every(d=>d.selections.every(s=>supplySeriesBasis(s.basis_note)&&(s.source_record_id===null)===(s.absent_reason!==null))))return false;
   if(preview){if(!same(preview.collection.request,pick(period,['item_kind','item_id','scope','timezone','date_from','date_to','as_of']))||model==='SeriesCreate'&&value.expected_capture_digest!==preview.expected_capture_digest||!selectionClosure(preview.collection,period))return false;const groups=new Map(preview.groups.map(g=>[g.date+':'+g.target,g.group_digest]));if(!period.days.every(d=>d.selections.every(r=>r.group_digest===groups.get(d.date+':'+r.target))))return false;}
  }
 }else if(model==='SeriesReview'&&!supplySeriesBasis(value.basis_note)||model==='SeriesRevoke'&&!supplySeriesRevokeBasis(value.basis_note))return false;
 return true;
}catch{return false;}}
export async function supplyCandidateGroups(collection,request){const result=[];for(const day of periodDays(request))for(const target of targets){const members=collection.source_records.filter(r=>r.locator.target===target&&(r.locator.date===day.date||r.locator.day_start_at<day.day_end_at&&r.locator.day_end_at>day.day_start_at)).map(r=>({...pick(r.source,['source_record_id','content_hash','governance_hash','status','eligible']),locator_hash:r.locator_hash})).sort((a,b)=>a.source_record_id<b.source_record_id?-1:1),body={...day,target,members};result.push({...body,group_digest:await digest(body)});}return result;}
function selectionClosure(collection,req){try{
 const records=[...collection.unit_definitions,...collection.source_records].map(r=>r.source),all=new Map(records.map(r=>[r.source_kind+':'+r.source_record_id,r])),reviews=new Map(req.member_reviews.map(r=>[r.source_kind+':'+r.source_record_id,r]));
 if(all.size!==records.length||reviews.size!==all.size||[...all.keys()].some(k=>!reviews.has(k)))return false;
 for(const[k,s]of all){const r=reviews.get(k);if(r.expected_content_hash!==s.content_hash||r.expected_governance_hash!==s.governance_hash||r.selection==='confirmed'&&(s.status!=='published'||!s.eligible||s.payload===null))return false;}
 const unit=all.get('unit_definition:'+req.unit_definition_id);if(!unit||unit.professional_status!=='confirmed'||reviews.get('unit_definition:'+req.unit_definition_id).selection!=='confirmed'||unit.content_hash!==req.expected_unit_content_hash||unit.governance_hash!==req.expected_unit_governance_hash)return false;
 const used=new Set();
 for(const day of req.days)for(const selected of day.selections){const[start,end]=supplyDayBounds(day.date,req.timezone),candidates=collection.source_records.filter(r=>r.locator.target===selected.target&&(r.locator.date===day.date||r.locator.day_start_at<end&&r.locator.day_end_at>start)),eligible=candidates.filter(r=>r.source.status==='published'&&r.source.eligible);if(eligible.length>1&&(selected.source_record_id!==null||selected.absent_reason!=='unresolved_conflict'))return false;if(selected.source_record_id===null)continue;const s=all.get('daily_quantity:'+selected.source_record_id);if(!s||!candidates.some(r=>r.source.source_record_id===s.source_record_id)||reviews.get('daily_quantity:'+s.source_record_id)?.selection!=='confirmed'||!same([s.payload.target,s.payload.date,s.payload.timezone,s.payload.day_start_at,s.payload.day_end_at],[selected.target,day.date,req.timezone,start,end])||used.has(s.source_record_id))return false;used.add(s.source_record_id);}
 return same([...used].sort(),req.member_reviews.filter(r=>r.source_kind==='daily_quantity'&&r.selection==='confirmed').map(r=>r.source_record_id).sort());
}catch{return false;}}
export async function verifySupplyPreview(v,period=null){try{
 if(!keys(v,['schema_version','collection','groups','expected_capture_digest'])||v.schema_version!=='supply_series_preview_v1'||!await verifySupplyCapture(v.collection)||v.expected_capture_digest!==v.collection.collection_digest||period&&!same(v.collection.request,period)||!supplySeriesRequestValid('SeriesPeriodRequest',v.collection.request))return false;
 return same(v.groups,await supplyCandidateGroups(v.collection,v.collection.request))&&bytes(v)<=8388608;
}catch{return false;}}
export function supplySeriesMetadataValid(row,{itemKind=null,itemId=null}={}){try{
 if(!keys(row,technical)||!uuid(row.series_id)||!uuid(row.unit_definition_id)||!['pharmaceutical','consumable'].includes(row.item_kind)||!positive(row.item_id)||row.scope!=='hospital_inventory'||row.schema_version!=='supply_series_private_v1'||!positive(row.created_by)||!clock(row.as_of)||!clock(row.created_at)||row.as_of>row.created_at||!['content_hash','collection_digest','governance_hash'].every(k=>hash(row[k]))||row.source_id!==`supply_series:${row.series_id}:${row.content_hash.slice(0,12)}`||itemKind!==null&&row.item_kind!==itemKind||itemId!==null&&row.item_id!==itemId)return false;
 const reviewed=positive(row.reviewed_by)&&clock(row.reviewed_at)&&row.reviewed_at>=row.created_at,revoked=positive(row.revoked_by)&&clock(row.revoked_at)&&row.revoked_at>=(row.reviewed_at||row.created_at);
 if(row.status==='draft')return row.revision===1&&!reviewed&&row.reviewed_by===null&&row.reviewed_at===null&&row.revoked_by===null&&row.revoked_at===null&&row.projection_hash===null;
 if(['published','rejected'].includes(row.status))return row.revision===2&&reviewed&&row.revoked_by===null&&row.revoked_at===null&&(row.status==='published'?hash(row.projection_hash):row.projection_hash===null);
 return row.status==='revoked'&&revoked&&(reviewed?row.revision===3&&hash(row.projection_hash):row.revision===2&&row.reviewed_by===null&&row.reviewed_at===null&&row.projection_hash===null);
}catch{return false;}}
async function verifySnapshot(s){try{
 if(!generatedSchemaMatches(schemas,'PrivateSnapshot',s)||bytes(s)>8388608||!supplySeriesRequestValid('SeriesRequest',s.request)||!await verifySupplyCapture(s.collection)||s.collection_digest!==s.collection.collection_digest||!same(pick(s,['item_kind','item_id','scope','as_of']),pick(s.request,['item_kind','item_id','scope','as_of']))||!same(s.collection.request,pick(s.request,['item_kind','item_id','scope','timezone','date_from','date_to','as_of']))||s.as_of!==s.collection.as_of||s.captured_at!==s.collection.captured_at||s.as_of>s.captured_at||await digest(s.recipe)!==s.recipe_digest||await digest(s.input_policy)!==s.input_policy_digest||!same(s.recipe.input_policy,s.input_policy)||s.recipe.rule_id!=='supply_recorded_quantity_v1'||!same(s.profile,{parameters:s.request.parameters,recipe_digest:s.recipe_digest,input_policy_digest:s.input_policy_digest})||!selectionClosure(s.collection,s.request))return false;
 const groups=await supplyCandidateGroups(s.collection,s.request),map=new Map(groups.map(g=>[g.date+':'+g.target,g.group_digest]));return s.request.days.every(d=>d.selections.every(r=>r.group_digest===map.get(d.date+':'+r.target)));
}catch{return false;}}
export async function verifySupplySeries(row,{itemKind=null,itemId=null,auditOnly=false}={}){try{
 const task=row?.frozen_task_view===true;if(!keys(row,task?frozen:live)||!supplySeriesMetadataValid(pick(row,technical),{itemKind,itemId}))return false;
 if(task){if(row.can_record!==false||row.can_review!==false||row.can_revoke!==false)return false;}else{
  if(typeof row.source_current!=='boolean'||typeof row.eligible!=='boolean'||typeof row.can_review!=='boolean'||typeof row.can_revoke!=='boolean'||row.audit_only!==auditOnly||row.forecast_purpose!=='recorded_request_gross_fulfilled_issue_confirmed_consumption_not_latent_demand_or_purchase_decision'||!Array.isArray(row.exclusion_reasons)||new Set(row.exclusion_reasons).size!==row.exclusion_reasons.length||row.exclusion_reasons.some(r=>!['original_collection_changed','series_draft','series_rejected','series_revoked','series_period_or_algorithm_changed'].includes(r))||row.eligible&&(!row.source_current||row.status!=='published'||row.exclusion_reasons.length))return false;
  if(row.snapshot===null)return row.public_source===null&&row.local_resolution===null&&row.review_basis_note===null&&row.revoke_reason===null&&!row.eligible&&!row.audit_only&&row.exclusion_reasons.length>0;
 }
 if(!verifyGovText(row)||await digest(pick(row,govKeys))!==row.governance_hash||!await verifySnapshot(row.snapshot)||await digest(row.snapshot)!==row.content_hash||!same(pick(row.snapshot,['series_id','schema_version','item_kind','item_id','scope','created_by','as_of','collection_digest']),pick(row,['series_id','schema_version','item_kind','item_id','scope','created_by','as_of','collection_digest']))||row.snapshot.captured_at!==row.created_at||row.snapshot.request.unit_definition_id!==row.unit_definition_id)return false;
 const s=row.snapshot;
 if(!task){const unit=s.collection.unit_definitions.find(r=>r.source.source_record_id===s.request.unit_definition_id)?.source,resolution={schema_version:'supply_local_resolution_v1',series_id:s.series_id,source_content_hash:row.content_hash,item_kind:s.item_kind,item_id:s.item_id,scope:s.scope,sku_binding:s.collection.sku_binding,unit_definition_id:s.request.unit_definition_id,original_unit_text:unit?.payload?.original_unit_text};if(!same(row.local_resolution,resolution))return false;}
 const published=row.status==='published'||row.status==='revoked'&&row.revision===3;
 if(!published)return row.public_source===null&&row.projection_hash===null;
 const pub={...pick(row,govKeys),status:'published',revision:2,revoked_by:null,revoked_at:null,revoke_reason:''},gov=await digest(pub),{projectSupplySnapshot,verifySupplySource}=await import('./supplyResults');
 const projected=await projectSupplySnapshot(s,gov);
 return same(projected,row.public_source)&&await digest(projected)===row.projection_hash&&await verifySupplySource(projected,{validateCurrentRecipe:!task&&!auditOnly&&row.eligible});
}catch{return false;}}
function verifyGovText(row){const reviewed=row.reviewed_by!==null,revoked=row.status==='revoked';return(reviewed?supplySeriesBasis(row.review_basis_note):row.review_basis_note==='')&&(revoked?supplySeriesRevokeBasis(row.revoke_reason):row.revoke_reason==='');}
