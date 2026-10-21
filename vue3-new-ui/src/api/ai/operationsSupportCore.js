import {supportCanonical,supportDigest,supportId,supportHash} from '../inpatientSupport';
import {documentClock,documentUtf8} from './documentEvidence';
import {parseOriginalJson,scalarJsonValue} from './researchCohortOriginalJson';
import {decodeGeneratedSchemas,generatedSchemaMatches} from '../sofaSchema';
import packed from './operationsSupportSchemas.json';
import fixed from './operationsSupportFixed.json';
const schemas=decodeGeneratedSchemas(packed);
export const operationsCanonical=supportCanonical,operationsDigest=supportDigest,operationsId=supportId,operationsHash=supportHash;
export const operationsFixed=Object.freeze(structuredClone(fixed));
export const operationsBytes=v=>documentUtf8(typeof v==='string'?v:supportCanonical(v)).length;
export const operationsScalar=v=>typeof v==='string'&&scalarJsonValue(v);
export const operationsSame=(a,b)=>supportCanonical(a)===supportCanonical(b);
export const operationsKeys=(v,n)=>v!==null&&typeof v==='object'&&!Array.isArray(v)&&operationsSame(Object.keys(v).sort(),[...n].sort());
export const operationsPick=(v,n)=>Object.fromEntries(n.map(k=>[k,v[k]]));
export const operationsPositive=v=>Number.isSafeInteger(v)&&v>=1&&v<=2147483647;
export const operationsClock=v=>typeof v==='string'&&/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}Z$/u.test(v)&&documentClock(v);
export const operationsSchema=(model,value)=>Object.hasOwn(schemas,model)&&generatedSchemaMatches(schemas,model,value);
export const operationsFormSchema=model=>Object.hasOwn(schemas,model)?structuredClone(schemas[model]):null;
export const operationsTextHash=async text=>{
 if(!operationsScalar(text))throw new Error('完整原文须为有效Unicode标量字符串');
 return Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',documentUtf8(text))),v=>v.toString(16).padStart(2,'0')).join('');
};
function noFractionLexemes(raw){
 let quoted=false,escaped=false;
 for(let i=0;i<raw.length;i++){
  const char=raw[i];if(quoted){if(escaped)escaped=false;else if(char==='\\')escaped=true;else if(char==='"')quoted=false;continue;}
  if(char==='"'){quoted=true;continue;}
  if(char==='-'||/[0-9]/u.test(char)){const match=raw.slice(i).match(/^-?(?:0|[1-9]\d*)(?:\.\d+)?(?:[eE][+-]?\d+)?/u);if(match){if(/[.eE]/u.test(match[0]))throw new Error('运维闭集只接受原始整数JSON量');i+=match[0].length-1;}}
 }
}
export function parseOperationsJson(raw,max=8388608){noFractionLexemes(raw);return parseOriginalJson(raw,max);}
export function decodeOperationsPart(raw,max=8388608){
 let text=raw;
 if(typeof text!=='string'){
  const v=raw instanceof ArrayBuffer?new Uint8Array(raw):ArrayBuffer.isView(raw)?new Uint8Array(raw.buffer,raw.byteOffset,raw.byteLength):null;
  if(!v||!v.length||v.length>max)throw new Error('运维完整分件须使用原UTF8字节并遵守容量');
  text=new TextDecoder('utf-8',{fatal:true,ignoreBOM:true}).decode(v);
 }
 if(!operationsScalar(text)||!text.length||operationsBytes(text)>max)throw new Error('完整运维分件超限，未截断读取');
 return Object.freeze({raw:text,value:parseOperationsJson(text,max)});
}
export function decodeOperationsResponse(raw){
 const value=decodeOperationsPart(raw).value;
 if(!operationsKeys(value,['code','msg','data'])||value.code!==200||!operationsScalar(value.msg))throw new Error('运维回执闭集无法核对');
 return value;
}
export function operationsWhole(value,max=8388608){return scalarJsonValue(value)&&operationsBytes(value)<=max;}
