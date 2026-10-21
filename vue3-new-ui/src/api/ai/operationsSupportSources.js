import request from '@/utils/request';
import {operationsCanonical as canonical,operationsDigest as digest,operationsTextHash as textHash,operationsId as uuid,operationsHash as hash,operationsSame as same,operationsKeys as keys,operationsPick as pick,operationsPositive as positive,operationsClock as clock,operationsSchema as schema,operationsWhole as whole,operationsBytes as bytes,operationsScalar as scalar,decodeOperationsPart,decodeOperationsResponse} from './operationsSupportCore';
export {operationsFormSchema as operationsSupportFormSchema} from './operationsSupportCore';
const BASE='/ai/operations-support',MAX=8388608;
export const operationsSourceKinds=Object.freeze(['diagnostic_log','runbook','reference_document']);
const originalKeys=['original_id','content_hash','raw_text_sha256','raw_bytes_length','codepoint_length','captured_by','captured_at','creation_event_id','status','revision','revoked_at','revocation_event_id'];
const releaseKeys=['release_id','original_id','original_content_hash','original_captured_by','content_hash','created_by','recorded_at','creation_event_id','status','revision','review_decision','privacy_reviewed','faithfulness_reviewed','applicability_reviewed','model_processing_allowed','reviewed_by','reviewed_at','review_event_id','published_review_hash','revoked_at','revocation_event_id'];
const caseKeys=['case_id','requested_by','assembled_at','member_bindings_hash','private_hash','public_hash','source_count','creation_event_id','status','revision','revoked_at','revocation_event_id','source_accessible','model_processing_permission'];
const originalCreation=['original_id','content_hash','raw_text_sha256','raw_bytes_length','codepoint_length','captured_by','captured_at'];
const releaseCreation=['release_id','original_id','original_content_hash','original_captured_by','content_hash','created_by','recorded_at'];
const nullable=(value,check)=>value===null||check(value);
function activeState(value,time){
 return ['active','revoked'].includes(value.status)&&value.revision===(value.status==='active'?1:2)&&(value.status==='active'?(value.revoked_at===null&&value.revocation_event_id===null):(clock(value.revoked_at)&&value.revoked_at>=time&&positive(value.revocation_event_id)));
}
export function verifyOperationsOriginalMetadata(value){try{
 return keys(value,originalKeys)&&uuid(value.original_id)&&[value.content_hash,value.raw_text_sha256].every(hash)&&positive(value.captured_by)&&positive(value.creation_event_id)&&clock(value.captured_at)&&positive(value.raw_bytes_length)&&value.raw_bytes_length<=4194304&&positive(value.codepoint_length)&&value.codepoint_length<=value.raw_bytes_length&&activeState(value,value.captured_at)&&whole(value);
}catch{return false;}}
export function verifyOperationsReleaseMetadata(value){try{
 if(!keys(value,releaseKeys)||![value.release_id,value.original_id].every(uuid)||![value.content_hash,value.original_content_hash].every(hash)||![value.original_captured_by,value.created_by,value.creation_event_id].every(positive)||!clock(value.recorded_at)||!['draft','published','rejected','revoked'].includes(value.status)||!['privacy_reviewed','faithfulness_reviewed','applicability_reviewed','model_processing_allowed'].every(k=>value[k]===null||Number.isInteger(value[k])&&[0,1].includes(value[k]))||!nullable(value.reviewed_by,positive)||!nullable(value.review_event_id,positive)||!nullable(value.reviewed_at,clock)||!nullable(value.published_review_hash,hash)||!whole(value))return false;
 const reviewed=value.reviewed_by!==null,revoked=value.status==='revoked';
 if(reviewed!==Boolean(value.review_event_id)||reviewed!==(value.reviewed_at!==null)||reviewed&&value.reviewed_at<value.recorded_at||value.reviewed_by===value.created_by||value.reviewed_by===value.original_captured_by)return false;
 if(revoked?(!clock(value.revoked_at)||value.revoked_at<(value.reviewed_at??value.recorded_at)||!positive(value.revocation_event_id)||value.revision!==(reviewed?3:2)):(value.revoked_at!==null||value.revocation_event_id!==null||value.revision!==(reviewed?2:1)))return false;
 if(!reviewed)return ['draft','revoked'].includes(value.status)&&value.review_decision===null&&value.published_review_hash===null&&['privacy_reviewed','faithfulness_reviewed','applicability_reviewed','model_processing_allowed'].every(k=>value[k]===null);
 const accepted=value.review_decision==='published';
 return ['published','rejected'].includes(value.review_decision)&&(accepted?(value.privacy_reviewed===1&&value.faithfulness_reviewed===1&&value.applicability_reviewed===1&&[0,1].includes(value.model_processing_allowed)&&hash(value.published_review_hash)&&['published','revoked'].includes(value.status)):(value.model_processing_allowed===0&&value.published_review_hash===null&&['privacy_reviewed','faithfulness_reviewed','applicability_reviewed'].every(k=>[0,1].includes(value[k]))&&!(value.privacy_reviewed===1&&value.faithfulness_reviewed===1&&value.applicability_reviewed===1)&&['rejected','revoked'].includes(value.status)));
}catch{return false;}}
export function verifyOperationsCaseMetadata(value){try{
 return keys(value,caseKeys)&&uuid(value.case_id)&&positive(value.requested_by)&&positive(value.creation_event_id)&&clock(value.assembled_at)&&['member_bindings_hash','private_hash','public_hash'].every(k=>hash(value[k]))&&positive(value.source_count)&&value.source_count<=128&&activeState(value,value.assembled_at)&&typeof value.source_accessible==='boolean'&&(!value.source_accessible||value.status==='active')&&value.model_processing_permission==='checked_separately_for_every_member_at_execution'&&whole(value);
}catch{return false;}}
export function operationsRequestValid(model,value){try{
 if(!['OriginalCreate','ReleaseCreate','ReleaseReview','SourceRevoke','CaseCreate','OperationsTaskSelection'].includes(model)||!schema(model,value)||!whole(value))return false;
 if(model==='OriginalCreate')return bytes(value.content_text)<=4194304;
 if(model==='CaseCreate')return new Set(value.release_ids).size===value.release_ids.length;
 if(model==='ReleaseReview')return (value.decision==='publish')===(value.privacy_reviewed&&value.faithfulness_reviewed&&value.applicability_reviewed)&&(value.decision!=='reject'||value.model_processing_allowed===false);
 if(model==='ReleaseCreate'){let end=0;for(const r of value.redactions){if(r.end_codepoint<=r.start_codepoint||r.start_codepoint<end)return false;end=r.end_codepoint;}return true;}
 return true;
}catch{return false;}}
export function operationsRedact(original,redactions){
 if(!scalar(original)||bytes(original)>4194304||!Array.isArray(redactions)||redactions.length>4096)throw new Error('请完整核对原文与明确码点范围');
 const points=Array.from(original),out=[];let previous=0;
 for(const span of redactions){if(!schema('Redaction',span)||span.end_codepoint<=span.start_codepoint||span.start_codepoint<previous||span.end_codepoint>points.length)throw new Error('遮盖范围须互不重叠且位于实际原文');out.push(points.slice(previous,span.start_codepoint).join(''),span.method==='mask'?'[已遮盖]':'');previous=span.end_codepoint;}
 return out.join('')+points.slice(previous).join('');
}
export async function verifyOperationsOriginal(value,metadata,{current=()=>true}={}){try{
 return current()&&verifyOperationsOriginalMetadata(metadata)&&metadata.status==='active'&&schema('OperationsOriginal',value)&&clock(value.captured_at)&&value.original_id===metadata.original_id&&value.captured_by===metadata.captured_by&&value.captured_at===metadata.captured_at&&bytes(value.content_text)===metadata.raw_bytes_length&&Array.from(value.content_text).length===metadata.codepoint_length&&await textHash(value.content_text)===metadata.raw_text_sha256&&await digest(value)===metadata.content_hash&&current()&&whole(value);
}catch{return false;}}
export async function verifyOperationsReleaseDraft(value,metadata,original,{current=()=>true}={}){try{
 if(!current()||!verifyOperationsReleaseMetadata(metadata)||!keys(value,['schema_version','release_id','created_by','recorded_at','proposal','released_text'])||value.schema_version!=='operations_support_release_draft_v1'||!operationsRequestValid('ReleaseCreate',value.proposal)||value.release_id!==metadata.release_id||value.created_by!==metadata.created_by||value.recorded_at!==metadata.recorded_at||!clock(value.recorded_at)||!schema('OperationsOriginal',original)||!clock(original.captured_at)||original.captured_at>value.recorded_at||original.original_id!==metadata.original_id||original.captured_by!==metadata.original_captured_by||value.proposal.original_id!==original.original_id||await digest(original)!==metadata.original_content_hash||value.proposal.original_full_sha256!==metadata.original_content_hash||operationsRedact(original.content_text,value.proposal.redactions)!==value.released_text||await digest(value)!==metadata.content_hash||(!whole(value)||!whole(original)))return false;
 return current();
}catch{return false;}}
export async function verifyOperationsReleasedDocument(value,{current=()=>true}={}){try{return current()&&schema('ReleasedOperationsDocument',value)&&bytes(value.text)<=4194304&&await textHash(value.text)===value.text_sha256&&current()&&whole(value);}catch{return false;}}
export async function verifyOperationsPublicSource(value,{caseMetadata=null,current=()=>true}={}){try{
 if(!current()||!schema('OperationsSupportSource',value)||!clock(value.assembled_at)||!whole(value))return false;
 const ids=value.documents.map(x=>x.source_id);if(!same(ids,[...new Set(ids)].sort()))return false;
 for(const row of value.documents)if(!await verifyOperationsReleasedDocument(row,{current}))return false;
 const counts={documents:ids.length,diagnostic_logs:value.documents.filter(x=>x.kind==='diagnostic_log').length,runbooks:value.documents.filter(x=>x.kind==='runbook').length,reference_documents:value.documents.filter(x=>x.kind==='reference_document').length};
 if(!same(counts,value.counts)||value.action_basis!==(counts.runbooks?'reviewed_runbook_reference_only':'missing_reviewed_runbook'))return false;
 if(caseMetadata!==null&&(!verifyOperationsCaseMetadata(caseMetadata)||!caseMetadata.source_accessible||caseMetadata.case_id!==value.source_id||caseMetadata.assembled_at!==value.assembled_at||caseMetadata.source_count!==ids.length||await digest(value)!==caseMetadata.public_hash))return false;
 return current();
}catch{return false;}}
export async function projectOperationsCollection(value,{current=()=>true}={}){try{
 if(!current()||!schema('PrivateOperationsCollection',value)||!clock(value.assembled_at)||!whole(value))return null;
 const originalIds=new Set(),reviewIds=new Set(),documents=[];
 for(const {original:o,review:r}of value.members){
  if(!clock(o.captured_at)||!clock(r.reviewed_at)||r.reviewed_at<o.captured_at||r.reviewed_at>value.assembled_at||r.original_id!==o.original_id||r.reviewed_by===o.captured_by||originalIds.has(o.original_id)||reviewIds.has(r.review_id)||await digest(o)!==r.original_full_sha256||operationsRedact(o.content_text,r.redactions)!==r.released_text||!whole({original:o,review:r})||!current())return null;
  originalIds.add(o.original_id);reviewIds.add(r.review_id);documents.push({source_id:r.review_id,kind:o.kind,title:r.released_title,declared_component:r.released_component,declared_version:r.released_version,text:r.released_text,text_sha256:await textHash(r.released_text)});
 }
 documents.sort((a,b)=>a.source_id.localeCompare(b.source_id));const runbooks=documents.filter(x=>x.kind==='runbook').length;
 const source={schema_version:'operations_support_source_v1',source_id:value.collection_id,assembled_at:value.assembled_at,coverage:'explicit_reviewed_derivatives_only_not_live_system_inventory',applicability:'manual_declarations_not_independent_live_compatibility_proof',action_basis:runbooks?'reviewed_runbook_reference_only':'missing_reviewed_runbook',counts:{documents:documents.length,diagnostic_logs:documents.filter(x=>x.kind==='diagnostic_log').length,runbooks,reference_documents:documents.filter(x=>x.kind==='reference_document').length},documents};
 return await verifyOperationsPublicSource(source,{current})&&current()?source:null;
}catch{return null;}}
export async function verifyOperationsCaseParts(metadata,{source,private:protectedPart=null},{current=()=>true}={}){try{
 if(!current()||!verifyOperationsCaseMetadata(metadata)||!metadata.source_accessible||!keys(source,['value','raw']))return false;
 const publicPart=decodeOperationsPart(source.raw);if(!same(publicPart.value,source.value)||await textHash(source.raw)!==metadata.public_hash||!await verifyOperationsPublicSource(source.value,{caseMetadata:metadata,current}))return false;
 if(protectedPart!==null){if(!keys(protectedPart,['value','raw']))return false;const actual=decodeOperationsPart(protectedPart.raw);if(!same(actual.value,protectedPart.value)||await textHash(protectedPart.raw)!==metadata.private_hash||protectedPart.value.collection_id!==metadata.case_id||protectedPart.value.requested_by!==metadata.requested_by||protectedPart.value.assembled_at!==metadata.assembled_at||!same(await projectOperationsCollection(protectedPart.value,{current}),source.value))return false;}
 // member_bindings_hash and private_hash remain explicitly opaque for ordinary
 // public-only reads. No missing private body or specific SQL Audit is invented.
 return current();
}catch{return false;}}
export function verifyOperationsSourceDirectory(value,kind,{page=1,size=20,superAdmin=false}={}){try{
 if(!keys(value,['items','total','page','size','body_read_policy'])||value.page!==page||value.size!==size||!positive(page)||!positive(size)||size>50||!Number.isSafeInteger(value.total)||value.total<value.items.length||!Array.isArray(value.items)||value.items.length>size||value.body_read_policy!=='metadata_only_explicit_part_required')return false;
 const ids=[];for(const row of value.items){
  if(kind==='originals'){if(!superAdmin||!verifyOperationsOriginalMetadata(row))return false;ids.push(row.original_id);}
  else if(kind==='cases'){if(!verifyOperationsCaseMetadata(row))return false;ids.push(row.case_id);}
  else if(kind==='releases'){
   if(typeof row.source_accessible!=='boolean'||!uuid(row.release_id))return false;
   if(keys(row,['release_id','source_accessible'])){if(superAdmin||row.source_accessible)return false;}
   else if(superAdmin){if(!verifyOperationsReleaseMetadata(Object.fromEntries(Object.entries(row).filter(([k])=>k!=='source_accessible'))))return false;}
   else if(!keys(row,['release_id','status','revision','published_review_hash','model_processing_allowed','source_accessible'])||row.status!=='published'||row.revision!==2||!hash(row.published_review_hash)||!Number.isInteger(row.model_processing_allowed)||![0,1].includes(row.model_processing_allowed))return false;
   ids.push(row.release_id);
  }else return false;
 }
 return new Set(ids).size===ids.length;
}catch{return false;}}
const id=v=>{if(!uuid(v))throw new Error('请明确规范运维资料UUID');return v;};
const read=(path,params={})=>request({url:BASE+path,method:'get',params,responseType:'arraybuffer',retry:0}).then(decodeOperationsResponse);
const part=path=>request({url:BASE+path,method:'get',responseType:'arraybuffer',retry:0}).then(decodeOperationsPart);
const write=(path,value,model)=>{if(!operationsRequestValid(model,value))throw new Error('请完整填写本次运维原件、独立核查或撤回请求');return request({url:BASE+path,method:'post',data:canonical(value),headers:{'Content-Type':'application/json'},responseType:'arraybuffer',retry:0}).then(decodeOperationsResponse);};
export function getOperationsSourceDirectory(kind,{page=1,size=20}={}){if(!['originals','releases','cases'].includes(kind)||!positive(page)||!positive(size)||size>50)throw new Error('来源目录须为明确类别与有界分页');return read('/'+kind,{page,size});}
export const getOperationsOriginal=value=>read('/originals/'+id(value));
export const getOperationsOriginalBody=value=>part('/originals/'+id(value)+'/body');
export const createOperationsOriginal=value=>write('/originals',value,'OriginalCreate');
export const revokeOperationsOriginal=(value,body)=>write('/originals/'+id(value)+'/revoke',body,'SourceRevoke');
export const getOperationsRelease=value=>read('/releases/'+id(value));
export const getOperationsReleaseDraft=value=>part('/releases/'+id(value)+'/draft');
export const getOperationsReleasedDocument=value=>part('/releases/'+id(value)+'/source');
export const createOperationsRelease=value=>write('/releases',value,'ReleaseCreate');
export const reviewOperationsRelease=(value,body)=>write('/releases/'+id(value)+'/review',body,'ReleaseReview');
export const revokeOperationsRelease=(value,body)=>write('/releases/'+id(value)+'/revoke',body,'SourceRevoke');
export const getOperationsCase=value=>read('/cases/'+id(value));
export const getOperationsCasePart=(value,name)=>{if(!['source','private'].includes(name))throw new Error('材料集仅提供完整公开或受控原件分件');return part('/cases/'+id(value)+'/parts/'+name);};
export const createOperationsCase=value=>write('/cases',value,'CaseCreate');
export const revokeOperationsCase=(value,body)=>write('/cases/'+id(value)+'/revoke',body,'SourceRevoke');
