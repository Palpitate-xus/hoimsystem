import request from '@/utils/request';
import registry from './supplyResultSchemas.json';
import fixed from './supplyFixedPolicy.json';
import {decodeGeneratedSchemas,generatedSchemaMatches} from '../sofaSchema';
import {supportCanonical,supportDigest} from '../inpatientSupport';
const schemas=decodeGeneratedSchemas(registry),same=(a,b)=>supportCanonical(a)===supportCanonical(b),pick=(value,names)=>Object.fromEntries(names.map(k=>[k,value[k]]));
export const supplyProviderId=v=>Number.isSafeInteger(v)&&v>0&&v<=2147483647;
export const checkSupplyProvider=(id,revision)=>{
 if(!supplyProviderId(id)||!supplyProviderId(revision))throw new Error('物资服务标识及已保存版本须为实际正整数');
 return request({url:`ai/admin/providers/${id}/supply-capabilities`,method:'post',data:JSON.stringify({expected_revision:revision}),headers:{'Content-Type':'application/json'},retry:0});
};
export async function verifySupplyCapabilities(value){try{
 if(new TextEncoder().encode(supportCanonical(value)).length>65536||!generatedSchemaMatches(schemas,'SupplyCapabilities',value)||!same(value.recipe,fixed.recipe)||!same(value.input_policy,fixed.input_policy)||!same(value.core_sha256,fixed.core_sha256)||!same(Object.keys(value.engine_versions).sort(),['fastapi','pydantic','pydantic_settings','uvicorn']))return false;
 const runtime=pick(value,fixed.runtime_fields.filter(k=>!['runtime_digest','model_version'].includes(k)));
 return value.recipe_digest===fixed.recipe_digest&&value.input_policy_digest===fixed.input_policy_digest&&await supportDigest(value.recipe)===value.recipe_digest&&await supportDigest(value.input_policy)===value.input_policy_digest&&await supportDigest(runtime)===value.runtime_digest&&value.model_version===`supply:${value.runtime_digest}`;
}catch{return false;}}
export async function verifySupplyProviderCheck(value,provider){try{
 return value!==null&&typeof value==='object'&&!Array.isArray(value)&&Object.keys(value).sort().join(',')==='capabilities,compatible,configured_model,issues,provider_id,provider_revision,scope_note'&&supplyProviderId(provider.provider_id)&&supplyProviderId(provider.revision)&&value.provider_id===provider.provider_id&&value.provider_revision===provider.revision&&value.configured_model===provider.model&&typeof value.compatible==='boolean'&&Array.isArray(value.issues)&&value.issues.length<=32&&value.issues.every(v=>typeof v==='string'&&v.length<=4000)&&typeof value.scope_note==='string'&&value.scope_note.length<=8000&&(!value.compatible||value.configured_model===value.capabilities?.model_version&&value.issues.length===0)&&await verifySupplyCapabilities(value.capabilities);
}catch{return false;}}
