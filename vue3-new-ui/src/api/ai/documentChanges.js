import request from '@/utils/request';
import packed from './documentChangeSourceSchemas.json';
import {decodeGeneratedSchemas,generatedSchemaMatches} from '../sofaSchema';
import {supportCanonical as canonical,supportDigest as digest,supportId as uuid,supportHash as hash} from '../inpatientSupport';
import {documentUtf8,documentClock,documentBasis,documentBytesHash,documentCodepointSlice,verifyDocumentOriginal,verifyDocumentPublication} from './documentEvidence';

const registry=decodeGeneratedSchemas(packed),base='ai/admin/document-changes',MAX=8388608,DECLARATION='declared_relationship_not_authority_or_clinical_validation';
const object=v=>v!==null&&typeof v==='object'&&!Array.isArray(v),same=(a,b)=>canonical(a)===canonical(b),keys=(v,names)=>object(v)&&same(Object.keys(v).sort(),[...names].sort()),own=(v,k)=>object(v)&&Object.hasOwn(v,k);
const positive=v=>Number.isSafeInteger(v)&&v>0&&v<=2147483647,current=o=>!o.current||o.current()===true,bytes=v=>documentUtf8(typeof v==='string'?v:canonical(v)).length;
function scalarJsonValue(value){
 let nodes=0;const active=new Set();
 function visit(v,depth){
  if(++nodes>2101248||depth>32)return false;
  if(v===null||typeof v==='boolean')return true;
  if(typeof v==='string'){documentUtf8(v);return true;}
  if(typeof v==='number')return Number.isSafeInteger(v);
  if(typeof v!=='object'||active.has(v)||!Array.isArray(v)&&![Object.prototype,null].includes(Object.getPrototypeOf(v)))return false;
  active.add(v);const values=Array.isArray(v)?v:Object.entries(v);for(const entry of values){if(Array.isArray(v)){if(!visit(entry,depth+1))return false;}else{const[k,item]=entry;if(['__proto__','constructor','prototype'].includes(k)||!visit(k,depth+1)||!visit(item,depth+1))return false;}}active.delete(v);return true;
 }
 return visit(value,0);
}

