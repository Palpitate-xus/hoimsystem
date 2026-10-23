import request from '@/utils/request';

const fields='schema_version run_id feature_key feature_name status native_domains native_identity_state native_feature_key feature_matches_native_contract requested_by provider_id provider_revision prompt_version preview create_time start_time finish_time feedback_count usage_verification input_tokens output_tokens'.split(' ');
const domains={charge:'charge_reconciliation',satisfaction:'feedback_analysis',document:'guideline_ingestion',drug_label:'drug_label_extraction',document_change:'guideline_change_review',research_cohort:'research_cohort',deidentification:'deidentification',operations_support:'operations_support',clinical_training:'clinical_training',rca:'incident_rca',infection:'infection_cluster',research_variables:'research_extraction'};
const object=v=>v!==null&&typeof v==='object'&&!Array.isArray(v);
const keys=(v,names)=>object(v)&&Object.keys(v).length===names.length&&names.every(name=>Object.hasOwn(v,name));
const positive=v=>Number.isSafeInteger(v)&&v>0;
const nullable=(v,test)=>v===null||test(v);
const clock=v=>nullable(v,value=>typeof value==='string'&&/^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d{1,6})?$/u.test(value));

export function technicalTaskValid(row){
 if(!keys(row,fields)||row.schema_version!=='global_ai_task_technical_v1'||typeof row.run_id!=='string'||!row.run_id.length||[...row.run_id].length>36)return false;
 if(!nullable(row.feature_key,v=>typeof v==='string'&&/^[a-z][a-z0-9_]{0,63}$/u.test(v))||!nullable(row.feature_name,v=>typeof v==='string'&&v.length>0&&v.length<=200))return false;
 if(!['queued','running','succeeded','failed','cancelled','invalid'].includes(row.status)||!Array.isArray(row.native_domains)||row.native_domains.length>12||row.native_domains.some(name=>!Object.hasOwn(domains,name))||JSON.stringify(row.native_domains)!==JSON.stringify([...new Set(row.native_domains)].sort()))return false;
 const count=row.native_domains.length,state=row.native_identity_state;
 if(!(['unique','invalid'].includes(state)?count===1:state==='conflicting'?count>1:state==='unproven'&&count===0))return false;
 const native=count===1?domains[row.native_domains[0]]:null;
 if(row.native_feature_key!==native||row.feature_matches_native_contract!==(native===null?null:row.feature_key===native))return false;
 if(['requested_by','provider_id','provider_revision'].some(name=>!nullable(row[name],positive))||!nullable(row.prompt_version,v=>Number.isSafeInteger(v)&&v>=0)||!nullable(row.preview,v=>typeof v==='boolean'))return false;
 return ['create_time','start_time','finish_time'].every(name=>clock(row[name]))&&Number.isSafeInteger(row.feedback_count)&&row.feedback_count>=0&&row.usage_verification==='not_verified'&&row.input_tokens===null&&row.output_tokens===null;
}

export async function readTechnicalTasks(params,{current}){
 if(!current())return null;
 const response=await request({url:'ai/admin/task-directory',method:'get',params});
 if(!current())return null;
 const valid=keys(response,['code','msg','data','total','page','page_size'])&&response.code===200&&typeof response.msg==='string'&&response.page===params.page&&response.page_size===params.page_size&&Number.isSafeInteger(response.total)&&response.total>=0&&Array.isArray(response.data)&&response.data.length===Math.min(params.page_size,Math.max(0,response.total-(params.page-1)*params.page_size))&&response.data.every(technicalTaskValid)&&new Set(response.data.map(row=>row.run_id)).size===response.data.length;
 if(!valid)throw new Error('全局任务技术目录闭集或分页无法核对');
 return JSON.parse(JSON.stringify(response));
}
