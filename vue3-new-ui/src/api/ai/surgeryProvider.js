import request from '@/utils/request';
import registry from './surgeryProviderSchemas.json';
import fixed from './surgeryFixedPolicy.json';
import {decodeGeneratedSchemas,generatedSchemaMatches} from '../sofaSchema';
import {supportCanonical,supportDigest} from '../inpatientSupport';
import {surgeryPositive} from './surgerySources';

const schemas=decodeGeneratedSchemas(registry),same=(a,b)=>supportCanonical(a)===supportCanonical(b),pick=(v,names)=>Object.fromEntries(names.map(k=>[k,v[k]]));
export const checkSurgeryProvider=(id,revision)=>{
 if(!surgeryPositive(id)||!surgeryPositive(revision))throw new Error('手术服务标识和已保存版本须为实际正整数');
 return request({url:`ai/admin/providers/${id}/surgery-capabilities`,method:'post',data:JSON.stringify({expected_revision:revision}),headers:{'Content-Type':'application/json'},retry:0});
};
export async function verifySurgeryCapabilities(value){
 try{
  if(new TextEncoder().encode(supportCanonical(value)).length>65536||!generatedSchemaMatches(schemas,'SurgeryCapabilities',value)||!same(value.recipe,fixed.recipe)||!same(value.input_policy,fixed.input_policy)||!same(value.core_sha256,fixed.core_sha256)||!same(Object.keys(value.engine_versions).sort(),['fastapi','pydantic','pydantic_settings','uvicorn'])||![value.python_version,...Object.values(value.engine_versions)].every(v=>typeof v==='string'&&/^\d+\.\d+\.\d+(?:[A-Za-z0-9.+_-]{0,50})?$/.test(v)))return false;
  const runtime=pick(value,fixed.runtime_fields.filter(k=>!['runtime_digest','model_version'].includes(k)));
  return value.recipe_digest===fixed.recipe_digest&&value.input_policy_digest===fixed.input_policy_digest&&await supportDigest(value.recipe)===value.recipe_digest&&await supportDigest(value.input_policy)===value.input_policy_digest&&await supportDigest(runtime)===value.runtime_digest&&value.model_version===`surgery:${value.runtime_digest}`;
 }catch{return false;}
}
export async function verifySurgeryProviderCheck(value,provider){
 try{
  return value!==null&&typeof value==='object'&&!Array.isArray(value)&&Object.keys(value).sort().join(',')==='capabilities,compatible,configured_model,issues,provider_id,provider_revision,scope_note'&&surgeryPositive(provider.provider_id)&&surgeryPositive(provider.revision)&&value.provider_id===provider.provider_id&&value.provider_revision===provider.revision&&value.configured_model===provider.model&&typeof value.compatible==='boolean'&&Array.isArray(value.issues)&&value.issues.length<=32&&value.issues.every(v=>typeof v==='string'&&v.length<=4000)&&typeof value.scope_note==='string'&&value.scope_note.length<=8000&&(!value.compatible||value.configured_model===value.capabilities?.model_version&&value.issues.length===0)&&await verifySurgeryCapabilities(value.capabilities);
 }catch{return false;}
}
