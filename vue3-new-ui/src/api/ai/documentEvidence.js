import request from '@/utils/request';
import registry from './documentEvidenceSchemas.json';
import {decodeGeneratedSchemas,generatedSchemaMatches} from '../sofaSchema';
import {supportCanonical,supportDigest,supportId} from '../inpatientSupport';

const schemas=decodeGeneratedSchemas(registry),base='ai/admin/document-evidence',own=(v,k)=>Object.hasOwn(v,k),same=(a,b)=>supportCanonical(a)===supportCanonical(b),pick=(v,n)=>Object.fromEntries(n.map(k=>[k,v[k]]));
const MAX=4194304,WIRE=8388608,QUOTE=65535,URI='hoim://document-evidence/',DECLARATION='submitter_declared_not_authority_or_clinical_validation';
const whitespace=/[\u0009-\u000d\u001c-\u0020\u0085\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000]/gu;
export const documentEvidenceStates=Object.freeze({draft:'待审核',published:'原文已发布',approved:'候选已批准',rejected:'审核拒绝',revoked:'已撤销',active:'已显式发布知识'});
export const documentKinds=Object.freeze({guideline:'指南原文',drug_label:'药品说明书原文',local_protocol:'院内规范原文',other:'其他原文'});
export const documentClauseKinds=Object.freeze({recommendation:'推荐条款',definition:'定义',applicability:'适用条件',warning:'警示',other:'其他原文'});
export const documentSchemaMatches=(model,value)=>generatedSchemaMatches(schemas,model,value);
export function documentUtf8(text){
 if(typeof text!=='string')throw new Error('需要原Unicode文字');
 for(let i=0;i<text.length;i++){const n=text.charCodeAt(i);if(n>=0xd800&&n<=0xdbff){const next=text.charCodeAt(++i);if(!(next>=0xdc00&&next<=0xdfff))throw new Error('孤立surrogate');}else if(n>=0xdc00&&n<=0xdfff)throw new Error('孤立surrogate');}
 return new TextEncoder().encode(text);
}
const bytes=v=>documentUtf8(typeof v==='string'?v:supportCanonical(v)).length;
export async function documentBytesHash(value){return Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',value instanceof Uint8Array?value:documentUtf8(value))),n=>n.toString(16).padStart(2,'0')).join('');}
export function documentBasis(value,maxCharacters=4000){try{return typeof value==='string'&&Array.from(value).length<=maxCharacters&&Array.from(value.replace(whitespace,'')).length>=10&&bytes(value)<=4000;}catch{return false;}}
export function documentClock(value){try{return typeof value==='string'&&/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}Z$/.test(value)&&value.slice(0,4)!=='0000'&&new Date(value.slice(0,23)+'Z').toISOString()===value.slice(0,23)+'Z';}catch{return false;}}
function strings(v){if(typeof v==='string'){documentUtf8(v);return true;}if(Array.isArray(v))return v.every(strings);if(v!==null&&typeof v==='object')return Object.entries(v).every(([key,x])=>{documentUtf8(key);return strings(x);});return true;}
function meaningful(value,max=8000){return typeof value==='string'&&Array.from(value.replace(whitespace,'')).length>0&&bytes(value)<=max;}
function metadata(m){return meaningful(m.title)&&meaningful(m.version)&&meaningful(m.declared_source_uri)&&(m.declared_publisher===null||meaningful(m.declared_publisher,800))&&(m.source_available_at===null||documentClock(m.source_available_at))&&documentBasis(m.applicability_note)&&documentBasis(m.authorization_note)&&bytes(m)<=32768;}
function filename(value){return typeof value==='string'&&/\.(txt|md)$/iu.test(value)&&!/[\\/]/u.test(value)&&bytes(value)<=1020;}
function governance(g,recorded,kind){
 const reviewed=g.reviewed_by!==null,revoked=g.revoked_by!==null;
 if(reviewed?(g.reviewed_at===null||!documentClock(g.reviewed_at)||g.reviewed_at<recorded||!documentBasis(g.review_basis_note)||[g.privacy_review,g.faithfulness_review].includes('unknown')):g.reviewed_at!==null||g.review_basis_note!==''||g.privacy_review!=='unknown'||g.faithfulness_review!=='unknown')return false;
 if(revoked?g.revoked_at===null||!documentClock(g.revoked_at)||g.revoked_at<(g.reviewed_at||recorded)||!documentBasis(g.revoke_reason,1000):g.revoked_at!==null||g.revoke_reason!=='')return false;
 if(g.status==='draft')return g.revision===1&&!reviewed&&!revoked;
 if(g.status==='revoked')return revoked&&g.revision===(reviewed?3:2);
 if(g.revision!==2||!reviewed||revoked)return false;
 const confirmed=g.privacy_review==='confirmed'&&g.faithfulness_review==='confirmed';
 return g.status==='rejected'?!confirmed:g.status===(kind==='original'?'published':'approved')&&confirmed;
}
function approvedAnchor(g,kind){if(g.status===(kind==='original'?'published':'approved'))return g;if(g.status!=='revoked'||g.revision!==3||g.privacy_review!=='confirmed'||g.faithfulness_review!=='confirmed')return null;return {...g,status:kind==='original'?'published':'approved',revision:2,revoked_by:null,revoked_at:null,revoke_reason:''};}
export function documentCodepointSlice(text,start,end){const out=[];let index=0;for(const char of text){if(index>=start&&index<end)out.push(char);if(++index>=end)break;}return out.join('');}
function count(text){let n=0;for(const char of text){void char;n++;}return n;}
export async function verifyDocumentOriginal(v,{current=()=>true}={}){try{
 if(!current()||!documentSchemaMatches('OriginalRecord',v)||!strings(v)||bytes(v)>WIRE)return false;
 const s=v.snapshot,g=v.governance;
 if(!documentClock(s.recorded_at)||!metadata(s.metadata)||s.metadata.source_available_at!==null&&s.metadata.source_available_at>s.recorded_at||(s.input_kind==='direct_text'?s.filename!==null:s.filename===null||!filename(s.filename)))return false;
 if(bytes(s)>WIRE-32768||bytes(s.text)!==s.raw_bytes_length||count(s.text)!==s.codepoint_length||s.raw_bytes_length>MAX||!governance(g,s.recorded_at,'original'))return false;
 if(await documentBytesHash(s.text)!==s.raw_bytes_hash||await supportDigest(s)!==v.content_hash||await supportDigest(g)!==v.governance_hash)return false;
 const reasons=g.status==='published'?[]:['original_not_published'];
 return current()&&v.source_id===`document_original:${s.original_id}:${v.content_hash.slice(0,12)}`&&v.declaration_status===DECLARATION&&v.eligible===!reasons.length&&same(reasons,v.ineligibility_reasons);
}catch{return false;}}
export async function verifyDocumentCandidate(v,original,{current=()=>true}={}){try{
 if(!current()||!documentSchemaMatches('CandidateRecord',v)||!strings(v)||bytes(v.snapshot)>131072||!await verifyDocumentOriginal(original,{current}))return false;
 const s=v.snapshot,p=s.proposal,g=v.governance,anchor=approvedAnchor(original.governance,'original');
 if(!anchor||!documentClock(s.recorded_at)||s.recorded_at<(anchor.reviewed_at||original.snapshot.recorded_at)||!governance(g,s.recorded_at,'candidate')||p.original.original_id!==original.snapshot.original_id||p.original.content_hash!==original.content_hash||await supportDigest(anchor)!==p.original.governance_hash||p.end>original.snapshot.codepoint_length||p.start>=p.end||count(p.quote)!==p.end-p.start||bytes(p.quote)>QUOTE||documentCodepointSlice(original.snapshot.text,p.start,p.end)!==p.quote||!meaningful(p.proposed_heading,800))return false;
 if(await supportDigest(s)!==v.content_hash||await supportDigest(g)!==v.governance_hash||v.source_id!==`document_candidate:${s.candidate_id}:${v.content_hash.slice(0,12)}`)return false;
 const parentCurrent=original.eligible&&p.original.governance_hash===original.governance_hash,reasons=[...(!parentCurrent?['original_not_current']:[]),...(g.status!=='approved'?['candidate_not_approved']:[])];
 return current()&&v.original_current===parentCurrent&&v.eligible===!reasons.length&&same(v.ineligibility_reasons,reasons);
}catch{return false;}}
function knowledgeMetadata(m){return meaningful(m.title,800)&&meaningful(m.version,800)&&new Set(m.feature_keys).size===m.feature_keys.length&&m.feature_keys.every(key=>/^[a-z][a-z0-9_]{1,79}$/u.test(key))&&[m.effective_from,m.effective_to].every(t=>t===null||documentClock(t)&&t.endsWith('.000000Z'))&&(m.effective_from===null||m.effective_to===null||m.effective_from<m.effective_to);}
export async function projectDocumentKnowledge(publication){
 if(!documentSchemaMatches('PublicationRecord',publication))throw new Error('完整知识发布合同缺失');
 const s=publication.snapshot,k=s.knowledge;
 return {document_id:s.knowledge_document_id,title:k.title,version:k.version,source_uri:URI+s.publication_id,source_kind:'document_span',source_reference_id:null,source_snapshot_hash:publication.content_hash,category:k.category,content:s.quote,content_hash:await supportDigest(s.quote),feature_keys_json:supportCanonical([...k.feature_keys].sort()),department_id:k.department_id,effective_from:k.effective_from,effective_to:k.effective_to,status:'published',reviewed_by:s.published_by,reviewed_at:s.knowledge_recorded_at,created_by:s.published_by,create_time:s.knowledge_recorded_at};
}
export async function verifyDocumentPublication(v,candidate,original,{current=()=>true}={}){try{
 if(!current()||!documentSchemaMatches('PublicationRecord',v)||!strings(v)||bytes(v.snapshot)>196608||!await verifyDocumentCandidate(candidate,original,{current}))return false;
 const s=v.snapshot,g=v.governance,a=approvedAnchor(original.governance,'original'),b=approvedAnchor(candidate.governance,'candidate'),k=v.knowledge_current;
 if(!a||!b||!knowledgeMetadata(s.knowledge)||!documentClock(s.published_at)||s.knowledge_clock_basis!=='legacy_utc_second_storage'||!documentClock(s.knowledge_recorded_at)||s.knowledge_recorded_at!==s.published_at.slice(0,19)+'.000000Z'||s.published_at<b.reviewed_at||!documentBasis(s.publication_basis_note)||s.original.original_id!==original.snapshot.original_id||s.original.content_hash!==original.content_hash||await supportDigest(a)!==s.original.governance_hash||s.candidate.candidate_id!==candidate.snapshot.candidate_id||s.candidate.content_hash!==candidate.content_hash||await supportDigest(b)!==s.candidate.governance_hash||s.quote!==candidate.snapshot.proposal.quote||bytes(s.quote)>QUOTE||await documentBytesHash(s.quote)!==s.quote_bytes_hash||await supportDigest(s)!==v.content_hash||await supportDigest(g)!==v.governance_hash)return false;
 if(g.status==='active'?g.revision!==1||g.revoked_by!==null||g.revoked_at!==null||g.revoke_reason!=='':g.revision!==2||g.revoked_by===null||!documentClock(g.revoked_at)||g.revoked_at<s.published_at||!documentBasis(g.revoke_reason,1000))return false;
 if(bytes(k.content)>QUOTE||![k.effective_from,k.effective_to,k.reviewed_at,k.create_time].every(t=>t===null||documentClock(t)))return false;
 const expected=await projectDocumentKnowledge(v),names=Object.keys(expected).filter(n=>n!=='status'),reasons=[];
 if(!original.eligible||s.original.governance_hash!==original.governance_hash)reasons.push('original_not_current');
 if(!candidate.eligible||s.candidate.governance_hash!==candidate.governance_hash)reasons.push('candidate_not_approved');
 if(g.status!=='active')reasons.push('publication_revoked');
 if(k.status!=='published')reasons.push('knowledge_not_published');
 if(!same(pick(expected,names),pick(k,names)))reasons.push('knowledge_changed');
 return current()&&v.eligible===!reasons.length&&same(v.ineligibility_reasons,reasons);
}catch{return false;}}
function decodedFile(v){if(!filename(v.filename))throw new Error('仅支持UTF8 txt/md文件');const binary=atob(v.bytes_base64);if(binary.length<1||binary.length>MAX||btoa(binary)!==v.bytes_base64)throw new Error('原文件字节不完整');const raw=Uint8Array.from(binary,char=>char.charCodeAt(0));return {raw,text:new TextDecoder('utf-8',{fatal:true,ignoreBOM:true}).decode(raw)};}
export async function readDocumentFile(file){
 if(!file||!Number.isSafeInteger(file.size)||file.size<1||file.size>MAX||!filename(file.name))throw new Error('请选择不超过4MiB的UTF8 .txt或.md原文件');
 const raw=new Uint8Array(await file.arrayBuffer());if(raw.length!==file.size)throw new Error('原文件大小已变化');
 const text=new TextDecoder('utf-8',{fatal:true,ignoreBOM:true}).decode(raw),encoded=documentUtf8(text);if(encoded.length!==raw.length||!encoded.every((value,i)=>value===raw[i]))throw new Error('原文件不能完整按UTF8保留');
 const pieces=[];for(let i=0;i<raw.length;i+=32768)pieces.push(String.fromCharCode(...raw.subarray(i,i+32768)));
 return {kind:'utf8_file',filename:file.name,bytes_base64:btoa(pieces.join('')),expected_bytes_hash:await documentBytesHash(raw)};
}
export async function documentEvidenceRequestValid(model,v){try{
 if(!documentSchemaMatches(model,v)||!strings(v)||bytes(v)>WIRE)return false;
 if(['ReviewRequest','RevokeRequest'].includes(model))return documentBasis(v.basis_note,model==='RevokeRequest'?1000:4000)&&(model!=='ReviewRequest'||(v.decision==='approve')===(v.privacy_review==='confirmed'&&v.faithfulness_review==='confirmed'));
 if(model==='OriginalCreate'){if(!metadata(v.metadata))return false;const input=v.content,raw=input.kind==='direct_text'?documentUtf8(input.text):decodedFile(input).raw;return raw.length>0&&raw.length<=MAX&&await documentBytesHash(raw)===input.expected_bytes_hash;}
 if(model==='CandidateCreate')return v.start<v.end&&count(v.quote)===v.end-v.start&&bytes(v.quote)<=QUOTE&&meaningful(v.proposed_heading,800);
 return model==='PublishRequest'&&knowledgeMetadata(v.knowledge)&&documentBasis(v.basis_note);
}catch{return false;}}
const id=value=>{if(!supportId(value))throw new Error('原文证据标识无效');return value;},read=(url,params)=>request({url,method:'get',params,retry:0}),write=async(url,data,model)=>{if(!await documentEvidenceRequestValid(model,data))throw new Error('原文、定位、审核或完整字节合同无法核对');return request({url,method:'post',data:JSON.stringify(data),headers:{'Content-Type':'application/json'},retry:0});};
export const getDocumentEvidenceOptions=()=>read(base+'/options');
export const getDocumentOriginals=params=>read(base+'/originals',params);
export const getDocumentOriginal=value=>read(`${base}/originals/${id(value)}`);
export const createDocumentOriginal=data=>write(base+'/originals',data,'OriginalCreate');
export const reviewDocumentOriginal=(value,data)=>write(`${base}/originals/${id(value)}/review`,data,'ReviewRequest');
export const revokeDocumentOriginal=(value,data)=>write(`${base}/originals/${id(value)}/revoke`,data,'RevokeRequest');
export const getDocumentCandidates=params=>read(base+'/candidates',params);
export const getDocumentCandidate=value=>read(`${base}/candidates/${id(value)}`);
export const createDocumentCandidate=data=>write(base+'/candidates',data,'CandidateCreate');
export const reviewDocumentCandidate=(value,data)=>write(`${base}/candidates/${id(value)}/review`,data,'ReviewRequest');
export const revokeDocumentCandidate=(value,data)=>write(`${base}/candidates/${id(value)}/revoke`,data,'RevokeRequest');
export const publishDocumentCandidate=(value,data)=>write(`${base}/candidates/${id(value)}/publish`,data,'PublishRequest');
export const getDocumentPublications=params=>read(base+'/publications',params);
export const getDocumentPublication=value=>read(`${base}/publications/${id(value)}`);
export const revokeDocumentPublication=(value,data)=>write(`${base}/publications/${id(value)}/revoke`,data,'RevokeRequest');
export function documentEvidenceOptionsValid(v){try{
 const names=['schema_version','source_kind','uri_prefix','input_kinds','file_extensions','original_max_utf8_bytes','request_max_utf8_bytes','knowledge_max_utf8_bytes','span_coordinate_space','normalization','automatic_extraction','automatic_publication','declaration_status','clinical_validation','knowledge_features'];
 if(!v||!same(Object.keys(v).sort(),names.sort())||v.schema_version!=='document_evidence_options_v1'||v.source_kind!=='document_span'||v.uri_prefix!==URI||!same(v.input_kinds,['direct_text','utf8_file'])||!same(v.file_extensions,['.txt','.md'])||v.original_max_utf8_bytes!==MAX||v.request_max_utf8_bytes!==WIRE||v.knowledge_max_utf8_bytes!==QUOTE||v.span_coordinate_space!=='unicode_codepoint_half_open'||v.normalization!=='none'||v.automatic_extraction!==false||v.automatic_publication!==false||v.declaration_status!==DECLARATION||v.clinical_validation!=='not_provided'||!Array.isArray(v.knowledge_features)||v.knowledge_features.length<1||v.knowledge_features.length>80)return false;
 return new Set(v.knowledge_features.map(x=>x.key)).size===v.knowledge_features.length&&v.knowledge_features.every(x=>same(Object.keys(x).sort(),['key','name'])&&/^[a-z][a-z0-9_]{1,79}$/u.test(x.key)&&meaningful(x.name,800));
}catch{return false;}}
export function documentDirectoryValid(kind,v){try{
 if(!['originals','candidates','publications'].includes(kind)||!v||!same(Object.keys(v).sort(),['items','page','page_size','total'])||![v.page,v.page_size,v.total].every(Number.isSafeInteger)||v.page<1||v.page_size<1||v.page_size>100||v.total<0||!Array.isArray(v.items)||v.items.length>Math.min(v.page_size,v.total))return false;
 const identity={originals:'original_id',candidates:'candidate_id',publications:'publication_id'}[kind];if(new Set(v.items.map(x=>x[identity])).size!==v.items.length)return false;
 return v.items.every(x=>{const basic=kind==='originals'?['original_id','title','version','document_kind','content_hash','raw_bytes_hash','raw_bytes_length','codepoint_length','recorded_at','status','revision','governance_hash','detail_required']:kind==='candidates'?['candidate_id','original_id','content_hash','start','end','recorded_at','status','revision','governance_hash','detail_required']:['publication_id','original_id','candidate_id','knowledge_document_id','content_hash','published_at','status','revision','detail_required'];
 if(!same(Object.keys(x).sort(),basic.sort())||!supportId(x[identity])||!/^([a-f0-9]{64})$/u.test(x.content_hash)||x.detail_required!==true||!Number.isSafeInteger(x.revision))return false;
 if(kind==='publications')return ['original_id','candidate_id','knowledge_document_id'].every(k=>supportId(x[k]))&&documentClock(x.published_at)&&(x.status==='active'?x.revision===1:x.status==='revoked'&&x.revision===2);
 if(!documentClock(x.recorded_at)||!/^[a-f0-9]{64}$/u.test(x.governance_hash)||!['draft','rejected','revoked',kind==='originals'?'published':'approved'].includes(x.status)||(x.status==='draft'?x.revision!==1:x.status==='revoked'?![2,3].includes(x.revision):x.revision!==2))return false;
 return kind==='originals'?meaningful(x.title)&&meaningful(x.version)&&own(documentKinds,x.document_kind)&&/^[a-f0-9]{64}$/u.test(x.raw_bytes_hash)&&[x.raw_bytes_length,x.codepoint_length].every(n=>Number.isSafeInteger(n)&&n>0&&n<=MAX):supportId(x.original_id)&&Number.isSafeInteger(x.start)&&Number.isSafeInteger(x.end)&&x.start>=0&&x.start<x.end&&x.end<=MAX;
 });
}catch{return false;}}
export function documentMetadataMatches(kind,record,metadata){if(!metadata)return true;const s=record.snapshot,key={originals:'original_id',candidates:'candidate_id',publications:'publication_id'}[kind];return !!key&&s[key]===metadata[key]&&record.content_hash===metadata.content_hash&&(kind==='publications'||record.governance_hash===metadata.governance_hash)&&record.governance.status===metadata.status&&record.governance.revision===metadata.revision;}
export async function verifyDocumentCreatedOriginal(record,body,options={}){try{if(!await documentEvidenceRequestValid('OriginalCreate',body)||!await verifyDocumentOriginal(record,options))return false;const s=record.snapshot,p=body.content,text=p.kind==='direct_text'?p.text:decodedFile(p).text;return s.input_kind===p.kind&&s.filename===(p.kind==='utf8_file'?p.filename:null)&&s.text===text&&same(s.metadata,body.metadata)&&record.governance.status==='draft';}catch{return false;}}
export async function verifyDocumentTransition(kind,after,before,action,body,parents={},options={}){try{
 const model=action==='publish'?'PublishRequest':action==='revoke'?'RevokeRequest':'ReviewRequest';if(!await documentEvidenceRequestValid(model,body)||before.governance.revision!==body.expected_revision||before.content_hash!==body.expected_content_hash||before.governance_hash!==body.expected_governance_hash)return false;
 if(action==='publish')return kind==='candidates'&&await verifyDocumentPublication(after,before,parents.original,options)&&same(after.snapshot.knowledge,body.knowledge)&&after.snapshot.publication_basis_note===body.basis_note&&after.snapshot.candidate.candidate_id===before.snapshot.candidate_id&&after.snapshot.candidate.content_hash===before.content_hash&&after.snapshot.candidate.governance_hash===before.governance_hash&&after.governance.status==='active';
 const valid=kind==='originals'?await verifyDocumentOriginal(after,options):kind==='candidates'?await verifyDocumentCandidate(after,parents.original,options):await verifyDocumentPublication(after,parents.candidate,parents.original,options);
 if(!valid||!same(after.snapshot,before.snapshot)||after.content_hash!==before.content_hash||after.governance.revision!==before.governance.revision+1)return false;
 const g=after.governance;
 if(action==='revoke'){
  if(g.status!=='revoked'||g.revoke_reason!==body.basis_note||!same(pick(g,Object.keys(before.governance).filter(k=>!['status','revision','revoked_by','revoked_at','revoke_reason'].includes(k))),pick(before.governance,Object.keys(before.governance).filter(k=>!['status','revision','revoked_by','revoked_at','revoke_reason'].includes(k)))))return false;
  return kind!=='publications'||g.revoked_at>=before.snapshot.published_at&&after.knowledge_current.status==='retired'&&same({...after.knowledge_current,status:before.knowledge_current.status},before.knowledge_current);
 }
 return before.governance.status==='draft'&&g.status===(body.decision==='approve'?(kind==='originals'?'published':'approved'):'rejected')&&g.privacy_review===body.privacy_review&&g.faithfulness_review===body.faithfulness_review&&g.review_basis_note===body.basis_note;
}catch{return false;}}
