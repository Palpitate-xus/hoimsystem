import request from '@/utils/request';
import registry from './deidentificationTaskSchemas.json';
import{decodeGeneratedSchemas,generatedSchemaMatches}from'../sofaSchema';
import{deidentificationId as uuid,keys,scalar,bytes}from'./deidentificationCore';
import{decodeDeidentificationWire}from'./deidentificationWire';
const schemas=decodeGeneratedSchemas(registry),BASE='ai/deidentification/tasks';
export const deidentificationTaskSchemaMatches=(name,value)=>generatedSchemaMatches(schemas,name,value);
export function deidentificationReferencesValid(v){return keys(v,['deidentification_case_id'])&&uuid(v.deidentification_case_id);}
export function deidentificationTaskInputValid(v){return deidentificationTaskSchemaMatches('TaskInput',v)&&(v.question===undefined||v.question===null||scalar(v.question)&&bytes(v.question)<=8000);}
const id=value=>{if(!uuid(value))throw new Error('明确75任务标识无效');return value;};
async function wire(url,{method='get',data,params}={}){const raw=await request({url:BASE+url,method,params,...(data===undefined?{}:{data:JSON.stringify(data),headers:{'Content-Type':'application/json'}}),responseType:'arraybuffer',retry:0});return decodeDeidentificationWire(raw);}
const taskBody=(input,preview)=>{if(!deidentificationTaskInputValid(input)||typeof preview!=='boolean')throw new Error('75任务仅接收明确来源引用与原样可选问题');return{input,preview};};
export const previewDeidentificationTask=(input,{preview=false}={})=>wire('/context',{method:'post',data:taskBody(input,preview)});
export const createDeidentificationTask=(input,{preview=false}={})=>wire('',{method:'post',data:taskBody(input,preview)});
export const getDeidentificationTask=(value,{audit_only=false}={})=>wire('/'+id(value),{params:{audit_only}});
export const getDeidentificationTaskSource=(value,{audit_only=false}={})=>wire('/'+id(value)+'/source',{params:{audit_only}});
export const getDeidentificationTaskResult=(value,{audit_only=false}={})=>wire('/'+id(value)+'/result',{params:{audit_only}});
export const getDeidentificationTaskTechnical=value=>wire('/'+id(value)+'/technical');
export const getDeidentificationTaskTrace=value=>wire('/'+id(value)+'/trace');
export const cancelDeidentificationTask=value=>wire('/'+id(value)+'/cancel',{method:'post',data:{}});
