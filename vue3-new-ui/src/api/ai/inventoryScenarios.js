import request from '@/utils/request';
import {supportCanonical as canonical,supportDigest as digest,supportHash as hash,supportId as uuid} from '@/api/inpatientSupport';
import {decodeGeneratedSchemas,generatedSchemaMatches} from '@/api/sofaSchema';
import {verifyInventoryCapture,inventorySourceBasis,inventoryRevokeBasis} from './inventorySources';
import {supplyDayBounds,supplyLocalDate} from './supplySources';
import packed from './inventoryScenarioSchemas.json';

const schemas=decodeGeneratedSchemas(packed),object=v=>v!==null&&typeof v==='object'&&!Array.isArray(v),same=(a,b)=>canonical(a)===canonical(b),own=(v,k)=>Object.hasOwn(v,k),positive=v=>Number.isSafeInteger(v)&&v>0&&v<=2147483647;
const keys=(v,ks)=>object(v)&&same(Object.keys(v).sort(),[...ks].sort()),pick=(v,ks)=>Object.fromEntries(ks.map(k=>[k,v[k]])),bytes=v=>new TextEncoder().encode(typeof v==='string'?v:canonical(v)).length;
const clock=v=>{try{return typeof v==='string'&&/^[1-9][0-9]{3}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{6}Z$/.test(v)&&new Date(v.slice(0,23)+'Z').toISOString()===v.slice(0,23)+'Z';}catch{return false;}};
const govKeys=['status','revision','reviewed_by','reviewed_at','review_basis_note','revoked_by','revoked_at','revoke_reason'];
const technical=['scenario_id','item_kind','item_id','scope','unit_definition_id','schema_version','as_of','created_at','created_by','content_hash','collection_digest','projection_hash','source_id','status','revision','reviewed_by','reviewed_at','revoked_by','revoked_at','governance_hash'];
const live=[...technical,'snapshot','public_source','local_resolution','source_current','eligible','exclusion_reasons','can_review','can_revoke','review_basis_note','revoke_reason','audit_only','comparison_purpose'];
const frozen=[...technical,'snapshot','public_source','review_basis_note','revoke_reason','frozen_task_view','can_record','can_review','can_revoke','automatic_purchase'];
const periodKeys=['item_kind','item_id','scope','timezone','date_from','date_to','as_of'];
const profileKeys=['daily_constraints','shared_budget','cost_unit','policy_review','policy_basis_note','assumptions','candidate_set_review','candidate_set_basis_note'];
export const inventoryScenarioBasis=v=>inventorySourceBasis(v);
export const inventoryScenarioRevokeBasis=v=>inventoryRevokeBasis(v);
export const inventoryScenarioReferencesValid=v=>keys(v,['inventory_scenario_id'])&&uuid(v.inventory_scenario_id);
export const getInventoryScenarios=(params={}, {auditOnly=false}={})=>request({url:auditOnly?'/ai/admin/inventory-scenarios':'/ai/inventory-scenarios',method:'get',params});
const identity=id=>{if(!uuid(id))throw new Error('库存场景须为规范UUID');return id;};
const write=(url,data,model)=>{if(!inventoryScenarioRequestValid(model,data))throw new Error('须完整核对库存场景原件、明确共同约束及依据');return request({url,method:'post',data:JSON.stringify(data),headers:{'Content-Type':'application/json'},retry:0});};
export const getInventoryScenarioRecord=(id,{auditOnly=false}={})=>request({url:(auditOnly?'/ai/admin/inventory-scenarios/':'/ai/inventory-scenarios/')+identity(id),method:'get',retry:0});
export const previewInventoryScenario=data=>write('/ai/inventory-scenarios/preview',data,'ScenarioPeriodRequest');
export const createInventoryScenario=data=>write('/ai/inventory-scenarios',data,'ScenarioCreate');
export const reviewInventoryScenario=(id,data)=>write(`/ai/inventory-scenarios/${identity(id)}/review`,data,'ScenarioReview');
export const revokeInventoryScenario=(id,data)=>write(`/ai/inventory-scenarios/${identity(id)}/revoke`,data,'ScenarioRevoke');
export const inventoryScenarioFormSchema=name=>own(schemas,name)?structuredClone(schemas[name]):null;
function addDay(date,offset){const d=new Date(date+'T00:00:00.000Z');d.setUTCDate(d.getUTCDate()+offset);return d.toISOString().slice(0,10);}
function periodDates(r){const days=[];for(let d=r.date_from;d<=r.date_to;d=addDay(d,1)){if(days.length>=31)throw new Error('Future domain exceeds31days');supplyDayBounds(d,r.timezone);days.push(d);}return days;}
function allBasis(v){if(Array.isArray(v))return v.every(allBasis);if(!object(v))return true;for(const[k,x]of Object.entries(v)){if((k==='basis_note'||k.endsWith('_basis_note'))&&!inventoryScenarioBasis(x)||!allBasis(x))return false;}return true;}
function tagged(v){if(Array.isArray(v))return v.every(tagged);if(!object(v))return true;if(own(v,'mode')&&own(v,'amount')&&((v.mode==='known')!==(v.amount!==null)||v.amount!==null&&v.amount.value===null))return false;return Object.values(v).every(tagged);}
function selectionClosure(collection,req){try{
 const rows=[...collection.unit_definitions,...collection.source_records].map(r=>r.source),all=new Map(rows.map(s=>[s.source_kind+':'+s.source_record_id,s])),reviews=new Map(req.member_reviews.map(r=>[r.source_kind+':'+r.source_record_id,r]));
 if(all.size!==rows.length||reviews.size!==all.size||[...all.keys()].some(k=>!reviews.has(k)))return false;
 for(const[k,s]of all){const r=reviews.get(k);if(r.expected_content_hash!==s.content_hash||r.expected_governance_hash!==s.governance_hash||r.use==='confirmed'&&(s.status!=='published'||s.payload===null))return false;}
 const unit=all.get('unit_definition:'+req.unit_definition_id);if(!unit||unit.status!=='published'||!unit.eligible||unit.payload===null||unit.professional_status!=='confirmed'||unit.content_hash!==req.expected_unit_content_hash||unit.governance_hash!==req.expected_unit_governance_hash)return false;
 const refs=[['inventory_observation',req.observation],['future_quantity_scenario',req.future_quantity_scenario],...req.candidates.map(r=>['purchase_candidate_plan',r])];
 for(const[kind,ref]of refs){const s=all.get(kind+':'+ref.source_record_id);if(!s||s.status!=='published'||s.payload===null||s.content_hash!==ref.expected_content_hash||s.governance_hash!==ref.expected_governance_hash||!same(pick(s,['item_kind','item_id','scope']),pick(req,['item_kind','item_id','scope']))||kind!=='inventory_observation'&&!same(pick(s.payload,['timezone','date_from','date_to']),pick(req,['timezone','date_from','date_to'])))return false;}
 const applicable=collection.source_records.map(r=>r.source).filter(s=>s.source_kind==='purchase_candidate_plan'&&s.status==='published'&&same(pick(s,['timezone','date_from','date_to']),pick(req,['timezone','date_from','date_to']))).map(s=>s.source_record_id).sort();
 if(!same([...req.candidates.map(r=>r.source_record_id)].sort(),applicable))return false;
 return req.candidates.some(r=>{const p=all.get('purchase_candidate_plan:'+r.source_record_id).payload;return p.orders.length===0&&typeof p.plan_fixed_fee.value==='string'&&/^0(?:\.0{1,6})?$/.test(p.plan_fixed_fee.value);});
}catch{return false;}}
export function inventoryScenarioRequestValid(model,value,preview=null){try{
 if(!generatedSchemaMatches(schemas,model,value)||bytes(value)>8388608)return false;
 if(model==='ScenarioReview')return inventoryScenarioBasis(value.basis_note);
 if(model==='ScenarioRevoke')return inventoryScenarioRevokeBasis(value.basis_note);
 const req=model==='ScenarioCreate'?value.request:value;
 if(!['ScenarioPeriodRequest','ScenarioRequest','ScenarioCreate'].includes(model))return false;
 const days=periodDates(req);if(days.length<1||req.date_from<=supplyLocalDate(req.as_of,req.timezone))return false;
 if(model==='ScenarioPeriodRequest')return true;
 if(!same(req.daily_constraints.map(d=>d.date),days)||!tagged(req)||!allBasis(req)||!req.cost_unit.currency_text.trim()||!req.cost_unit.original_cost_unit_text.trim())return false;
 const ids=[req.observation.source_record_id,req.future_quantity_scenario.source_record_id,...req.candidates.map(r=>r.source_record_id)],members=req.member_reviews.map(r=>r.source_kind+':'+r.source_record_id);
 if(new Set(ids).size!==ids.length||new Set(members).size!==members.length)return false;
 return !preview||same(preview.request,pick(req,periodKeys))&&(model!=='ScenarioCreate'||value.expected_collection_digest===preview.collection_digest)&&selectionClosure(preview,req);
}catch{return false;}}
export async function verifyInventoryScenarioPreview(value,period=null){try{return await verifyInventoryCapture(value)&&inventoryScenarioRequestValid('ScenarioPeriodRequest',value.request)&&(!period||same(value.request,period));}catch{return false;}}
export function inventoryScenarioMetadataValid(row,{itemKind=null,itemId=null}={}){try{
 if(!keys(row,technical)||!uuid(row.scenario_id)||!uuid(row.unit_definition_id)||!['pharmaceutical','consumable'].includes(row.item_kind)||!positive(row.item_id)||row.scope!=='hospital_inventory'||row.schema_version!=='inventory_scenario_private_v1'||!positive(row.created_by)||!clock(row.as_of)||!clock(row.created_at)||row.as_of>row.created_at||!['content_hash','collection_digest','governance_hash'].every(k=>hash(row[k]))||row.source_id!==`inventory_scenario:${row.scenario_id}:${row.content_hash.slice(0,12)}`||itemKind!==null&&row.item_kind!==itemKind||itemId!==null&&row.item_id!==itemId)return false;
 const reviewed=positive(row.reviewed_by)&&clock(row.reviewed_at)&&row.reviewed_at>=row.created_at,revoked=positive(row.revoked_by)&&clock(row.revoked_at)&&row.revoked_at>=(row.reviewed_at||row.created_at);
 if(row.status==='draft')return row.revision===1&&row.reviewed_by===null&&row.reviewed_at===null&&row.revoked_by===null&&row.revoked_at===null&&row.projection_hash===null;
 if(['published','rejected'].includes(row.status))return row.revision===2&&reviewed&&row.revoked_by===null&&row.revoked_at===null&&(row.status==='published'?hash(row.projection_hash):row.projection_hash===null);
 return row.status==='revoked'&&revoked&&(reviewed?row.revision===3&&hash(row.projection_hash):row.revision===2&&row.reviewed_by===null&&row.reviewed_at===null&&row.projection_hash===null);
}catch{return false;}}
async function verifySnapshot(s){try{
 if(!generatedSchemaMatches(schemas,'PrivateSnapshot',s)||bytes(s)>8388608||!inventoryScenarioRequestValid('ScenarioRequest',s.request)||!await verifyInventoryCapture(s.collection)||s.collection_digest!==s.collection.collection_digest||!same(pick(s,['item_kind','item_id','scope','as_of']),pick(s.request,['item_kind','item_id','scope','as_of']))||!same(s.collection.request,pick(s.request,periodKeys))||s.as_of!==s.collection.as_of||s.captured_at!==s.collection.captured_at||s.as_of>s.captured_at||await digest(s.recipe)!==s.recipe_digest||await digest(s.input_policy)!==s.input_policy_digest||!same(s.recipe.input_policy,s.input_policy)||s.recipe.rule_id!=='inventory_declared_candidate_plans_v1'||!same(s.profile,{schema_version:'inventory_profile_private_v1',recipe_digest:s.recipe_digest,input_policy_digest:s.input_policy_digest,...pick(s.request,profileKeys)})||!selectionClosure(s.collection,s.request))return false;
 return true;
}catch{return false;}}
async function localResolution(s,hashValue){const {inventoryOpaqueUuid}=await import('./inventoryResults'),selected=[s.request.observation,s.request.future_quantity_scenario,...s.request.candidates].map(ref=>s.collection.source_records.find(r=>r.source.source_record_id===ref.source_record_id).source),unit=s.collection.unit_definitions.find(r=>r.source.source_record_id===s.request.unit_definition_id).source;
 return{schema_version:'inventory_local_resolution_v1',scenario_id:s.scenario_id,source_content_hash:hashValue,item_kind:s.item_kind,item_id:s.item_id,scope:s.scope,sku_binding:s.collection.sku_binding,unit_definition_id:s.request.unit_definition_id,original_unit_text:unit.payload.original_unit_text,currency_text:s.request.cost_unit.currency_text,original_cost_unit_text:s.request.cost_unit.original_cost_unit_text,facts:await Promise.all(selected.map(async r=>({source_record_id:r.source_record_id,public_fact_id:await inventoryOpaqueUuid(s,'fact',r.source_record_id),source_kind:r.source_kind,source_id:r.source_id}))),candidates:await Promise.all(selected.slice(2).map(async r=>({source_record_id:r.source_record_id,candidate_id:await inventoryOpaqueUuid(s,'candidate',r.source_record_id)})))};
}
function govText(row){return(row.reviewed_by!==null?inventoryScenarioBasis(row.review_basis_note):row.review_basis_note==='')&&(row.status==='revoked'?inventoryScenarioRevokeBasis(row.revoke_reason):row.revoke_reason==='');}
export async function verifyInventoryScenario(row,{itemKind=null,itemId=null,auditOnly=false}={}){try{
 const task=row?.frozen_task_view===true;if(!keys(row,task?frozen:live)||!inventoryScenarioMetadataValid(pick(row,technical),{itemKind,itemId}))return false;
 if(task){if(row.can_record!==false||row.can_review!==false||row.can_revoke!==false||row.automatic_purchase!==false)return false;}else{
  if(typeof row.source_current!=='boolean'||typeof row.eligible!=='boolean'||typeof row.can_review!=='boolean'||typeof row.can_revoke!=='boolean'||row.audit_only!==auditOnly||row.comparison_purpose!=='finite_whole_declared_purchase_candidates_only_not_procurement_execution'||!Array.isArray(row.exclusion_reasons)||new Set(row.exclusion_reasons).size!==row.exclusion_reasons.length||row.exclusion_reasons.some(r=>!['original_collection_changed','scenario_draft','scenario_rejected','scenario_revoked','scenario_period_or_algorithm_changed'].includes(r))||row.eligible&&(!row.source_current||row.status!=='published'||row.exclusion_reasons.length))return false;
  if(row.snapshot===null)return row.public_source===null&&row.local_resolution===null&&row.review_basis_note===null&&row.revoke_reason===null&&!row.eligible&&!row.audit_only&&row.exclusion_reasons.length>0;
 }
 if(!govText(row)||await digest(pick(row,govKeys))!==row.governance_hash||!await verifySnapshot(row.snapshot)||await digest(row.snapshot)!==row.content_hash||!same(pick(row.snapshot,['scenario_id','schema_version','item_kind','item_id','scope','created_by','as_of','collection_digest']),pick(row,['scenario_id','schema_version','item_kind','item_id','scope','created_by','as_of','collection_digest']))||row.snapshot.captured_at!==row.created_at||row.snapshot.request.unit_definition_id!==row.unit_definition_id)return false;
 if(!task&&!same(row.local_resolution,await localResolution(row.snapshot,row.content_hash)))return false;
 const published=row.status==='published'||row.status==='revoked'&&row.revision===3;
 if(!published)return row.public_source===null&&row.projection_hash===null;
 const pub={...pick(row,govKeys),status:'published',revision:2,revoked_by:null,revoked_at:null,revoke_reason:''},pubHash=await digest(pub),{projectInventorySnapshot,verifyInventorySource}=await import('./inventoryResults');
 const projected=await projectInventorySnapshot(row.snapshot,pubHash);
 return same(projected,row.public_source)&&await digest(projected)===row.projection_hash&&await verifyInventorySource(projected,{validateCurrentRecipe:!task&&!auditOnly&&row.eligible});
}catch{return false;}}
