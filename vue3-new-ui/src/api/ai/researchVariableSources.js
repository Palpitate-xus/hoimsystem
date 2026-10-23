import request from '@/utils/request';
import registry from './researchVariableSourceSchemas.json';
import columns from './researchVariableSourceColumns.json';
import {decodeGeneratedSchemas,generatedSchemaMatches} from '../sofaSchema';
import {supportCanonical as canonical,supportDigest as digest,supportId as uuid,supportHash as hash} from '../inpatientSupport';
import {documentClock} from './documentEvidence';
import {researchCohortBasis as basis,getResearchScopes,getResearchScope} from './researchCohortSources';
import {verifyResearchRegistryRecord} from './researchCohortProofs';
import {researchVariableWhole as whole,verifyResearchVariableDictionary,verifyResearchVariableCapture,verifyResearchVariableBatchProjection,researchVariableDefinitionValid} from './researchVariableProofs';
import {decodeResearchVariableResponse} from './researchVariableTasks';

const schemas=decodeGeneratedSchemas(registry),base='/ai/research-variables',object=v=>v!==null&&typeof v==='object'&&!Array.isArray(v),same=(a,b)=>canonical(a)===canonical(b),keys=(v,n)=>object(v)&&same(Object.keys(v).sort(),[...n].sort());
const pick=(v,n)=>Object.fromEntries(n.map(k=>[k,v[k]])),positive=v=>Number.isSafeInteger(v)&&v>0&&v<=2147483647,statuses=['draft','published','rejected','revoked'];
const ordered=v=>Array.isArray(v)&&same(v,[...new Set(v)].sort((a,b)=>typeof a==='number'?a-b:a<b?-1:a>b?1:0));
export const researchVariableSourceBasis=basis;
export const researchVariableSourceSchema=name=>Object.hasOwn(schemas,name)?structuredClone(schemas[name]):null;
export function researchVariableSourceRequestValid(name,value){try{
 if(!Object.hasOwn(schemas,name)||!generatedSchemaMatches(schemas,name,value)||!whole(value))return false;
 if(name==='DictionaryCreate')return basis(value.purpose)&&basis(value.basis_note)&&ordered(value.variables.map(v=>v.variable_key))&&value.variables.every(researchVariableDefinitionValid);
 if(['BatchCapture','BatchCreate'].includes(name))return ordered(value.patient_ids)&&(name!=='BatchCreate'||basis(value.basis_note));
 return ['SourceReview','SourceRevoke','DefinitionReview'].includes(name)?basis(value.basis_note,name==='SourceRevoke'?1000:4000):name==='ScopeReference';
}catch{return false;}}
function kind(value){if(!['dictionary','batch'].includes(value))throw Error('须明确变量字典或完整批次');return value;}
const segment=value=>{if(!uuid(value))throw Error('来源须为实际规范UUID');return value;};
const routeKind=value=>kind(value)==='dictionary'?'dictionaries':'batches';
export function researchVariableSourceMetadataValid(v,{recordKind=v?.record_kind,technical=false,scopeReference=null,recordId=null}={}){try{
 if(!['dictionary','batch'].includes(recordKind)||typeof technical!=='boolean'||!whole(v))return false;
 const pk=recordKind==='dictionary'?'dictionary_id':'batch_id',extra=columns[recordKind==='dictionary'?'DICTIONARY_COLUMNS':'BATCH_COLUMNS'];
 if(!keys(v,[pk,...columns.COMMON_COLUMNS,...extra,'schema_version','record_kind','record_id','technical_only','body_included','detail_required','original','review_basis_note','revoke_reason',...(recordKind==='dictionary'?['definition_review_basis']:[])])||v.schema_version!=='research_variable_source_metadata_v1'||v.record_kind!==recordKind||v.record_id!==v[pk]||!uuid(v[pk])||recordId!==null&&v[pk]!==recordId||v.technical_only!==technical||v.body_included!==false||v.detail_required!==true||v.original!==null||v.review_basis_note!==null||v.revoke_reason!==null||recordKind==='dictionary'&&v.definition_review_basis!==null)return false;
 if(!uuid(v.scope_id)||!['content_hash','scope_content_hash','scope_governance_hash'].every(k=>hash(v[k]))||!positive(v.created_by)||!positive(v.created_event_id)||!positive(v.last_event_id)||!documentClock(v.created_at)||!statuses.includes(v.status))return false;
 const reviewed=v.reviewed_by!==null,revoked=v.revoked_by!==null;
 if(v.status==='draft'?(v.revision!==1||reviewed||revoked):v.status==='revoked'?(!revoked||v.revision!==(reviewed?3:2)):(v.revision!==2||!reviewed||revoked))return false;
 for(const prefix of ['reviewed','revoked'])if(v[prefix+'_by']===null?v[prefix+'_at']!==null:!positive(v[prefix+'_by'])||!documentClock(v[prefix+'_at'])||v[prefix+'_at']<v.created_at)return false;
 if(reviewed&&revoked&&v.revoked_at<v.reviewed_at||scopeReference!==null&&(!researchVariableSourceRequestValid('ScopeReference',scopeReference)||!same(pick(v,Object.keys(scopeReference)),scopeReference)))return false;
 if(recordKind==='batch')return uuid(v.dictionary_id)&&['dictionary_content_hash','dictionary_governance_hash','projection_hash','collection_digest','member_manifest_hash'].every(k=>hash(v[k]));
 const by=v.definition_reviewed_by,at=v.definition_reviewed_at;
 return ['unknown','recorded_reviewed','not_confirmed'].includes(v.definition_review_status)&&(v.definition_review_status==='unknown'?by===null&&at===null:positive(by)&&by!==v.created_by&&documentClock(at)&&at>=v.created_at&&(!reviewed||at<=v.reviewed_at));
}catch{return false;}}
export function researchVariableSourceDirectoryValid(v,{recordKind,technical=false,scopeReference=null,scopeId=null,status=null,page=1,size=20}={}){try{
 if(!keys(v,['schema_version','items','page','size','total','metadata_page_not_complete_source'])||v.schema_version!=='research_variable_source_directory_v1'||v.metadata_page_not_complete_source!==true||v.page!==page||v.size!==size||!Number.isSafeInteger(v.total)||v.total<0||!Array.isArray(v.items)||v.items.length!==Math.min(size,Math.max(0,v.total-(page-1)*size))||new Set(v.items.map(x=>x.record_id)).size!==v.items.length)return false;
 let previous=null;for(const row of v.items){if(!researchVariableSourceMetadataValid(row,{recordKind,technical,scopeReference})||scopeId!==null&&row.scope_id!==scopeId||status!==null&&row.status!==status||previous&&(previous.created_at<row.created_at||previous.created_at===row.created_at&&previous.record_id>=row.record_id))return false;previous=row;}return true;
}catch{return false;}}
function validationValid(v,recordKind,metadata){
 const basis=recordKind==='dictionary'?'recorded_literal_definition_review_not_scientific_or_clinical_validation':'current_recorded_fields_and_reviewed_definitions_not_scientific_validation';
 const allowed=recordKind==='dictionary'?['dictionary_not_published','independent_definition_review_unknown_or_not_confirmed','definition_reviewer_not_current']:['batch_not_published','original_capture_or_creator_project_authority_no_longer_current'];
 return keys(v,['eligible','exclusion_reasons','eligibility_basis'])&&v.eligibility_basis===basis&&typeof v.eligible==='boolean'&&Array.isArray(v.exclusion_reasons)&&new Set(v.exclusion_reasons).size===v.exclusion_reasons.length&&v.exclusion_reasons.every(r=>allowed.includes(r))&&v.eligible===(v.exclusion_reasons.length===0)&&(metadata.status==='published')===!v.exclusion_reasons.includes(recordKind+'_not_published')&&(recordKind!=='dictionary'||(metadata.definition_review_status==='recorded_reviewed')===!v.exclusion_reasons.includes('independent_definition_review_unknown_or_not_confirmed'));
}
function metadataMatchesProof(m,p,snapshot=null){
 const i=p.identity,g=p.governance,scope=m.record_kind==='dictionary'?p.payload:snapshot.request;
 if(!same(pick(m,['created_by','created_at','created_event_id']),pick(i,['created_by','created_at','created_event_id']))||!same(pick(m,['status','revision','reviewed_by','reviewed_at','revoked_by','revoked_at']),pick(g,['status','revision','reviewed_by','reviewed_at','revoked_by','revoked_at']))||m.content_hash!==p.content_hash||m.last_event_id!==p.last_event_id||!same(pick(m,['scope_id','scope_content_hash','scope_governance_hash']),pick(scope,['scope_id','scope_content_hash','scope_governance_hash'])))return false;
 if(m.record_kind==='dictionary')return m.dictionary_id===i.dictionary_id&&['definition_review_status','definition_reviewed_by','definition_reviewed_at'].every(k=>m[k]===p.definition_review[k]);
 return m.batch_id===i.batch_id&&m.dictionary_id===i.dictionary_id&&m.projection_hash===p.projection_hash&&m.collection_digest===snapshot.collection_digest&&m.member_manifest_hash===snapshot.member_manifest_hash&&m.dictionary_content_hash===scope.dictionary_content_hash&&m.dictionary_governance_hash===scope.dictionary_governance_hash;
}
function partValid(v,part,recordKind,metadata){return keys(v,['schema_version','metadata','part','current_validation','value'])&&v.schema_version==='research_variable_source_part_v1'&&v.part===part&&same(v.metadata,metadata)&&validationValid(v.current_validation,recordKind,metadata);}
export async function verifyResearchVariableDictionaryPartPair(definition,scope,{expectedDictionaryId=null,current=()=>true}={}){try{
 const metadata=definition?.metadata;if(!current()||!whole(definition)||!whole(scope)||!researchVariableSourceMetadataValid(metadata,{recordKind:'dictionary',recordId:expectedDictionaryId})||!partValid(definition,'definition','dictionary',metadata)||!partValid(scope,'scope','dictionary',metadata)||!same(definition.current_validation,scope.current_validation))return false;
 const proof={...definition.value,parent_binding:scope.value};return await verifyResearchVariableDictionary(proof,{current})&&metadataMatchesProof(metadata,proof)&&current();
}catch{return false;}}
export async function verifyResearchVariableSourcePartPair(source,snapshot,{expectedBatchId=null,current=()=>true}={}){try{
 const metadata=source?.metadata;if(!current()||!whole(source)||!whole(snapshot)||!researchVariableSourceMetadataValid(metadata,{recordKind:'batch',recordId:expectedBatchId})||!partValid(source,'source','batch',metadata)||!partValid(snapshot,'snapshot','batch',metadata)||!same(source.current_validation,snapshot.current_validation))return false;
 return await verifyResearchVariableBatchProjection(snapshot.value,source.value,{expectedBatchId,current})&&metadataMatchesProof(metadata,snapshot.value.proof,snapshot.value.snapshot)&&current();
}catch{return false;}}
const read=(url,params={})=>request({url,method:'get',params,responseType:'arraybuffer',retry:0}).then(decodeResearchVariableResponse);
const write=(url,body,name)=>{if(!researchVariableSourceRequestValid(name,body))throw Error('请完整填写明确项目、原字段、有限窗口及本次人工依据');return request({url,method:'post',data:JSON.stringify(body),headers:{'Content-Type':'application/json'},responseType:'arraybuffer',retry:0}).then(decodeResearchVariableResponse);};
export function getResearchVariableSources(recordKind,{scopeReference=null,technical=false,scopeId=null,status=null,page=1,size=20}={}){
 kind(recordKind);if(typeof technical!=='boolean'||!Number.isSafeInteger(page)||page<1||page>100000||!Number.isSafeInteger(size)||size<1||size>100||status!==null&&!statuses.includes(status)||(technical?scopeReference!==null||scopeId!==null&&!uuid(scopeId):scopeId!==null||!researchVariableSourceRequestValid('ScopeReference',scopeReference)))throw Error('目录须明确项目三锚或独立技术范围及有界分页');
 return read(`${base}/${technical?'technical/':''}${routeKind(recordKind)}`,{...(technical?(scopeId===null?{}:{scope_id:scopeId}):scopeReference),...(status===null?{}:{status}),page,size});
}
export const getResearchVariableSourceMetadata=(recordKind,id,{technical=false}={})=>{kind(recordKind);if(typeof technical!=='boolean')throw Error('技术目录须明确布尔状态');return read(`${base}/${technical?'technical/':''}${routeKind(recordKind)}/${segment(id)}`);};
export const getResearchVariableSourcePart=(recordKind,id,part)=>{kind(recordKind);if(!(recordKind==='dictionary'?['definition','scope']:['source','snapshot']).includes(part))throw Error('须按本件固定完整分件读取');return read(`${base}/${routeKind(recordKind)}/${segment(id)}/parts/${part}`);};
async function readVerified(recordKind,id,{current=()=>true}={}){
 const metadata=await getResearchVariableSourceMetadata(recordKind,id);if(!current()||!researchVariableSourceMetadataValid(metadata,{recordKind,recordId:id}))throw Error('来源元数据无法核对');
 const names=recordKind==='dictionary'?['definition','scope']:['source','snapshot'],parts={};for(const name of names){if(!current())return null;parts[name]=await getResearchVariableSourcePart(recordKind,id,name);}
 const valid=recordKind==='dictionary'?await verifyResearchVariableDictionaryPartPair(parts.definition,parts.scope,{expectedDictionaryId:id,current}):await verifyResearchVariableSourcePartPair(parts.source,parts.snapshot,{expectedBatchId:id,current});
 if(!current())return null;if(!valid||!same(parts[names[0]].metadata,metadata))throw Error('完整来源分件、原件或治理锚无法核对');
 const after=await getResearchVariableSourceMetadata(recordKind,id);if(!current())return null;if(!same(metadata,after))throw Error('读取期间来源已变化，请显式重读');
 return {metadata,currentValidation:parts[names[0]].current_validation,...(recordKind==='dictionary'?{definition:parts.definition.value,scope:parts.scope.value}:{source:parts.source.value,snapshot:parts.snapshot.value})};
}
export const readVerifiedResearchVariableDictionary=(id,options)=>readVerified('dictionary',id,options);
export const readVerifiedResearchVariableBatch=(id,options)=>readVerified('batch',id,options);
export const previewResearchVariableBatch=body=>write(`${base}/batches/preview`,body,'BatchCapture');
export const createResearchVariableDictionary=body=>write(`${base}/dictionaries`,body,'DictionaryCreate');
export const createResearchVariableBatch=body=>write(`${base}/batches`,body,'BatchCreate');
export const reviewResearchVariableDefinition=(id,body)=>write(`${base}/dictionaries/${segment(id)}/definition-review`,body,'DefinitionReview');
export const reviewResearchVariableSource=(recordKind,id,body)=>write(`${base}/${routeKind(recordKind)}/${segment(id)}/review`,body,'SourceReview');
export const revokeResearchVariableSource=(recordKind,id,body)=>write(`${base}/${routeKind(recordKind)}/${segment(id)}/revoke`,body,'SourceRevoke');
export function researchVariableSourceAckValid(v,{recordKind,recordId=null}={}){return keys(v,['schema_version','metadata','fresh_parts_required'])&&v.schema_version==='research_variable_source_ack_v1'&&v.fresh_parts_required===true&&researchVariableSourceMetadataValid(v.metadata,{recordKind,recordId});}
export async function verifyResearchVariablePreview(value,body,{current=()=>true}={}){return researchVariableSourceRequestValid('BatchCapture',body)&&await verifyResearchVariableCapture(value,{current})&&same(value.request,body)&&current();}
const original=b=>b.metadata.record_kind==='dictionary'?b.definition:b.snapshot.proof;
export function researchVariableSourceCreatedValid(bundle,body){try{
 if(bundle.metadata.status!=='draft'||bundle.metadata.revision!==1)return false;
 return bundle.metadata.record_kind==='dictionary'?same(bundle.definition.payload,body)&&bundle.definition.definition_review.definition_review_status==='unknown':same(bundle.snapshot.snapshot.request,Object.fromEntries(Object.entries(body).filter(([k])=>k!=='basis_note')))&&bundle.snapshot.snapshot.basis_note===body.basis_note;
}catch{return false;}}
export function researchVariableSourceTransitionValid(after,before,action,body){try{
 const a=original(after),b=original(before),m=after.metadata,n=before.metadata,kind=n.record_kind;
 if(m.record_kind!==kind||m.record_id!==n.record_id||a.content_hash!==b.content_hash||!same(a.identity,b.identity)||m.last_event_id===n.last_event_id||body.expected_revision!==n.revision)return false;
 if(kind==='dictionary'&&(!same(a.payload,b.payload)||action!=='definition-review'&&!same(a.definition_review,b.definition_review))||kind==='batch'&&!same(after.snapshot.snapshot,before.snapshot.snapshot))return false;
 if(action==='definition-review')return kind==='dictionary'&&n.status==='draft'&&n.definition_review_status==='unknown'&&same(a.governance,b.governance)&&body.expected_content_hash===n.content_hash&&a.definition_review.definition_review_status===body.decision&&a.definition_review.definition_review_basis===body.basis_note;
 const expected=action==='review'?{...b.governance,status:body.decision==='publish'?'published':'rejected',revision:b.governance.revision+1,reviewed_by:a.governance.reviewed_by,reviewed_at:a.governance.reviewed_at,review_basis_note:body.basis_note}:action==='revoke'?{...b.governance,status:'revoked',revision:b.governance.revision+1,revoked_by:a.governance.revoked_by,revoked_at:a.governance.revoked_at,revoke_reason:body.basis_note}:null;
 return expected!==null&&(action==='review'?n.status==='draft':['draft','published'].includes(n.status))&&same(a.governance,expected);
}catch{return false;}}
export {getResearchScopes,getResearchScope};
export async function verifyResearchVariableScope(row,{current=()=>true}={}){return await verifyResearchRegistryRecord(row,{current})&&row.audit_only===false&&row.eligible===true&&row.original.payload.permitted_uses.includes('research_variable_extraction')&&current();}
