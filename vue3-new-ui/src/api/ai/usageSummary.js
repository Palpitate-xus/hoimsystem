import request from '@/utils/request';

const fields='feature_key status count recorded_count pending_count invalid_count unverified_count input_tokens input_tokens_known_sum input_tokens_known_count input_tokens_unknown_count output_tokens output_tokens_known_sum output_tokens_known_count output_tokens_unknown_count model_call_attempted_count model_call_unattempted_count model_call_unknown_count local_calculation_count local_calculation_attempted_count local_calculation_unattempted_count local_calculation_unknown_count local_calculation_ms_known_sum local_calculation_ms_known_count'.split(' ');
const object=value=>value!==null&&typeof value==='object'&&!Array.isArray(value);
const keys=(value,names)=>object(value)&&Object.keys(value).length===names.length&&names.every(name=>Object.hasOwn(value,name));
const count=value=>Number.isSafeInteger(value)&&value>=0;

export function usageRowValid(row){
 if(!keys(row,fields)||!(row.feature_key===null||typeof row.feature_key==='string'&&/^[a-z][a-z0-9_]{0,63}$/u.test(row.feature_key))||!['queued','running','succeeded','failed','cancelled','invalid'].includes(row.status)||!count(row.count)||row.count===0)return false;
 if(fields.filter(name=>name!=='feature_key'&&name!=='status'&&!['input_tokens','output_tokens'].includes(name)).some(name=>!count(row[name])))return false;
 if(['recorded','pending','invalid','unverified'].reduce((sum,name)=>sum+row[name+'_count'],0)!==row.count)return false;
 for(const key of ['input_tokens','output_tokens']){
  const known=row[key+'_known_count'],unknown=row[key+'_unknown_count'],sum=row[key+'_known_sum'];
  if(known>row.recorded_count||known+unknown!==row.count||known===0&&sum!==0||row[key]!== (unknown===0?sum:null))return false;
 }
 if(row.model_call_attempted_count+row.model_call_unattempted_count+row.model_call_unknown_count!==row.count||row.model_call_attempted_count+row.model_call_unattempted_count>row.recorded_count)return false;
 const local=row.local_calculation_count;
 return local<=row.count&&row.local_calculation_attempted_count+row.local_calculation_unattempted_count+row.local_calculation_unknown_count===local&&row.local_calculation_ms_known_count<=local&&(row.local_calculation_ms_known_count!==0||row.local_calculation_ms_known_sum===0);
}

export function usageSummaryValid(value){
 return keys(value,['code','msg','schema_version','accounting_scope','coverage','data'])&&value.code===200&&typeof value.msg==='string'&&value.schema_version==='global_ai_usage_summary_v2'&&value.accounting_scope==='specific_usage_audit_record_without_source_or_result_content_validation'&&keys(value.coverage,['total','scanned','complete'])&&count(value.coverage.total)&&value.coverage.scanned===value.coverage.total&&value.coverage.complete===true&&Array.isArray(value.data)&&value.data.every(usageRowValid)&&value.data.reduce((sum,row)=>sum+row.count,0)===value.coverage.total&&new Set(value.data.map(row=>JSON.stringify([row.feature_key,row.status]))).size===value.data.length;
}

export function usageCountLabel(row,key){
 const unknown=row[key+'_unknown_count'];
 return unknown===0?String(row[key]):row[key+'_known_count']===0?`未知（${unknown}项）`:`已知${row[key+'_known_sum']}；另${unknown}项未知`;
}

export async function readUsageSummary({current}){
 if(!current())return null;
 const value=await request({url:'ai/admin/usage',method:'get'});
 if(!current())return null;
 if(!usageSummaryValid(value))throw new Error('调用统计闭集、覆盖范围或独立未知用量无法核对');
 return JSON.parse(JSON.stringify(value));
}
