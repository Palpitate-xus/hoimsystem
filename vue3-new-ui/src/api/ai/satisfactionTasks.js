import request from '@/utils/request';
import {supportCanonical as canonical,supportDigest as digest,supportId as uuid} from '@/api/inpatientSupport';
import {scalarJsonValue} from './nativeOriginalJson';
import {getSatisfactionCase,satisfactionReferencesValid,verifySatisfactionCase} from './satisfactionSources';
import {verifySatisfactionContext,verifySatisfactionRun,verifySatisfactionReceipt,satisfactionResultBudgets} from './satisfactionResults';

const object=v=>v!==null&&typeof v==='object'&&!Array.isArray(v),same=(a,b)=>canonical(a)===canonical(b),own=(v,k)=>Object.hasOwn(v,k),bytes=v=>new TextEncoder().encode(typeof v==='string'?v:canonical(v)).length;
const id=v=>{if(!uuid(v))throw new Error('评价任务标识必须为规范UUID');return v;};
const json=value=>({data:JSON.stringify(value),headers:{'Content-Type':'application/json'}});
export function satisfactionTaskInputValid(input,{allowEmpty=false}={}){try{return object(input)&&scalarJsonValue(input)&&Object.keys(input).every(k=>['satisfaction_case_id','question'].includes(k))&&(!own(input,'satisfaction_case_id')?allowEmpty:uuid(input.satisfaction_case_id))&&(!own(input,'question')||input.question===null||typeof input.question==='string'&&Array.from(input.question).length<=2000&&bytes(input.question)<=8000);}catch{return false;}}
export function previewSatisfactionTask(input){if(!satisfactionTaskInputValid(input))throw new Error('须明确一个评价原件，仅可另附未改写的问题');return request({url:'/ai/operational-context',method:'post',...json({feature_key:'feedback_analysis',input}),retry:0});}
export function createSatisfactionTask(input,preview){if(!satisfactionTaskInputValid(input)||typeof preview!=='boolean')throw new Error('评价原件或明确试运行标志无效');return request({url:'/ai/runs',method:'post',...json({feature_key:'feedback_analysis',input,preview}),retry:0});}
export const getSatisfactionTask=runId=>request({url:`/ai/runs/${id(runId)}`,method:'get',retry:0});
export function getSatisfactionTaskHistory(caseId){id(caseId);return request({url:'/ai/runs',method:'get',params:{feature_key:'feedback_analysis',satisfaction_case_id:caseId,satisfaction_native_only:true,limit:30},retry:0});}
export const cancelSatisfactionTask=runId=>request({url:`/ai/runs/${id(runId)}/cancel`,method:'post',retry:0});
export function feedbackSatisfactionTask(runId,outcome,comment){if(!['accepted','rejected','modified'].includes(outcome)||typeof comment!=='string'||!scalarJsonValue(comment)||Array.from(comment).length>2000||bytes(comment)>8000)throw new Error('须明确有效的本次人工反馈');return request({url:`/ai/runs/${id(runId)}/feedback`,method:'post',...json({outcome,comment}),retry:0});}

export async function readCurrentSatisfactionCase(references,{current=()=>true}={}){
 if(!satisfactionReferencesValid(references))throw new Error('当前评价范围须仅含一个明确原件');
 const row=(await getSatisfactionCase(references.satisfaction_case_id,{auditOnly:false})).data;
 if(!current())return null;
 if(row.case_id!==references.satisfaction_case_id||!row.eligible||row.audit_only||!await verifySatisfactionCase(row,{auditOnly:false}))throw new Error('当前完整评价原件、发布状态或授权无法核对');
 return current()?row:null;
}
export async function verifySatisfactionTaskPreview(value,input,original,{current=()=>true}={}){try{
 if(!current()||!satisfactionTaskInputValid(input)||!object(value)||!same(Object.keys(value).sort(),['context','evidence','metadata'])||!scalarJsonValue(value)||bytes(value)>satisfactionResultBudgets.context||!await verifySatisfactionContext(value.context,{references:{satisfaction_case_id:input.satisfaction_case_id}})||!current())return false;
 const c=value.context,b=c.satisfaction_binding,short=Object.fromEntries(Object.entries(c).filter(([key])=>!['satisfaction_source','satisfaction_case'].includes(key)));
 const metadata={snapshot_time:c.snapshot_time,source_count:1,department_ids:[],context_digest:await digest(short),clinical_context_fingerprint:await digest(Object.fromEntries(Object.entries(short).filter(([key])=>key!=='snapshot_time'))),missing_data:c.missing_data};
 return current()&&b.content_hash===original.content_hash&&same(c.satisfaction_source,original.public_source)&&same(value.metadata,metadata)&&same(value.evidence,[{source_id:b.source_id,kind:'operational_record',title:'完整评价与明确选择人工摘录的安全冻结依据',content:canonical({satisfaction_binding:b})}]);
}catch{return false;}}
const stable=['run_id','feature_key','preview','prompt_version','provider_revision','context_digest','patient_id','encounter_ref','create_time','feature_name','requires_human_review','context_metadata'];
export async function readVerifiedSatisfactionTask(runId,{references,receipt=null,preview=null,current=()=>true}={}){
 const original=await readCurrentSatisfactionCase(references,{current});if(!current()||!original)return null;
 const run=(await getSatisfactionTask(runId)).data;if(!current())return null;
 if(!await verifySatisfactionRun(run,{runId,references})||!current())throw new Error('完整评价任务、精确统计或逐字主题依据无法核对');
 const binding=run.satisfaction_findings.satisfaction_binding;
 if(binding.content_hash!==original.content_hash||!same(run.satisfaction_findings.satisfaction_source,original.public_source)||preview!==null&&run.preview!==Number(preview)||receipt&&(!await verifySatisfactionReceipt(receipt,{runId})||!same(Object.fromEntries(stable.map(k=>[k,receipt[k]])),Object.fromEntries(stable.map(k=>[k,run[k]])))))throw new Error('完整任务与当前原件、冻结版本或短回执不一致');
 return current()?{run,original,references:{...references}}:null;
}
