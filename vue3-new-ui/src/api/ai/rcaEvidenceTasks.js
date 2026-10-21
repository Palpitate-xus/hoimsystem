import request from '@/utils/request';
import {rcaReply,parseRcaJson,rcaSchema,rcaKeys,rcaId,rcaBytes,rcaBound,RCA_WIRE} from './rcaEvidenceProofs';
const id=v=>{if(!rcaId(v))throw new Error('需要原任务规范UUID');return v;};
export function rcaTaskInputValid(value){try{return rcaSchema('RcaTaskSelection',value)&&rcaBound(value)&&(value.question===undefined||value.question===null||rcaBytes(value.question)<=8000);}catch{return false;}}
export const rcaReferencesValid=v=>rcaKeys(v,['rca_evidence_case_id'])&&rcaId(v.rca_evidence_case_id);
const read=async(url,params={})=>rcaReply(await request({url,params,method:'get',responseType:'arraybuffer',retry:0}));
const write=async(url,data)=>rcaReply(await request({url,data:JSON.stringify(data),method:'post',responseType:'arraybuffer',headers:{'Content-Type':'application/json'},retry:0}));
export function getRcaPreview(input,{preview=false}={}){if(!rcaTaskInputValid(input)||typeof preview!=='boolean')throw new Error('须明确选择真实Case与原样可选问题');return write('ai/rca-evidence/context',{...input,preview});}
export function createRcaTask(input,{preview=false}={}){if(!rcaTaskInputValid(input)||typeof preview!=='boolean')throw new Error('须为本项唯一Case引用，不得混入其它范围或正文');return write('ai/runs',{feature_key:'incident_rca',input,preview});}
export const getRcaTask=(value,{auditOnly=false}={})=>{if(typeof auditOnly!=='boolean')throw new Error('明确当前或冻结审计');return read(`ai/${auditOnly?'admin/':''}runs/${id(value)}`);};
export const getRcaTaskPart=(value,part,{auditOnly=false}={})=>{if(!['source','case','result','receipt'].includes(part)||typeof auditOnly!=='boolean')throw new Error('仅允许本任务四类完整分件');return read(`ai/${auditOnly?'admin/':''}runs/${id(value)}/rca-evidence/${part}`);};
export const cancelRcaTask=value=>write(`ai/runs/${id(value)}/cancel`,{});
export async function getRcaTaskHistory({caseId=null,page=1,pageSize=20,auditOnly=false}={}){
 if(caseId!==null&&!rcaId(caseId)||!Number.isSafeInteger(page)||page<1||page>100000||!Number.isSafeInteger(pageSize)||pageSize<1||pageSize>100||typeof auditOnly!=='boolean')throw new Error('需要本项明确历史范围和分页');
 const raw=await request({url:`ai/${auditOnly?'admin/':''}runs`,params:{feature_key:'incident_rca',...(caseId!==null?{rca_evidence_case_id:caseId}:{}),page,page_size:pageSize},method:'get',responseType:'arraybuffer',retry:0});
 if(!(raw instanceof ArrayBuffer)||raw.byteLength>RCA_WIRE)throw new Error('完整任务目录超限');return parseRcaJson(new TextDecoder('utf-8',{fatal:true,ignoreBOM:true}).decode(new Uint8Array(raw)));
}
