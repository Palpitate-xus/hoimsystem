import request from '@/utils/request';
import registry from './inventoryResultSchemas.json';
import fixed from './inventoryFixedPolicy.json';
import {decodeGeneratedSchemas,generatedSchemaMatches} from '../sofaSchema';
import {supportCanonical,supportDigest} from '../inpatientSupport';
const schemas=decodeGeneratedSchemas(registry),same=(a,b)=>supportCanonical(a)===supportCanonical(b),pick=(value,names)=>Object.fromEntries(names.map(k=>[k,value[k]]));
export const inventoryProviderId=v=>Number.isSafeInteger(v)&&v>0&&v<=2147483647;
export const checkInventoryProvider=(id,revision)=>{
 if(!inventoryProviderId(id)||!inventoryProviderId(revision))throw new Error('库存候选比较服务标识及已保存版本须为实际正整数');
 return request({url:`ai/admin/providers/${id}/inventory-capabilities`,method:'post',data:JSON.stringify({expected_revision:revision}),headers:{'Content-Type':'application/json'},retry:0});
};
export async function verifyInventoryCapabilities(value){try{
 if(new TextEncoder().encode(supportCanonical(value)).length>65536||!generatedSchemaMatches(schemas,'InventoryCapabilities',value)||!same(value.recipe,fixed.recipe)||!same(value.input_policy,fixed.input_policy)||!same(value.core_sha256,fixed.core_sha256)||!same(Object.keys(value.engine_versions).sort(),['fastapi','pydantic','pydantic_settings','uvicorn']))return false;
 const runtime=pick(value,fixed.runtime_fields.filter(k=>!['runtime_digest','model_version'].includes(k)));
 return value.recipe_digest===fixed.recipe_digest&&value.input_policy_digest===fixed.input_policy_digest&&await supportDigest(value.recipe)===value.recipe_digest&&await supportDigest(value.input_policy)===value.input_policy_digest&&await supportDigest(runtime)===value.runtime_digest&&value.model_version===`inventory:${value.runtime_digest}`;
}catch{return false;}}
export async function verifyInventoryProviderCheck(value,provider){try{
 return value!==null&&typeof value==='object'&&!Array.isArray(value)&&Object.keys(value).sort().join(',')==='capabilities,compatible,configured_model,issues,provider_id,provider_revision,scope_note'&&inventoryProviderId(provider.provider_id)&&inventoryProviderId(provider.revision)&&value.provider_id===provider.provider_id&&value.provider_revision===provider.revision&&typeof provider.model==='string'&&value.configured_model===provider.model&&typeof value.compatible==='boolean'&&Array.isArray(value.issues)&&value.issues.length<=32&&new Set(value.issues).size===value.issues.length&&value.issues.every(v=>typeof v==='string'&&v.length<=4000)&&typeof value.scope_note==='string'&&value.scope_note.length<=8000&&value.compatible===(value.issues.length===0)&&(!value.compatible||value.configured_model===value.capabilities?.model_version)&&await verifyInventoryCapabilities(value.capabilities);
}catch{return false;}}
