import registry from './researchVariableTaskSchemas.json';
import fixed from './researchVariableTaskFixed.json';
import {decodeGeneratedSchemas,generatedSchemaMatches} from '../sofaSchema';
import {supportCanonical as canonical,supportDigest as digest,supportId as uuid,supportHash as hash} from '../inpatientSupport';
import {documentClock,documentUtf8} from './documentEvidence';
import {researchCohortBasis as basis} from './researchCohortSources';
import {verifyResearchRegistryProof} from './researchCohortProofs';

const schemas=decodeGeneratedSchemas(registry),object=v=>v!==null&&typeof v==='object'&&!Array.isArray(v),same=(a,b)=>canonical(a)===canonical(b);
const keys=(v,n)=>object(v)&&same(Object.keys(v).sort(),[...n].sort()),pick=(v,n)=>Object.fromEntries(n.map(k=>[k,v[k]])),omit=(v,n)=>Object.fromEntries(Object.entries(v).filter(([k])=>!n.includes(k)));
const positive=v=>Number.isSafeInteger(v)&&v>0&&v<=2147483647,bytes=v=>documentUtf8(typeof v==='string'?v:canonical(v)).length,ordered=a=>same(a,[...new Set(a)].sort((a,b)=>a<b?-1:a>b?1:0));
const blank=/[\u0009-\u000d\u001c-\u0020\u0085\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000\ufeff]/gu,meaningful=v=>typeof v==='string'&&v.replace(blank,'').length>0;
const day=v=>typeof v==='string'&&/^\d{4}-\d\d-\d\d$/u.test(v)&&documentClock(v+'T00:00:00.000000Z');
const naive=v=>typeof v==='string'&&/^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{6}$/u.test(v)&&documentClock(v+'Z');
const compare=(a,b)=>{for(let i=0;i<a.length;i++){if(a[i]===b[i])continue;return a[i]<b[i]?-1:1;}return 0;};
export const researchVariableFixed=Object.freeze(structuredClone(fixed));
export const researchVariableSchemaMatches=(name,value)=>Object.hasOwn(schemas,name)&&generatedSchemaMatches(schemas,name,value);
export const researchVariableBytes=bytes;
export function researchVariableWhole(value,limit=fixed.max_wire_bytes){
 let nodes=0,rawBytes=0;const stack=[[value,0]];
 while(stack.length){const[v,depth]=stack.pop();if(++nodes>fixed.max_json_nodes||depth>fixed.max_json_depth)throw new Error('完整科研资料超出结构预算');
  if(typeof v==='string'){rawBytes+=documentUtf8(v).length;if(rawBytes>limit)throw new Error('完整原量UTF8已超过分件预算');continue;}if(v===null||typeof v==='boolean')continue;
  if(typeof v==='number'){if(!Number.isFinite(v)||Number.isInteger(v)&&!Number.isSafeInteger(v))throw new Error('原数值超出浏览器精确域');continue;}
  if(Array.isArray(v)){if(nodes+stack.length+v.length>fixed.max_json_nodes)throw new Error('完整列表超限');for(const x of v)stack.push([x,depth+1]);continue;}
  if(!object(v)||![Object.prototype,null].includes(Object.getPrototypeOf(v)))throw new Error('完整资料须为JSON');
  const entries=Object.entries(v);if(nodes+stack.length+2*entries.length>fixed.max_json_nodes)throw new Error('完整对象超限');
  for(const[k,x]of entries){if(['__proto__','prototype','constructor'].includes(k))throw new Error('原型键不可用');stack.push([k,depth+1],[x,depth+1]);}
 }
 if(bytes(value)>limit)throw new Error('完整科研分件超出UTF8预算，未截断');return true;
}
export function parseResearchVariableJson(raw,limit=fixed.max_wire_bytes){
 if(typeof raw!=='string'||bytes(raw)>limit)throw new Error('完整原UTF8 JSON超限');let at=0,nodes=0;
 const fail=()=>{throw new Error('原JSON含重复键、非法原值或未闭合结构');},ws=()=>{while(at<raw.length&&/[\x20\t\r\n]/u.test(raw[at]))at++;};
 function string(){const start=at++;while(at<raw.length){const c=raw[at++];if(c==='"'){const v=JSON.parse(raw.slice(start,at));documentUtf8(v);return v;}if(c==='\\')at++;}return fail();}
 function read(depth){if(++nodes>fixed.max_json_nodes||depth>fixed.max_json_depth)return fail();ws();const c=raw[at];if(c==='"')return string();
  if(c==='{'||c==='['){const array=c==='[',out=array?[]:Object.create(null),seen=new Set(),end=array?']':'}';at++;ws();if(raw[at]===end){at++;return out;}
   while(at<raw.length){let key;if(!array){if(raw[at]!=='"'||++nodes>fixed.max_json_nodes)return fail();key=string();if(seen.has(key)||['__proto__','prototype','constructor'].includes(key))return fail();seen.add(key);ws();if(raw[at++]!==':')return fail();}const v=read(depth+1);if(array)out.push(v);else out[key]=v;ws();if(raw[at]===end){at++;return out;}if(raw[at++]!==',')return fail();ws();}return fail();}
  for(const[word,v]of [['true',true],['false',false],['null',null]])if(raw.slice(at,at+word.length)===word){at+=word.length;return v;}
  const m=/^-?(?:0|[1-9]\d*)(?:\.\d+)?(?:[eE][+-]?\d+)?/u.exec(raw.slice(at));if(!m)return fail();at+=m[0].length;const v=Number(m[0]);if(!Number.isFinite(v)||Number.isInteger(v)&&!Number.isSafeInteger(v))return fail();return v;
 }
 const value=read(0);ws();if(at!==raw.length)return fail();researchVariableWhole(value,limit);return value;
}
function literal(kind,value,{publicText=false}={}){
 if(value===null)return true;
 if(kind==='verbatim_text')return typeof value==='string'&&documentUtf8(value).length<=fixed.max_wire_bytes;
 if(kind==='original_integer'){
  if(!publicText)return Number.isSafeInteger(value)&&value>=-2147483648&&value<=2147483647;
  if(typeof value!=='string'||!/^(-?[1-9]\d*|0)$/u.test(value)||value.length>21)return false;
  const n=BigInt(value);return n>=BigInt('-9223372036854775808')&&n<=BigInt('9223372036854775807');
 }
 return kind==='original_calendar_date'?day(value):kind==='original_naive_clock'&&naive(value);
}
function variable(v){
 if(!researchVariableSchemaMatches('VariableDefinition',v)||fixed.variable_fields[v.family]?.[v.field]!==v.value_kind||!basis(v.extraction_instruction))return false;
 const staticField=v.family==='patient_demographics';
 return staticField===(v.record_window===null)&&staticField===(v.temporal_policy==='static_subject_field_without_event_clock')&&(v.declared_unit===null||v.value_kind==='verbatim_text')&&(v.record_window===null||day(v.record_window.date_from)&&day(v.record_window.date_to)&&v.record_window.date_from<=v.record_window.date_to&&(Date.parse(v.record_window.date_to+'T00:00:00Z')-Date.parse(v.record_window.date_from+'T00:00:00Z'))/86400000<366);
}
const GOV=['status','revision','reviewed_by','reviewed_at','review_basis_note','revoked_by','revoked_at','revoke_reason'];
function governance(identity,g,manual=null){
 if(!keys(g,GOV)||!['draft','published','rejected','revoked'].includes(g.status))return false;
 const reviewed=g.reviewed_by!==null,revoked=g.revoked_by!==null;
 if(g.status==='draft'?(g.revision!==1||reviewed||revoked):g.status==='revoked'?(!revoked||g.revision!==(reviewed?3:2)):(g.revision!==2||!reviewed||revoked))return false;
 for(const[prefix,present]of [['reviewed',reviewed],['revoked',revoked]]){const by=g[prefix+'_by'],at=g[prefix+'_at'],note=g[prefix==='reviewed'?'review_basis_note':'revoke_reason'];if(present?(!positive(by)||!documentClock(at)||at<identity.created_at||!basis(note,prefix==='revoked'?1000:4000)):(at!==null||note!==''))return false;}
 if(reviewed&&revoked&&g.revoked_at<g.reviewed_at)return false;
 if(manual!==null){if(!keys(manual,['definition_review_status','definition_reviewed_by','definition_reviewed_at','definition_review_basis']))return false;const state=manual.definition_review_status,by=manual.definition_reviewed_by,at=manual.definition_reviewed_at,note=manual.definition_review_basis;if(state==='unknown'){if(by!==null||at!==null||note!=='')return false;}else if(!['recorded_reviewed','not_confirmed'].includes(state)||!positive(by)||by===identity.created_by||!documentClock(at)||at<identity.created_at||reviewed&&at>g.reviewed_at||!basis(note))return false;}
 return true;
}
export async function verifyResearchVariableDictionary(proof,{current=()=>true}={}){try{
 if(!current()||!keys(proof,['schema_version','identity','payload','parent_binding','content_hash','governance','definition_review','last_event_id','governance_hash'])||proof.schema_version!=='research_variable_dictionary_proof_v1'||!researchVariableWhole(proof))return false;
 const i=proof.identity,p=proof.payload,s=proof.parent_binding.scope;
 if(!keys(i,['dictionary_id','scope_id','schema_version','created_by','created_at','created_event_id'])||i.schema_version!=='research_variable_dictionary_original_v1'||!uuid(i.dictionary_id)||!uuid(i.scope_id)||!positive(i.created_by)||!positive(i.created_event_id)||!documentClock(i.created_at)||!positive(proof.last_event_id)||!keys(proof.parent_binding,['scope'])||!await verifyResearchRegistryProof(s,{current})||!researchVariableSchemaMatches('DictionaryCreate',p)||!p.variables.every(variable)||!ordered(p.variables.map(v=>v.variable_key))||!basis(p.purpose)||!basis(p.basis_note)||!governance(i,proof.governance,proof.definition_review))return false;
 if(s.governance.status!=='published'||s.governance.reviewed_at>i.created_at||p.scope_id!==i.scope_id||p.scope_id!==s.identity.scope_id||p.scope_content_hash!==s.content_hash||p.scope_governance_hash!==s.governance_hash)return false;
 for(const v of p.variables)if(!s.payload.data_families.includes(v.family)||v.record_window!==null&&!(s.payload.record_window.date_from<=v.record_window.date_from&&v.record_window.date_to<=s.payload.record_window.date_to))return false;
 return current()&&await digest({identity:i,payload:p,parent_binding:proof.parent_binding})===proof.content_hash&&await digest({dictionary_id:i.dictionary_id,content_hash:proof.content_hash,governance:proof.governance,definition_review:proof.definition_review,last_event_id:proof.last_event_id})===proof.governance_hash&&current();
}catch{return false;}}
async function authorizationManifest(value,current){
 const roots=value.authorization_manifest;if(!Array.isArray(roots))return false;const seen=new Map();let previous=null;
 for(const item of roots){
  if(!current()||!keys(item,['kind','source_record_id','content_hash','governance_hash','metadata'])||!['acl','authorization'].includes(item.kind)||!uuid(item.source_record_id)||!hash(item.content_hash)||!hash(item.governance_hash))return false;
  const loc=[item.kind,item.source_record_id];if(previous&&compare(previous,loc)>=0)return false;previous=loc;
  const m=item.metadata,pk=item.kind==='acl'?'acl_id':'authorization_id',names=[pk,'content_hash','status','revision','created_at','reviewed_at','revoked_at','valid_from','valid_until',...(item.kind==='acl'?['user_id','permission']:['patient_id','authorization_kind','access_basis','authorization_review_status','authorization_reviewed_by','authorization_reviewed_at'])];
  if(!keys(m,names)||m[pk]!==item.source_record_id||m.content_hash!==item.content_hash||!['draft','published','rejected','revoked'].includes(m.status)||m.revision!==(m.status==='draft'?1:['published','rejected'].includes(m.status)?2:m.reviewed_at!==null?3:2))return false;
  for(const name of ['created_at','reviewed_at','revoked_at','valid_from','valid_until','authorization_reviewed_at'])if(Object.hasOwn(m,name)&&m[name]!==null&&(!documentClock(m[name])||!['valid_from','valid_until'].includes(name)&&m[name]>value.captured_at))return false;
  if(!documentClock(m.created_at)||(m.valid_from===null?m.valid_until!==null:!documentClock(m.valid_until)||m.valid_from>=m.valid_until))return false;
  if(item.kind==='acl'?(!positive(m.user_id)||!['read_only','read_capture'].includes(m.permission)):(!positive(m.patient_id)||!['permission_recorded','waiver_recorded','unknown','withdrawn','denied'].includes(m.authorization_kind)||!['explicit_project_acl','current_care_or_grant'].includes(m.access_basis)||!['unknown','recorded_reviewed','not_confirmed'].includes(m.authorization_review_status)||m.authorization_reviewed_by!==null&&!positive(m.authorization_reviewed_by)))return false;
  seen.set(canonical(loc),item);
 }
 for(const p of [value.actor_acl,...value.patient_authorizations]){const i=p.identity,item=seen.get(canonical([i.source_kind,i.source_record_id]));if(!item||item.content_hash!==p.content_hash||item.governance_hash!==p.governance_hash)return false;for(const k of ['status','revision','reviewed_at','revoked_at'])if(item.metadata[k]!==p.governance[k])return false;for(const k of ['created_at','valid_from','valid_until',i.source_kind==='acl'?'user_id':'patient_id'])if(item.metadata[k]!==i[k])return false;}
 return current();
}
export async function verifyResearchVariableCapture(value,{current=()=>true}={}){try{
 const names=['schema_version','purpose','request','actor_id','scope_original','actor_acl','patient_authorizations','authorization_manifest','dictionary_original','records','member_manifest','member_manifest_hash','captured_at','collection_digest',...Object.keys(fixed.policies)];
 if(!current()||!keys(value,names)||value.schema_version!=='research_variable_capture_v1'||value.purpose!=='research_variable_extraction'||!positive(value.actor_id)||!documentClock(value.captured_at)||!researchVariableWhole(value)||Object.entries(fixed.policies).some(([k,v])=>value[k]!==v)||!researchVariableSchemaMatches('BatchCapture',value.request)||!ordered(value.request.patient_ids))return false;
 const scope=value.scope_original,acl=value.actor_acl,dictionary=value.dictionary_original,request=value.request,permissions=value.patient_authorizations;
 if(!await verifyResearchRegistryProof(scope,{current})||!await verifyResearchRegistryProof(acl,{kind:'acl',current})||!await verifyResearchVariableDictionary(dictionary,{current})||!same(pick(request,['scope_id','scope_content_hash','scope_governance_hash']),{scope_id:scope.identity.scope_id,scope_content_hash:scope.content_hash,scope_governance_hash:scope.governance_hash})||!request.patient_ids.every(p=>scope.payload.patient_ids.includes(p))||!same(dictionary.parent_binding.scope,scope)||dictionary.identity.dictionary_id!==request.variable_dictionary_id||dictionary.content_hash!==request.dictionary_content_hash||dictionary.governance_hash!==request.dictionary_governance_hash||dictionary.definition_review.definition_review_status!=='recorded_reviewed'||dictionary.definition_review.definition_reviewed_at>value.captured_at||acl.identity.user_id!==value.actor_id||acl.identity.permission!=='read_capture'||!same(acl.parent_binding.scope,scope)||!Array.isArray(permissions)||!same(permissions.map(p=>p.identity?.patient_id),request.patient_ids))return false;
 for(const p of permissions)if(!await verifyResearchRegistryProof(p,{kind:'authorization',current})||!same(p.parent_binding.scope,scope)||!['permission_recorded','waiver_recorded'].includes(p.identity.authorization_kind)||p.authorization_review.authorization_review_status!=='recorded_reviewed')return false;
 for(const p of [scope,acl,dictionary,...permissions])if(p.governance.status!=='published'||p.governance.reviewed_at>value.captured_at||p.identity.created_at>value.captured_at||p!==dictionary&&(p.identity.valid_from===null||!(p.identity.valid_from<=value.captured_at&&value.captured_at<p.identity.valid_until)))return false;
 if(!Array.isArray(value.records)||value.records.length>8192||!Array.isArray(value.authorization_manifest)||1+permissions.length+value.authorization_manifest.length+2+value.records.length>8192||!await authorizationManifest(value,current))return false;
 const manifest=[];let previous=null;
 for(const row of value.records){
  if(!current()||!keys(row,fixed.record_keys)||!positive(row.patient_id)||!request.patient_ids.includes(row.patient_id)||(row.family==='patient_demographics'?row.record_id!==row.patient_id:!uuid(row.record_id))||!literal('original_naive_clock',row.recorded_clock))return false;
  const clockName=fixed.family_clocks[row.family],state=!clockName?'static_subject_without_event_clock':row.recorded_clock===null?'unknown_record_clock':'recorded_naive_calendar_in_variable_window';
  if(!clockName&&row.recorded_clock!==null||row.window_status!==state||!keys(row.lifecycle_original,fixed.lifecycle[row.family]||[]))return false;
  for(const[k,v]of Object.entries(row.lifecycle_original))if(!literal(k==='status'?'original_integer':'original_naive_clock',v))return false;
  const active=dictionary.payload.variables.filter(v=>v.family===row.family&&(v.record_window===null||row.recorded_clock===null||v.record_window.date_from<=row.recorded_clock.slice(0,10)&&row.recorded_clock.slice(0,10)<=v.record_window.date_to));
  if(!active.length||!Array.isArray(row.variables)||active.length!==row.variables.length)return false;const repeated=new Map();
  for(let n=0;n<active.length;n++){const v=active[n],f=row.variables[n];if(!keys(f,['variable_key','field','value_kind','record_window','literal'])||!same(omit(f,['literal']),pick(v,['variable_key','field','value_kind','record_window']))||!literal(v.value_kind,f.literal)||v.field===clockName&&f.literal!==row.recorded_clock||Object.hasOwn(row.lifecycle_original,v.field)&&f.literal!==row.lifecycle_original[v.field]||repeated.has(v.field)&&repeated.get(v.field)!==f.literal)return false;repeated.set(v.field,f.literal);}
  const parent=row.parent_binding,kind=row.family==='medical_records'?'registration_uuid':row.family==='structured_medical_records'?'admission_id':'direct_patient_fk';
  if(!keys(parent,['kind','status','technical_hash'])||parent.kind!==kind||!['patient_bound','unknown_parent','missing_parent','patient_mismatch'].includes(parent.status)||!hash(parent.technical_hash)||kind==='direct_patient_fk'&&!same(parent,{kind,status:'patient_bound',technical_hash:await digest({patient_id:row.patient_id})})||parent.status==='unknown_parent'&&parent.technical_hash!==await digest({[kind]:null}))return false;
  const loc=[row.patient_id,row.family,String(row.record_id)];if(previous&&compare(previous,loc)>=0)return false;previous=loc;
  manifest.push({patient_id:row.patient_id,family:row.family,record_id:row.record_id,content_hash:await digest(row)});
 }
 return current()&&same(manifest,value.member_manifest)&&await digest(manifest)===value.member_manifest_hash&&await digest(omit(value,['captured_at','collection_digest']))===value.collection_digest&&current();
}catch{return false;}}
export async function verifyResearchVariableSource(source,{expectedHash=null,validateCurrentRecipe=true,current=()=>true}={}){try{
 if(!current()||!researchVariableWhole(source)||!researchVariableSchemaMatches('VariableTaskSource',source)||!same(source.limitations,fixed.limitations)||new Set(source.member_tokens).size!==source.member_tokens.length||source.source_id!==`research_variables:${source.source_id.split(':')[1]}:${source.content_hash.slice(0,12)}`||!uuid(source.source_id.split(':')[1])||validateCurrentRecipe&&!same(source.recipe,fixed.source_recipe))return false;
 if(!source.variables.every(variable)||!ordered(source.variables.map(v=>v.variable_key)))return false;
 const variables=new Map(source.variables.map(v=>[v.variable_key,v])),records=new Set(),docs=new Map(source.documents.map(d=>[d.field_token,d]));if(docs.size!==source.documents.length)return false;
 const used=[];for(const row of source.records){const staticField=row.family==='patient_demographics',expectedWindow=staticField?'static_subject_without_event_clock':row.recorded_clock===null?'unknown_record_clock':'recorded_naive_calendar_in_variable_window';if(records.has(row.record_token)||!source.member_tokens.includes(row.member_token)||new Set(row.field_tokens).size!==row.field_tokens.length||!literal('original_naive_clock',row.recorded_clock)||!keys(row.lifecycle_original,fixed.lifecycle[row.family]||[])||row.window_status!==expectedWindow||staticField&&(row.recorded_clock!==null||row.parent_status!=='patient_bound'))return false;for(const[k,v]of Object.entries(row.lifecycle_original))if(v!==null&&(k==='status'?!Number.isSafeInteger(v):!naive(v)))return false;records.add(row.record_token);const names=[];
  for(const token of row.field_tokens){const d=docs.get(token),v=d&&variables.get(d.variable_key);if(!d||d.member_token!==row.member_token||d.record_token!==row.record_token||!v||v.family!==row.family||v.value_kind!==d.value_kind||!literal(d.value_kind,d.literal,{publicText:true})||v.record_window!==null&&row.recorded_clock!==null&&!(v.record_window.date_from<=row.recorded_clock.slice(0,10)&&row.recorded_clock.slice(0,10)<=v.record_window.date_to))return false;names.push(d.variable_key);used.push(token);}if(!ordered(names))return false;
 }
 return same(used,source.documents.map(d=>d.field_token))&&await digest(source.documents)===source.documents_hash&&(expectedHash===null||hash(expectedHash)&&await digest(source)===expectedHash)&&current();
}catch{return false;}}
// HMACs are server-frozen opaque identities. This checks their consistent
// bijections and every ordered original literal, without exporting the DB key.
export async function verifyResearchVariablePrivateScope(value,source,binding,{current=()=>true,validateCurrentRecipe=true}={}){try{
 if(!current()||!keys(value,['snapshot','proof'])||!researchVariableWhole(value)||await digest(value)!==binding.private_scope_hash||bytes(value)!==binding.private_scope_bytes||!await verifyResearchVariableSource(source,{expectedHash:binding.source_projection_hash,validateCurrentRecipe,current}))return false;
 const s=value.snapshot,p=value.proof,c=s.capture,r=s.request;
 if(!keys(s,fixed.snapshot_keys)||s.schema_version!=='research_variable_batch_original_v1'||!keys(p,['schema_version','identity','content_hash','governance','governance_hash','projection_hash','last_event_id'])||p.schema_version!=='research_variable_batch_proof_v1'||!keys(p.identity,['schema_version','batch_id','scope_id','dictionary_id','created_by','created_at','created_event_id'])||p.identity.schema_version!=='research_variable_batch_identity_v1'||!same(omit(p.identity,['schema_version']),pick(s,['batch_id','scope_id','dictionary_id','created_by','created_at','created_event_id']))||!positive(s.created_by)||!positive(s.created_event_id)||!documentClock(s.created_at)||!uuid(s.batch_id)||!uuid(s.scope_id)||!uuid(s.dictionary_id)||!basis(s.basis_note)||!hash(s.identity_key_hash)||!governance(p.identity,p.governance)||!await verifyResearchVariableCapture(c,{current}))return false;
 if(!same(s.request,c.request)||s.created_by!==c.actor_id||s.created_at<c.captured_at||s.scope_id!==r.scope_id||s.dictionary_id!==r.variable_dictionary_id||s.collection_digest!==c.collection_digest||s.member_manifest_hash!==c.member_manifest_hash||s.authorization_binding_hash!==await digest(pick(c,['scope_original','actor_acl','patient_authorizations','authorization_manifest','dictionary_original']))||!same(s.recipe,source.recipe)||await digest(s)!==p.content_hash||p.content_hash!==binding.batch_content_hash||p.governance.status!=='published'||p.governance.revision!==2||p.governance_hash!==binding.batch_governance_hash||p.last_event_id!==binding.batch_last_event_id||s.created_event_id!==binding.batch_created_event_id||p.governance_hash!==await digest({batch_id:s.batch_id,content_hash:p.content_hash,governance:p.governance,last_event_id:p.last_event_id})||p.projection_hash!==binding.source_projection_hash)return false;
 const definition=c.dictionary_original;
 if(definition.identity.dictionary_id!==binding.dictionary_id||definition.content_hash!==binding.dictionary_content_hash||definition.governance_hash!==binding.dictionary_governance_hash||definition.identity.created_event_id!==binding.dictionary_created_event_id||definition.last_event_id!==binding.dictionary_last_event_id||s.collection_digest!==binding.collection_digest||s.member_manifest_hash!==binding.member_manifest_hash||s.batch_id!==binding.batch_id||s.scope_id!==binding.request_authorization.scope_id||source.content_hash!==p.content_hash||source.governance_hash!==p.governance_hash||source.captured_at!==c.captured_at||!same(source.variables,definition.payload.variables)||source.external_model_use!==c.scope_original.payload.external_model_use||source.records.length!==c.records.length||source.member_tokens.length!==r.patient_ids.length)return false;
 const members=new Map(r.patient_ids.map((id,n)=>[id,source.member_tokens[n]])),recordIds=new Map(),fields=new Map();let cursor=0;
 for(let n=0;n<c.records.length;n++){const row=c.records[n],pub=source.records[n],loc=canonical([row.patient_id,row.family,row.record_id]);if(recordIds.has(loc)&&recordIds.get(loc)!==pub.record_token)return false;recordIds.set(loc,pub.record_token);
  if(pub.member_token!==members.get(row.patient_id)||!same(pick(pub,['family','recorded_clock','window_status','lifecycle_original']),pick(row,['family','recorded_clock','window_status','lifecycle_original']))||pub.parent_status!==row.parent_binding.status||pub.field_tokens.length!==row.variables.length)return false;
  for(let j=0;j<row.variables.length;j++){const original=row.variables[j],doc=source.documents[cursor++],token=pub.field_tokens[j],rawId=canonical([loc,original.field,original.variable_key]);if(fields.has(rawId)&&fields.get(rawId)!==token)return false;fields.set(rawId,token);
   const expected={member_token:members.get(row.patient_id),record_token:pub.record_token,field_token:token,variable_key:original.variable_key,value_kind:original.value_kind,literal:typeof original.literal==='number'?String(original.literal):original.literal};if(!same(doc,expected))return false;
  }
 }
 return cursor===source.documents.length&&current();
}catch{return false;}}
export async function verifyResearchVariableResult(result,source,instructionsDigest,{current=()=>true}={}){try{
 if(!current()||!hash(instructionsDigest)||!researchVariableWhole(result)||!researchVariableSchemaMatches('VariableGenerationResult',result)||!await verifyResearchVariableSource(source,{current}))return false;
 const d=result.research_variable_extraction;if(d.task_version!==fixed.task_version||d.source_id!==source.source_id||d.source_projection_hash!==await digest(source)||d.documents_hash!==source.documents_hash||d.instructions_digest!==instructionsDigest)return false;
 const docs=new Map(source.documents.map(row=>[row.field_token,row])),spans=new Map();
 for(const row of d.literal_draft.candidates){const doc=docs.get(row.field_token);if(!doc||!same(pick(row,['member_token','record_token','variable_key','value_kind']),pick(doc,['member_token','record_token','variable_key','value_kind']))||doc.literal===null||row.start>=row.end||Array.from(doc.literal).slice(row.start,row.end).join('')!==row.quote||Array.from(row.quote).length!==row.end-row.start||!meaningful(row.quote))return false;
  if(row.value_kind!=='verbatim_text'&&(row.start!==0||row.end!==Array.from(doc.literal).length||row.classification!=='value_quote_candidate'))return false;
  const before=spans.get(row.field_token)||[];if(before.some(([a,b])=>row.start<b&&a<row.end))return false;before.push([row.start,row.end]);spans.set(row.field_token,before);
 }
 const explanation=structuredClone(fixed.explanation);explanation.summary=explanation.summary.replace('{count}',String(d.literal_draft.candidates.length));for(const s of explanation.sections)s.source_ids=s.source_ids.map(id=>id.replace('{source_id}',source.source_id));
 return current()&&same(result,{...explanation,research_variable_extraction:d});
}catch{return false;}}
