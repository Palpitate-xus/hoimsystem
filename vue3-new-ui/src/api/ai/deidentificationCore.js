import registry from './deidentificationSourceSchemas.json';
import policy from './deidentificationSourcePolicy.json';
import {decodeGeneratedSchemas,generatedSchemaMatches} from '../sofaSchema';
import {supportCanonical,supportDigest,supportId,supportHash} from '../inpatientSupport';
import {documentUtf8,documentBytesHash,documentClock} from './documentEvidence';

export {policy as deidentificationPolicy,supportCanonical as deidentificationCanonical,supportDigest as deidentificationDigest,supportId as deidentificationId,supportHash as deidentificationHash,documentUtf8 as deidentificationUtf8,documentBytesHash as deidentificationTextHash,documentClock as deidentificationClock};
export const schemas=decodeGeneratedSchemas(registry),object=v=>v!==null&&typeof v==='object'&&!Array.isArray(v),same=(a,b)=>supportCanonical(a)===supportCanonical(b),pick=(v,n)=>Object.fromEntries(n.map(k=>[k,v[k]]));
export const keys=(v,n)=>object(v)&&same(Object.keys(v).sort(),[...n].sort()),positive=v=>Number.isSafeInteger(v)&&v>0&&v<=2147483647;
export const compare=(a,b)=>{const aa=Array.from(a),bb=Array.from(b);for(let i=0;i<Math.min(aa.length,bb.length);i++){const n=aa[i].codePointAt(0)-bb[i].codePointAt(0);if(n)return n;}return aa.length-bb.length;};
export const tupleCompare=(a,b)=>{for(let i=0;i<Math.min(a.length,b.length);i++){const n=typeof a[i]==='number'?a[i]-b[i]:compare(a[i],b[i]);if(n)return n;}return a.length-b.length;};
export const ordered=values=>Array.isArray(values)&&values.every((v,i)=>i===0||tupleCompare(Array.isArray(values[i-1])?values[i-1]:[values[i-1]],Array.isArray(v)?v:[v])<0);
export function scalar(v){try{documentUtf8(v);return true;}catch{return false;}}
export function jsonScalars(v,depth=0){if(depth>80)return false;if(typeof v==='string')return scalar(v);if(Array.isArray(v))return v.every(x=>jsonScalars(x,depth+1));if(object(v))return Object.entries(v).every(([k,x])=>!['__proto__','constructor','prototype'].includes(k)&&scalar(k)&&jsonScalars(x,depth+1));return v===null||typeof v==='boolean'||Number.isSafeInteger(v);}
export const bytes=v=>documentUtf8(typeof v==='string'?v:supportCanonical(v)).length;
const whitespace=/[\ufeff\u0009-\u000d\u001c-\u0020\u0085\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000]/gu;
export function deidentificationBasis(value,max=4000){try{return scalar(value)&&Array.from(value).length>=20&&Array.from(value).length<=max&&value.replace(whitespace,'').length>0&&bytes(value)<=4000;}catch{return false;}}
export function calendar(value){try{return typeof value==='string'&&/^\d{4}-\d\d-\d\d$/.test(value)&&!value.startsWith('0000-')&&new Date(value+'T00:00:00.000Z').toISOString()===value+'T00:00:00.000Z';}catch{return false;}}
export function naiveClock(value){return typeof value==='string'&&/^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{6}$/.test(value)&&documentClock(value+'Z');}
export const deidentificationSchemaMatches=(name,v)=>generatedSchemaMatches(schemas,name,v);
export function deidentificationRequestValid(name,v){try{
 if(!deidentificationSchemaMatches(name,v)||!jsonScalars(v)||bytes(supportCanonical(v))>policy.max_bytes)return false;
 const recurse=x=>{if(Array.isArray(x))return x.every(recurse);if(!object(x))return true;for(const[k,c]of Object.entries(x)){
  if((k==='basis_note'||k==='purpose'||k==='external_model_use_basis'||k==='authorization_basis'||k==='declared_purpose')&&!deidentificationBasis(c,k==='basis_note'&&name==='GovernanceRevoke'?1000:4000))return false;
  if(['valid_from','valid_until'].includes(k)&&c!==null&&!documentClock(c))return false;
  if(['date_from','date_to'].includes(k)&&!calendar(c))return false;
  if(k==='original_authority_text'&&c!==null&&bytes(c)>65535)return false;
  if(!recurse(c))return false;
 }if(Object.hasOwn(x,'valid_from')&&Object.hasOwn(x,'valid_until')&&((x.valid_from===null)!==(x.valid_until===null)||x.valid_from!==null&&x.valid_until<=x.valid_from))return false;return true;};
 if(!recurse(v))return false;
 if(['FieldSelection','CaptureRequest','CaseCreate'].includes(name)){
  const req=name==='CaseCreate'?v.request:v,fields=name==='FieldSelection'?[v]:req.documents;
  if(fields&&(!fields.every(s=>policy.text_fields[s.family]?.includes(s.field))||!ordered(fields.map(s=>[s.family,s.record_id,s.field]))))return false;
 }
 if(name==='SpanEdit')return v.start<v.end&&Array.from(v.quote).length===v.end-v.start;
 if(name==='ReviewCreate')return ordered(v.edits.map(e=>[e.document_source_id,e.start,e.end]))&&v.edits.every(e=>deidentificationRequestValid('SpanEdit',e));
 if(name==='ScopeCreate')return ['patient_ids','proposed_user_ids','data_families','permitted_uses'].every(k=>ordered(v[k]))&&calendar(v.record_window.date_from)&&calendar(v.record_window.date_to)&&0<=Date.parse(v.record_window.date_to)-Date.parse(v.record_window.date_from)&&Date.parse(v.record_window.date_to)-Date.parse(v.record_window.date_from)<366*86400000;
 return true;
}catch{return false;}}
export async function deidentificationDocument(source_id,field,text){
 if(!scalar(source_id)||!source_id||Array.from(source_id).length>160||!scalar(field)||Array.from(field).length>100||text!==null&&!scalar(text))throw new Error('明确完整文字字段无法核对');
 if(text===null)return{source_id,field,text:null,text_hash:null,utf8_bytes:null,codepoint_length:null,absent_reason:'not_recorded'};
 if(bytes(text)>policy.max_bytes)throw new Error('完整文字超过8MiB');
 return{source_id,field,text,text_hash:await documentBytesHash(text),utf8_bytes:bytes(text),codepoint_length:Array.from(text).length,absent_reason:null};
}
export async function verifyDeidentificationDocument(v){try{return deidentificationSchemaMatches('SourceDocument',v)&&same(await deidentificationDocument(v.source_id,v.field,v.text),v);}catch{return false;}}
export async function applyDeidentificationEdits(documents,edits){
 if(!Array.isArray(documents)||documents.length<1||documents.length>policy.max_documents||new Set(documents.map(d=>d.source_id)).size!==documents.length||!Array.isArray(edits)||edits.length>policy.max_edits||!ordered(edits.map(e=>[e.document_source_id,e.start,e.end])))throw new Error('完整字段和明确编辑须有序且不重叠');
 for(const doc of documents)if(!await verifyDeidentificationDocument(doc))throw new Error('原文全文SHA/CP不符');
 const grouped=new Map(documents.map(d=>[d.source_id,[]]));
 for(const e of edits){const d=documents.find(d=>d.source_id===e.document_source_id),g=grouped.get(e.document_source_id);if(!deidentificationRequestValid('SpanEdit',e)||!d||d.text===null||d.text_hash!==e.text_hash||e.end>d.codepoint_length||Array.from(d.text).slice(e.start,e.end).join('')!==e.quote||g.length&&g[g.length-1].end>e.start)throw new Error('原文逐字位置、整件SHA或明确编辑不符');g.push(e);}
 const out=[];for(const d of documents){let text=d.text;if(text!==null){const cp=Array.from(text),parts=[];let cursor=0;for(const e of grouped.get(d.source_id)){parts.push(cp.slice(cursor,e.start).join(''),policy.masks[e.action]);cursor=e.end;}parts.push(cp.slice(cursor).join(''));text=parts.join('');}out.push(await deidentificationDocument(d.source_id,d.field,text));}
 const value={schema_version:'deidentification_selected_output_v1',documents:out,limitations:[...policy.limitations],anonymity_guaranteed:false};if(bytes(supportCanonical(value))>policy.max_bytes)throw new Error('完整输出超过8MiB');return value;
}