const ref=o=>({original_id:o.snapshot.original_id,content_hash:o.content_hash,governance_hash:o.governance_hash}),targetKey=t=>t.kind+':'+String(t.target_id),ordered=a=>same(a,[...new Set(a)].sort());
export const documentChangeSchemaMatches=(name,value)=>scalarJsonValue(value)&&generatedSchemaMatches(registry,name,value);
export const documentChangeReferenceValid=value=>keys(value,['document_change_scope_id'])&&uuid(value.document_change_scope_id);
export const documentChangeStates=Object.freeze({draft:'待审核',published:'已审核发布',rejected:'审核拒绝',revoked:'已撤销'});
function bounded(value,max=MAX){if(bytes(value)>max)throw new Error('完整原件超过UTF8预算，未截断');return true;}
function wire(value){return bounded({code:200,msg:'success',data:value});}
function signature(g,recorded){
 if(!documentClock(recorded))return false;
 const reviewed=g.reviewed_by!==null,revoked=g.revoked_by!==null,confirmed=['privacy_review','faithfulness_review','dependency_review'].every(k=>g[k]==='confirmed');
 if(reviewed?!documentClock(g.reviewed_at)||g.reviewed_at<recorded||!documentBasis(g.review_basis_note)||['privacy_review','faithfulness_review','dependency_review'].some(k=>g[k]==='unknown'):g.reviewed_at!==null||g.review_basis_note!==''||['privacy_review','faithfulness_review','dependency_review'].some(k=>g[k]!=='unknown'))return false;
 if(revoked?!documentClock(g.revoked_at)||g.revoked_at<(g.reviewed_at||recorded)||!documentBasis(g.revoke_reason,1000):g.revoked_at!==null||g.revoke_reason!=='')return false;
 if(g.status==='draft')return g.revision===1&&!reviewed&&!revoked;
 if(g.status==='revoked')return revoked&&g.revision===(reviewed?3:2);
 return reviewed&&!revoked&&g.revision===2&&(g.status==='published'?confirmed:g.status==='rejected'&&!confirmed);
}
function audits(v){const g=v.governance,a=v.audit_event_ids,values=[a.created,a.reviewed,a.revoked].filter(n=>n!==null);return positive(a.created)&&(a.reviewed!==null)===(g.reviewed_by!==null)&&(a.revoked!==null)===(g.revoked_by!==null)&&values.every(positive)&&new Set(values).size===values.length;}
const RISK=['rule_profile_id','schema_version','rule_id','recipe_digest','policy_digest','identity_hash','published_key','payload_json','content_hash','created_by','created_at','status','revision','published_at','published_by','review_note','review_evidence_reference','implementation_terms_confirmed','revoked_at','revoked_by','revoke_reason'];
const PATHWAY=['pathway_id','name','disease_code','disease_name','steps','expected_days','status','source_revision','create_time'];
const RISK_INTS=new Set(['created_by','revision','published_by','implementation_terms_confirmed','revoked_by']),PATHWAY_INTS=new Set(['pathway_id','expected_days','status','source_revision']);
export function documentChangeTargetValid(value){try{
 if(!documentChangeSchemaMatches('TargetSnapshot',value)||!bounded(value,1048576))return false;
 if(!value.exists)return value.columns===null&&value.state==='missing'&&same(value.state_reasons,['target_missing']);
 const risk=value.target.kind==='risk_rule_profile',names=risk?RISK:PATHWAY,ints=risk?RISK_INTS:PATHWAY_INTS;
 if(!keys(value.columns,names)||value.state==='missing'||value.columns[risk?'rule_profile_id':'pathway_id']!==value.target.target_id)return false;
 if(Object.entries(value.columns).some(([k,v])=>v!==null&&(ints.has(k)?!Number.isSafeInteger(v):typeof v!=='string')))return false;
 return new Set(value.state_reasons).size===value.state_reasons.length&&(value.state==='current')===(value.state_reasons.length===0);
}catch{return false;}}
export async function verifyDocumentChangeLink(v,{original=null,target=null,...options}={}){try{
 if(!current(options)||!documentChangeSchemaMatches('LinkRecord',v)||!wire(v)||!signature(v.governance,v.snapshot.recorded_at)||!audits(v))return false;
 const s=v.snapshot,p=s.proposal,span=p.span;
 if(!documentBasis(p.basis_note)||!documentChangeTargetValid(s.target_snapshot)||!s.target_snapshot.exists||!same(s.target_snapshot.target,p.target)||await digest(s.target_snapshot)!==p.expected_target_hash||bytes(s)>1048576||Array.from(span.quote).length!==span.end-span.start||span.start>=span.end||bytes(span.quote)>65535)return false;
 if(await digest(s)!==v.content_hash||await digest(v.governance)!==v.governance_hash)return false;
 if(original){if(!await verifyDocumentOriginal(original,options)||p.original.original_id!==original.snapshot.original_id||p.original.content_hash!==original.content_hash||span.end>original.snapshot.codepoint_length||documentCodepointSlice(original.snapshot.text,span.start,span.end)!==span.quote)return false;if(v.original_current!==(original.eligible&&same(p.original,ref(original))))return false;}
 if(target&&(!documentChangeTargetValid(target)||!same(target.target,p.target)||v.target_current!==(target.state==='current'&&same(target,s.target_snapshot))))return false;
 const reasons=[...(v.governance.status==='published'?[]:['link_not_published']),...(v.original_current?[]:['original_changed']),...(v.target_current?[]:['target_changed'])];
 return current(options)&&v.eligible===!reasons.length&&same(reasons,v.ineligibility_reasons);
}catch{return false;}}
async function inventoryValid(v,options){
 if(!documentChangeSchemaMatches('Inventory',v)||!wire(v))return false;
 const originals=[v.baseline_original,v.candidate_original],ids=new Set(),targets=new Map(v.targets.map(t=>[targetKey(t.target),t]));
 const add=id=>{if(ids.has(id))return false;ids.add(id);return true;};
 for(const o of originals)if(!await verifyDocumentOriginal(o,options)||!o.eligible||!add('original:'+o.snapshot.original_id))return false;
 if(!ordered(v.targets.map(t=>targetKey(t.target)))||!ordered(v.rule_links.map(l=>l.snapshot.link_id))||!ordered(v.publications.map(p=>p.publication.snapshot.publication_id)))return false;
 for(const t of v.targets)if(!documentChangeTargetValid(t)||!add('target:'+targetKey(t.target)))return false;
 for(const l of v.rule_links){const original=originals.find(o=>o.snapshot.original_id===l.snapshot.proposal.original.original_id),target=targets.get(targetKey(l.snapshot.proposal.target));if(!original||!target||!add('link:'+l.snapshot.link_id)||!await verifyDocumentChangeLink(l,{...options,original,target}))return false;}
 for(const p of v.publications){const original=originals.find(o=>o.snapshot.original_id===p.publication.snapshot.original.original_id);if(!original||!add('candidate:'+p.candidate.snapshot.candidate_id)||!add('publication:'+p.publication.snapshot.publication_id)||!add('knowledge:'+p.publication.snapshot.knowledge_document_id)||!await verifyDocumentPublication(p.publication,p.candidate,original,options))return false;}
 return current(options)&&ids.size===v.member_count&&ids.size<=8192;
}
function relationship(r){return documentBasis(r.basis_note)&&(r.kind!=='declared_successor'||r.same_guideline_family==='confirmed');}
export async function verifyDocumentChangeScope(v,options={}){try{
 if(!current(options)||!documentChangeSchemaMatches('ScopeRecord',v)||!wire(v)||!signature(v.governance,v.snapshot.recorded_at)||!audits(v)||v.automatic_supersession!==false)return false;
 const s=v.snapshot,r=s.request,i=s.inventory;
 if(!relationship(r.relationship)||!documentBasis(r.declaration_basis_note)||!await inventoryValid(i,options)||await digest(i)!==s.inventory_hash||await digest(s)!==v.content_hash||await digest(v.governance)!==v.governance_hash||!same(r.baseline_original,ref(i.baseline_original))||!same(r.candidate_original,ref(i.candidate_original)))return false;
 const targets=r.declared_targets.map(targetKey),present=new Set(i.targets.filter(t=>t.exists).map(t=>targetKey(t.target)));
 if(!ordered(targets)||targets.some(k=>!present.has(k))||[i.baseline_original,i.candidate_original].some(o=>o.governance.reviewed_at>s.recorded_at))return false;
 const reasons=[...(v.governance.status==='published'?[]:['scope_not_published']),...(v.inventory_current?[]:['inventory_changed'])];
 return current(options)&&v.eligible===!reasons.length&&same(reasons,v.ineligibility_reasons);
}catch{return false;}}
export async function projectDocumentChangeScope(v){
 if(!documentChangeSchemaMatches('ScopeRecord',v))throw new Error('完整比较原件合同缺失');
 const s=v.snapshot,i=s.inventory,r=s.request,declared=new Set(r.declared_targets.map(targetKey));
 const original=o=>({schema_version:'document_change_original_source_v1',original:ref(o),raw_bytes_hash:o.snapshot.raw_bytes_hash,raw_bytes_length:o.snapshot.raw_bytes_length,codepoint_length:o.snapshot.codepoint_length,text:o.snapshot.text});
 const rule_links=[];for(const l of i.rule_links){const p=l.snapshot.proposal;rule_links.push({link_id:l.snapshot.link_id,content_hash:l.content_hash,governance_hash:l.governance_hash,original:p.original,start:p.span.start,end:p.span.end,quote_bytes_hash:await documentBytesHash(p.span.quote),target:p.target,target_snapshot_hash:p.expected_target_hash,dependency_kind:p.dependency_kind,current:l.eligible,within_declared_scope:declared.has(targetKey(p.target))});}
 const targets=[];for(const t of i.targets)targets.push({target:t.target,snapshot_hash:await digest(t),state:t.state,within_declared_scope:declared.has(targetKey(t.target))});
 const result={schema_version:'document_change_source_v1',scope:{scope_id:s.scope_id,content_hash:v.content_hash,governance_hash:v.governance_hash},baseline:original(i.baseline_original),candidate:original(i.candidate_original),relationship_kind:r.relationship.kind,same_guideline_family:r.relationship.same_guideline_family,rule_link_coverage:r.rule_link_coverage,targets,rule_links,publications:i.publications.map(({publication:p})=>({publication_id:p.snapshot.publication_id,content_hash:p.content_hash,governance_hash:p.governance_hash,original:p.snapshot.original,candidate:p.snapshot.candidate,knowledge_document_id:p.snapshot.knowledge_document_id,knowledge_content_hash:p.knowledge_current.content_hash,bound_source_current:p.eligible,ineligibility_reasons:p.ineligibility_reasons})),member_count:i.member_count,inventory_hash:s.inventory_hash,hospital_wide_rule_inventory:'not_provided',clinical_validation:'not_provided'};
 wire(result);return result;
}
export async function verifyDocumentChangeSource(v,{scope=null,...options}={}){try{
 if(!current(options)||!documentChangeSchemaMatches('DocumentChangeSource',v)||!wire(v)||v.baseline.original.original_id===v.candidate.original.original_id||v.member_count!==2+v.targets.length+v.rule_links.length+3*v.publications.length)return false;
 for(const o of [v.baseline,v.candidate])if(bytes(o.text)!==o.raw_bytes_length||Array.from(o.text).length!==o.codepoint_length||await documentBytesHash(o.text)!==o.raw_bytes_hash)return false;
 if(!ordered(v.targets.map(t=>targetKey(t.target)))||!ordered(v.rule_links.map(l=>l.link_id))||!ordered(v.publications.map(p=>p.publication_id)))return false;
 const originals=[v.baseline,v.candidate],targets=new Map(v.targets.map(t=>[targetKey(t.target),t]));
 for(const l of v.rule_links){const original=originals.find(o=>same(o.original,l.original)),t=targets.get(targetKey(l.target));if(!original||!t||l.start>=l.end||l.end>original.codepoint_length||await documentBytesHash(documentCodepointSlice(original.text,l.start,l.end))!==l.quote_bytes_hash||l.within_declared_scope!==t.within_declared_scope||l.current&&(t.state!=='current'||l.target_snapshot_hash!==t.snapshot_hash))return false;}
 if(v.publications.some(p=>!originals.some(o=>same(p.original,o.original))))return false;
 if(scope&&(!await verifyDocumentChangeScope(scope,options)||!same(await projectDocumentChangeScope(scope),v)))return false;
 return current(options);
}catch{return false;}}
export async function verifyDocumentChangeCapture(v,expected=null,options={}){try{
 if(!keys(v,['schema_version','request','inventory','inventory_hash','member_count','hospital_wide_rule_inventory','automatic_supersession','clinical_validation'])||v.schema_version!=='document_change_capture_v1'||v.automatic_supersession!==false||v.hospital_wide_rule_inventory!=='not_provided'||v.clinical_validation!=='not_provided'||!wire(v)||!await documentChangeRequestValid('ScopeCaptureRequest',v.request)||expected&&!same(expected,v.request)||!await inventoryValid(v.inventory,options)||await digest(v.inventory)!==v.inventory_hash||v.member_count!==v.inventory.member_count)return false;
 return current(options)&&same(v.request.baseline_original,ref(v.inventory.baseline_original))&&same(v.request.candidate_original,ref(v.inventory.candidate_original))&&v.request.declared_targets.every(t=>v.inventory.targets.some(row=>row.exists&&same(row.target,t)));
}catch{return false;}}
export async function documentChangeRequestValid(model,v){try{
 if(!documentChangeSchemaMatches(model,v)||!bounded(v,model==='LinkCreate'?1048576:MAX))return false;
 if(model==='ScopeCaptureRequest'||model==='ScopeCreate')return relationship(v.relationship)&&documentBasis(v.declaration_basis_note)&&v.baseline_original.original_id!==v.candidate_original.original_id&&ordered(v.declared_targets.map(targetKey));
 if(model==='LinkCreate')return documentBasis(v.basis_note)&&v.span.start<v.span.end&&Array.from(v.span.quote).length===v.span.end-v.span.start&&bytes(v.span.quote)<=65535;
 if(model==='ReviewRequest')return documentBasis(v.basis_note)&&(v.decision==='approve')===(v.privacy_review==='confirmed'&&v.faithfulness_review==='confirmed'&&v.dependency_review==='confirmed');
 if(model==='RevokeRequest')return documentBasis(v.basis_note,1000);
 return model==='TargetReference';
}catch{return false;}}
export function documentChangeDirectoryValid(kind,v){try{
 const key=kind==='links'?'link_id':kind==='scopes'?'scope_id':null;
 return !!key&&keys(v,['items','page','page_size','total'])&&Number.isSafeInteger(v.page)&&v.page>=1&&v.page<=1000000&&Number.isSafeInteger(v.page_size)&&v.page_size>=1&&v.page_size<=100&&Number.isSafeInteger(v.total)&&v.total>=0&&v.items.length<=v.page_size&&v.items.length===Math.max(0,Math.min(v.page_size,v.total-(v.page-1)*v.page_size))&&new Set(v.items.map(r=>r[key])).size===v.items.length&&v.items.every(r=>keys(r,[key,'content_hash','governance_hash','status','revision','recorded_at','detail_required'])&&uuid(r[key])&&hash(r.content_hash)&&hash(r.governance_hash)&&Object.hasOwn(documentChangeStates,r.status)&&Number.isSafeInteger(r.revision)&&r.revision>=1&&r.revision<=3&&documentClock(r.recorded_at)&&r.detail_required===true)&&wire(v);
}catch{return false;}}
export function documentChangeMetadataMatches(kind,record,row){const key=kind==='links'?'link_id':'scope_id';return !row||record.snapshot[key]===row[key]&&record.content_hash===row.content_hash&&record.governance_hash===row.governance_hash&&record.governance.status===row.status&&record.governance.revision===row.revision&&record.snapshot.recorded_at===row.recorded_at;}
export function documentChangeOptionsValid(v){try{return keys(v,['schema_version','target_kinds','span_coordinate_space','maximum_case_utf8_bytes','maximum_combined_members','maximum_json_nodes','maximum_json_depth','maximum_declared_targets','hospital_wide_rule_inventory','automatic_supersession','clinical_validation','declaration_status'])&&same(v,{schema_version:'document_change_options_v1',target_kinds:['risk_rule_profile','clinical_pathway'],span_coordinate_space:'unicode_codepoint_half_open',maximum_case_utf8_bytes:8388608,maximum_combined_members:8192,maximum_json_nodes:2101248,maximum_json_depth:32,maximum_declared_targets:256,hospital_wide_rule_inventory:'not_provided',automatic_supersession:false,clinical_validation:'not_provided',declaration_status:DECLARATION});}catch{return false;}}
function id(v){if(!uuid(v))throw new Error('需要规范UUID');return v;}
function directory(params={}){if(!object(params)||Object.keys(params).some(k=>!['page','page_size','original_id'].includes(k))||Object.hasOwn(params,'original_id')&&!uuid(params.original_id)||Object.hasOwn(params,'page')&&(!Number.isSafeInteger(params.page)||params.page<1||params.page>1000000)||Object.hasOwn(params,'page_size')&&(!Number.isSafeInteger(params.page_size)||params.page_size<1||params.page_size>100))throw new Error('目录过滤须为明确原件和整数分页');return params;}
const read=(path,params)=>request({url:path,method:'get',params,retry:0}),write=async(path,data,model)=>{if(!await documentChangeRequestValid(model,data))throw new Error('完整声明、审核或CAS字段不符合合同');return request({url:path,method:'post',data:JSON.stringify(data),headers:{'Content-Type':'application/json'},retry:0});};
export const getDocumentChangeOptions=()=>read(base+'/options');
export const getDocumentChangeTarget=data=>write(base+'/target-snapshot',data,'TargetReference');
export const captureDocumentChangeScope=data=>write(base+'/capture',data,'ScopeCaptureRequest');
export const getDocumentChangeLinks=(params={})=>read(base+'/links',directory(params));
export const getDocumentChangeScopes=(params={})=>read(base+'/scopes',directory(params));
export const getDocumentChangeLink=value=>read(`${base}/links/${id(value)}`);
export const getDocumentChangeScope=value=>read(`${base}/scopes/${id(value)}`);
export const getDocumentChangePublicSource=value=>read(`${base}/scopes/${id(value)}/public-source`);
export const createDocumentChangeLink=data=>write(base+'/links',data,'LinkCreate');
export const createDocumentChangeScope=data=>write(base+'/scopes',data,'ScopeCreate');
export const reviewDocumentChangeLink=(value,data)=>write(`${base}/links/${id(value)}/review`,data,'ReviewRequest');
export const reviewDocumentChangeScope=(value,data)=>write(`${base}/scopes/${id(value)}/review`,data,'ReviewRequest');
export const revokeDocumentChangeLink=(value,data)=>write(`${base}/links/${id(value)}/revoke`,data,'RevokeRequest');
export const revokeDocumentChangeScope=(value,data)=>write(`${base}/scopes/${id(value)}/revoke`,data,'RevokeRequest');
