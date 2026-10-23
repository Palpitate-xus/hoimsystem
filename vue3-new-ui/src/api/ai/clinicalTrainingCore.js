import {supportCanonical,supportDigest,supportId,supportHash} from '../inpatientSupport';
import {documentClock,documentUtf8} from './documentEvidence';
import {parseOriginalJson,scalarJsonValue} from './researchCohortOriginalJson';
import {decodeGeneratedSchemas,generatedSchemaMatches} from '../sofaSchema';
import packed from './clinicalTrainingSourceSchemas.json';
import fixed from './clinicalTrainingSourcePolicy.json';
const schemas=decodeGeneratedSchemas(packed);
export const trainingCanonical=supportCanonical,trainingDigest=supportDigest,trainingId=supportId,trainingHash=supportHash;
export const trainingFixed=Object.freeze(structuredClone(fixed));
export const trainingBytes=v=>documentUtf8(typeof v==='string'?v:supportCanonical(v)).length;
export const trainingScalar=v=>typeof v==='string'&&scalarJsonValue(v);
export const trainingSame=(a,b)=>supportCanonical(a)===supportCanonical(b);
export const trainingKeys=(v,n)=>v!==null&&typeof v==='object'&&!Array.isArray(v)&&trainingSame(Object.keys(v).sort(),[...n].sort());
export const trainingPick=(v,n)=>Object.fromEntries(n.map(k=>[k,v[k]]));
export const trainingPositive=v=>Number.isSafeInteger(v)&&v>=1&&v<=2147483647;
export const trainingClock=v=>typeof v==='string'&&/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}Z$/u.test(v)&&documentClock(v);
export const trainingSchema=(model,value)=>Object.hasOwn(schemas,model)&&generatedSchemaMatches(schemas,model,value);
export const trainingFormSchema=model=>Object.hasOwn(schemas,model)?structuredClone(schemas[model]):null;
export const trainingTextHash=async text=>{
 if(!trainingScalar(text))throw new Error('完整原文须为有效Unicode标量字符串');
 return Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',documentUtf8(text))),v=>v.toString(16).padStart(2,'0')).join('');
};
function noFractionLexemes(raw){
 let quoted=false,escaped=false;
 for(let i=0;i<raw.length;i++){
  const char=raw[i];if(quoted){if(escaped)escaped=false;else if(char==='\\')escaped=true;else if(char==='"')quoted=false;continue;}
  if(char==='"'){quoted=true;continue;}
  if(char==='-'||/[0-9]/u.test(char)){const match=raw.slice(i).match(/^-?(?:0|[1-9]\d*)(?:\.\d+)?(?:[eE][+-]?\d+)?/u);if(match){if(/[.eE]/u.test(match[0]))throw new Error('培训闭集只接受原始整数JSON量');i+=match[0].length-1;}}
 }
}
export function parseTrainingJson(raw,max=8388608){noFractionLexemes(raw);return parseOriginalJson(raw,max);}
export function decodeTrainingPart(raw,max=8388608){
 let text=raw;
 if(typeof text!=='string'){
  const v=raw instanceof ArrayBuffer?new Uint8Array(raw):ArrayBuffer.isView(raw)?new Uint8Array(raw.buffer,raw.byteOffset,raw.byteLength):null;
  if(!v||!v.length||v.length>max)throw new Error('培训完整分件须使用原UTF8字节并遵守容量');
  text=new TextDecoder('utf-8',{fatal:true,ignoreBOM:true}).decode(v);
 }
 if(!trainingScalar(text)||!text.length||trainingBytes(text)>max)throw new Error('完整培训分件超限，未截断读取');
 return Object.freeze({raw:text,value:parseTrainingJson(text,max)});
}
export function decodeTrainingResponse(raw){
 const value=decodeTrainingPart(raw).value;
 if(!trainingKeys(value,['code','msg','data'])||value.code!==200||!trainingScalar(value.msg))throw new Error('培训回执闭集无法核对');
 return value;
}
export function trainingWhole(value,max=8388608){return scalarJsonValue(value)&&trainingBytes(value)<=max;}
