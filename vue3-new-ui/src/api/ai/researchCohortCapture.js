import {supportCanonical as canonical,supportDigest as digest,supportHash as hash,supportId as uuid} from '../inpatientSupport';
import {documentClock,documentUtf8} from './documentEvidence';
import {verifyResearchRegistryProof} from './researchCohortProofs';
import {researchCohortRequestValid,researchCohortPolicy} from './researchCohortSources';
import policy from './researchCohortRecipe.json';
const object=v=>v!==null&&typeof v==='object'&&!Array.isArray(v),same=(a,b)=>canonical(a)===canonical(b),keys=(v,n)=>object(v)&&same(Object.keys(v).sort(),[...n].sort()),positive=v=>Number.isSafeInteger(v)&&v>0&&v<=2147483647;
const omit=(v,n)=>Object.fromEntries(Object.entries(v).filter(([k])=>!n.includes(k))),clock=v=>documentClock(v),day=v=>typeof v==='string'&&/^\d{4}-\d{2}-\d{2}$/u.test(v)&&documentClock(v+'T00:00:00.000000Z');
const ordered=(a,b)=>{for(let i=0;i<a.length;i++){if(a[i]===b[i])continue;return a[i]<b[i];}return false;};
function rawValid(family,raw){
 if(!keys(raw,policy.family_columns[family]))return false;
 for(const [field,value]of Object.entries(raw)){
  if(value===null)continue;
  if(researchCohortPolicy.scalar_fields[family]?.includes(field)&&!Number.isSafeInteger(value))return false;
  if(researchCohortPolicy.text_fields[family]?.includes(field)&&typeof value!=='string')return false;
  if(researchCohortPolicy.date_fields[family]?.includes(field)&&(field==='birthday'?!day(value):typeof value!=='string'||!clock(value+'Z')))return false;
  if(field.endsWith('_id')&&!['medical_record_id','record_id','admission_id'].includes(field)&&!positive(value))return false;
  if(['registration_uuid','medical_record_id','record_id','admission_id'].includes(field)&&!uuid(value))return false;
 }
 return true;
}
async function manifestValid(capture,acl,permissions,current){
 const roots=capture.authorization_manifest;if(!Array.isArray(roots))return false;const seen=new Map();let previous=null;
 for(const item of roots){
  if(!current()||!keys(item,['kind','source_record_id','content_hash','governance_hash','metadata'])||!['acl','authorization'].includes(item.kind)||!uuid(item.source_record_id)||!hash(item.content_hash)||!hash(item.governance_hash))return false;
  const locator=[item.kind,item.source_record_id];if(previous&&!ordered(previous,locator))return false;previous=locator;
  const m=item.metadata,pk=item.kind==='acl'?'acl_id':'authorization_id',names=[pk,'content_hash','status','revision','created_at','reviewed_at','revoked_at','valid_from','valid_until',...(item.kind==='acl'?['user_id','permission']:['patient_id','authorization_kind','access_basis','authorization_review_status','authorization_reviewed_by','authorization_reviewed_at'])];
  if(!keys(m,names)||m[pk]!==item.source_record_id||m.content_hash!==item.content_hash||!['draft','published','rejected','revoked'].includes(m.status)||m.revision!==(m.status==='draft'?1:['published','rejected'].includes(m.status)?2:m.reviewed_at!==null?3:2))return false;
  for(const name of ['created_at','reviewed_at','revoked_at','valid_from','valid_until','authorization_reviewed_at'])if(Object.hasOwn(m,name)&&m[name]!==null&&(!clock(m[name])||!['valid_from','valid_until'].includes(name)&&m[name]>capture.captured_at))return false;
  if(!clock(m.created_at)||(m.valid_from===null?m.valid_until!==null:!clock(m.valid_until)||m.valid_from>=m.valid_until))return false;
  if(item.kind==='acl'?(!positive(m.user_id)||!['read_only','read_capture'].includes(m.permission)):(!positive(m.patient_id)||!['permission_recorded','waiver_recorded','unknown','withdrawn','denied'].includes(m.authorization_kind)||!['explicit_project_acl','current_care_or_grant'].includes(m.access_basis)||!['unknown','recorded_reviewed','not_confirmed'].includes(m.authorization_review_status)))return false;
  seen.set(canonical(locator),item);
 }
 for(const proof of [acl,...permissions]){
  const i=proof.identity,item=seen.get(canonical([i.source_kind,i.source_record_id]));if(!item||item.content_hash!==proof.content_hash||item.governance_hash!==proof.governance_hash)return false;
  for(const name of ['status','revision','reviewed_at','revoked_at'])if(item.metadata[name]!==proof.governance[name])return false;
  for(const name of ['created_at','valid_from','valid_until',i.source_kind==='acl'?'user_id':'patient_id'])if(item.metadata[name]!==i[name])return false;
 }
 return current();
}
export async function verifyResearchCapture(value,{current=()=>true}={}){try{
 if(!current()||!keys(value,['schema_version','request','actor_id','scope_original','actor_acl','patient_authorizations','authorization_manifest','supported_columns','records','member_manifest','manifest_hash','captured_at','collection_digest'])||value.schema_version!=='research_cohort_capture_v1'||documentUtf8(canonical(value)).length>policy.max_bytes||!positive(value.actor_id)||!clock(value.captured_at)||!keys(value.request,['scope_id','scope_content_hash','scope_governance_hash']))return false;
 const scope=value.scope_original,acl=value.actor_acl,permissions=value.patient_authorizations;
 if(!await verifyResearchRegistryProof(scope,{kind:'scope',current})||!await verifyResearchRegistryProof(acl,{kind:'acl',current})||!current()||!same(value.request,{scope_id:scope.identity.scope_id,scope_content_hash:scope.content_hash,scope_governance_hash:scope.governance_hash})||acl.identity.user_id!==value.actor_id||acl.identity.permission!=='read_capture'||!same(acl.parent_binding.scope,scope)||!Array.isArray(permissions)||!same(permissions.map(v=>v.identity?.patient_id),scope.payload.patient_ids))return false;
 for(const p of permissions)if(!await verifyResearchRegistryProof(p,{kind:'authorization',current})||!same(p.parent_binding.scope,scope)||!['permission_recorded','waiver_recorded'].includes(p.identity.authorization_kind)||p.authorization_review.authorization_review_status!=='recorded_reviewed')return false;
 for(const p of [scope,acl,...permissions])if(p.identity.valid_from===null||!(p.identity.valid_from<=value.captured_at&&value.captured_at<p.identity.valid_until)||p.governance.status!=='published'||p.governance.reviewed_at>value.captured_at)return false;
 if(!same(value.supported_columns,Object.fromEntries(scope.payload.data_families.map(f=>[f,policy.family_columns[f]])))||!Array.isArray(value.records)||!Array.isArray(value.authorization_manifest)||value.records.length+value.authorization_manifest.length+1>policy.max_roots)return false;
 const manifest=[];let previous=null;
 for(const entry of value.records){
  if(!current()||!keys(entry,['family','patient_id','record_id','original','parent_binding','window_status']))return false;
  const family=entry.family,raw=entry.original,parent=entry.parent_binding;
  if(!Object.hasOwn(value.supported_columns,family)||!rawValid(family,raw)||!scope.payload.patient_ids.includes(entry.patient_id)||raw.patient_id!==entry.patient_id||raw[policy.family_keys[family]]!==entry.record_id||!keys(parent,['kind','status','technical_hash'])||!['patient_bound','unknown_parent','missing_parent','patient_mismatch'].includes(parent.status)||!hash(parent.technical_hash))return false;
  const kind=family==='medical_records'?'registration_uuid':family==='structured_medical_records'?'admission_id':'direct_patient_fk';
  if(parent.kind!==kind||!['unknown_clock','recorded_calendar_in_scope'].includes(entry.window_status))return false;
  if(kind==='direct_patient_fk'&&!same(parent,{kind,status:'patient_bound',technical_hash:await digest({patient_id:entry.patient_id})}))return false;
  if(kind!=='direct_patient_fk'&&raw[kind]===null&&!same(parent,{kind,status:'unknown_parent',technical_hash:await digest({[kind]:null})}))return false;
  const field=policy.family_clocks[family],at=field?raw[field]:null;
  if(field?(entry.window_status!==(at===null?'unknown_clock':'recorded_calendar_in_scope')||at!==null&&!(scope.payload.record_window.date_from<=at.slice(0,10)&&at.slice(0,10)<=scope.payload.record_window.date_to)):entry.window_status!=='recorded_calendar_in_scope')return false;
  const locator=[entry.patient_id,family,String(entry.record_id)];if(previous&&!ordered(previous,locator))return false;previous=locator;
  manifest.push({family,patient_id:entry.patient_id,record_id:entry.record_id,content_hash:await digest(raw),parent_binding_hash:await digest(parent),window_status:entry.window_status});
 }
 if(!current()||!same(value.member_manifest,manifest)||await digest(manifest)!==value.manifest_hash||!await manifestValid(value,acl,permissions,current))return false;
 return await digest(omit(value,['captured_at','collection_digest']))===value.collection_digest&&current();
}catch{return false;}}
export async function evaluateResearchCriteria(capture,criteria,{current=()=>true}={}){
 if(!current()||!researchCohortRequestValid('CaptureRequest',{...capture.request,criteria}))throw new Error('科研条件不闭合');
 const all=values=>values.includes(false)?false:values.includes(null)?null:true,any=values=>values.includes(true)?true:values.includes(null)?null:false,truth=v=>v===null?'unknown':v?'true':'false';
 const outcomes=[];let constructionBytes=0;
 for(const patient_id of capture.scope_original.payload.patient_ids){
  const records=capture.records.filter(r=>r.patient_id===patient_id),leaves=[];
  async function visit(node,path){
   if(!current())throw new Error('科研核对上下文已变化');
   if(['all','any'].includes(node.op)){const results=[];for(let n=0;n<node.children.length;n++)results.push(await visit(node.children[n],path+'.'+n));return node.op==='all'?all(results):any(results);}
   if(node.op==='not'){const value=await visit(node.child,path+'.not');return value===null?null:!value;}
   if(!capture.scope_original.payload.data_families.includes(node.family))throw new Error('谓词超出项目明确范围');
   const candidates=records.filter(r=>r.family===node.family),results=[],evidence=[];
   for(const r of candidates){
    const value=r.original[node.field],item={family:node.family,record_id:r.record_id,field:node.field,original_hash:await digest(r.original),field_hash:await digest(value),start:null,end:null,quote:null,recorded_value:node.op==='recorded_text_contains'?null:value};let result=null;
    if(r.window_status==='unknown_clock'||r.parent_binding.status!=='patient_bound')item.reason='record_scope_or_parent_unknown';
    else if(value===null)item.reason='original_field_missing';
    else{item.reason='recorded_predicate_only';if(node.op==='recorded_scalar_equal')result=value===node.expected;else if(node.op==='recorded_date_compare'){const actual=value.slice(0,10);result=node.comparison==='before'?actual<node.expected:node.comparison==='after'?actual>node.expected:actual===node.expected;}else{const start=value.indexOf(node.literal);result=start>=0;if(result){item.start=Array.from(value.slice(0,start)).length;item.end=item.start+Array.from(node.literal).length;item.quote=Array.from(value).slice(item.start,item.end).join('');}}}
    item.truth=truth(result);constructionBytes+=documentUtf8(canonical(item)).length;if(constructionBytes>policy.max_bytes)throw new Error('完整三值证据超过8MiB，未裁剪');evidence.push(item);results.push(result);
   }
   const result=!candidates.length?null:node.quantifier==='any_record'?any(results):all(results);leaves.push({path,predicate:structuredClone(node),truth:truth(result),reason:!candidates.length?'no_recorded_members':'whole_declared_recorded_family',evidence});return result;
  }
  const value=await visit(criteria.root,'root');outcomes.push({patient_id,truth:truth(value),interpretation:'recorded_criteria_only_not_clinical_eligibility',leaves});
 }
 const result={schema_version:'research_recorded_evaluation_v1',criteria_hash:await digest(criteria),outcomes,limitations:structuredClone(policy.evaluation_limitations)};if(!current()||documentUtf8(canonical(result)).length>policy.max_bytes)throw new Error('科研核对上下文或完整预算无效');return result;
}
