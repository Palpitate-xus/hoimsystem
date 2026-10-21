import request from '@/utils/request';
import {supportCanonical as canonical,supportId as uuid} from '../inpatientSupport';
import {documentUtf8,documentClock} from './documentEvidence';
import {decodeGeneratedSchemas,generatedSchemaMatches} from '../sofaSchema';
import {parseOriginalJson,scalarJsonValue} from './researchCohortOriginalJson';
import registry from './researchCohortSourceSchemas.json';
import policy from './researchCohortSourcePolicy.json';

const schemas=decodeGeneratedSchemas(registry),base='/ai/research-cohort';
const own=(v,k)=>Object.hasOwn(v,k),object=v=>v!==null&&typeof v==='object'&&!Array.isArray(v),same=(a,b)=>canonical(a)===canonical(b);
const bytes=v=>documentUtf8(typeof v==='string'?v:canonical(v)).length;
const meaningful=v=>typeof v==='string'&&!!v.replace(/\ufeff/gu,'').replace(/[\u0009-\u000d\u001c-\u0020\u0085\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000]/gu,'');
const basis=(v,max=4000)=>meaningful(v)&&Array.from(v).length>=20&&Array.from(v).length<=max&&bytes(v)<=4000;
const ordered=v=>Array.isArray(v)&&same(v,[...new Set(v)].sort((a,b)=>typeof a==='number'?a-b:a<b?-1:a>b?1:0));
const day=v=>{try{return typeof v==='string'&&/^\d{4}-\d{2}-\d{2}$/u.test(v)&&v.slice(0,4)!=='0000'&&new Date(v+'T00:00:00.000Z').toISOString().slice(0,10)===v;}catch{return false;}};
export const researchCohortPolicy=Object.freeze(structuredClone(policy));
export const researchCohortSchemaMatches=(model,value)=>own(schemas,model)&&generatedSchemaMatches(schemas,model,value);
export const researchCohortSchema=model=>own(schemas,model)?structuredClone(schemas[model]):null;
export const researchCohortBasis=basis;
export function researchCohortCriteriaValid(value){try{
 if(!generatedSchemaMatches(schemas,'CaptureRequest',value,'CohortCriteria'))return false;
 let count=0;
 const visit=(node,depth)=>{
  if(!object(node)||++count>policy.max_criteria_nodes||depth>policy.max_criteria_depth)return false;
  if(['all','any'].includes(node.op))return Array.isArray(node.children)&&node.children.every(v=>visit(v,depth+1));
  if(node.op==='not')return visit(node.child,depth+1);
  const fields=node.op==='recorded_scalar_equal'?policy.scalar_fields:node.op==='recorded_date_compare'?policy.date_fields:node.op==='recorded_text_contains'?policy.text_fields:null;
  if(!fields?.[node.family]?.includes(node.field))return false;
  return node.op!=='recorded_date_compare'||day(node.expected);
 };
 return visit(value.root,1);
}catch{return false;}}
export function researchCohortRequestValid(model,value){try{
 if(!['ScopeCreate','ProjectACLCreate','PatientAuthorizationCreate','AuthorizationReview','SourceReview','SourceRevoke','CaptureRequest','CaseCreate'].includes(model)||!researchCohortSchemaMatches(model,value)||!scalarJsonValue(value)||bytes(value)>policy.max_source_bytes)return false;
 if(['ScopeCreate','ProjectACLCreate','PatientAuthorizationCreate'].includes(model)&&bytes(value)>262144)return false;
 if(model==='ScopeCreate'){
  if(![value.patient_ids,value.proposed_user_ids,value.data_families,value.permitted_uses].every(ordered)||!basis(value.purpose)||!basis(value.authorization_basis)||!basis(value.external_model_use_basis)||!documentClock(value.valid_from)||!documentClock(value.valid_until)||value.valid_from>=value.valid_until)return false;
  const w=value.record_window;if(!day(w.date_from)||!day(w.date_to))return false;
  const days=(Date.parse(w.date_to+'T00:00:00Z')-Date.parse(w.date_from+'T00:00:00Z'))/86400000;
  return days>=0&&days<366;
 }
 if(model==='CaptureRequest')return researchCohortCriteriaValid(value.criteria);
 if(model==='CaseCreate')return basis(value.basis_note)&&researchCohortRequestValid('CaptureRequest',value.request);
 if(!basis(value.basis_note,model==='SourceRevoke'?1000:4000))return false;
 if(model==='ProjectACLCreate')return documentClock(value.valid_from)&&documentClock(value.valid_until)&&value.valid_from<value.valid_until;
 if(model==='PatientAuthorizationCreate')return value.valid_from===null?value.valid_until===null:documentClock(value.valid_from)&&documentClock(value.valid_until)&&value.valid_from<value.valid_until;
 return true;
}catch{return false;}}

export function decodeResearchCohortResponse(raw){
 if(!(raw instanceof ArrayBuffer)&&!ArrayBuffer.isView(raw))throw new Error('科研来源必须按完整原UTF8字节读取');
 const view=raw instanceof ArrayBuffer?new Uint8Array(raw):new Uint8Array(raw.buffer,raw.byteOffset,raw.byteLength);
 if(view.byteLength<1||view.byteLength>policy.max_response_bytes)throw new Error('科研来源组合回执超过32MiB，未截断读取');
 const text=new TextDecoder('utf-8',{fatal:true,ignoreBOM:true}).decode(view),value=parseOriginalJson(text,policy.max_response_bytes);
 if(!object(value)||!same(Object.keys(value).sort(),['code','data','msg'])||value.code!==200||typeof value.msg!=='string')throw new Error('科研来源回执闭集或状态无法核对');
 return value;
}
const id=value=>{if(!uuid(value))throw new Error('科研来源需要明确规范UUID');return value;};
const query=(params,allowed)=>{if(!object(params)||Object.keys(params).some(k=>!allowed.includes(k)))throw new Error('科研来源查询范围无效');return params;};
const read=(url,params={})=>request({url,method:'get',params,responseType:'arraybuffer',retry:0}).then(decodeResearchCohortResponse);
const write=(url,value,model)=>{if(!researchCohortRequestValid(model,value))throw new Error('请完整填写本次项目用途、明确授权和治理依据');return request({url,method:'post',data:JSON.stringify(value),headers:{'Content-Type':'application/json'},responseType:'arraybuffer',retry:0}).then(decodeResearchCohortResponse);};
const audit=options=>{if(options===undefined)return {audit_only:false};if(!object(options)||Object.keys(options).some(k=>k!=='auditOnly')||typeof options.auditOnly!=='boolean')throw new Error('冻结科研读取须明确布尔选择');return {audit_only:options.auditOnly};};
export const getResearchScope=(value,options)=>read(`${base}/scopes/${id(value)}`,audit(options));
export const createResearchScope=value=>write(`${base}/scopes`,value,'ScopeCreate');
export const authorizeResearchScope=(value,body)=>write(`${base}/scopes/${id(value)}/authorization-review`,body,'AuthorizationReview');
export const reviewResearchScope=(value,body)=>write(`${base}/scopes/${id(value)}/review`,body,'SourceReview');
export const revokeResearchScope=(value,body)=>write(`${base}/scopes/${id(value)}/revoke`,body,'SourceRevoke');
export const getResearchProjectACL=(value,options)=>read(`${base}/project-acls/${id(value)}`,audit(options));
export const createResearchProjectACL=value=>write(`${base}/project-acls`,value,'ProjectACLCreate');
export const reviewResearchProjectACL=(value,body)=>write(`${base}/project-acls/${id(value)}/review`,body,'SourceReview');
export const revokeResearchProjectACL=(value,body)=>write(`${base}/project-acls/${id(value)}/revoke`,body,'SourceRevoke');
export const getResearchPatientAuthorization=(value,options)=>read(`${base}/patient-authorizations/${id(value)}`,audit(options));
export const createResearchPatientAuthorization=value=>write(`${base}/patient-authorizations`,value,'PatientAuthorizationCreate');
export const authorizeResearchPatientAuthorization=(value,body)=>write(`${base}/patient-authorizations/${id(value)}/authorization-review`,body,'AuthorizationReview');
export const reviewResearchPatientAuthorization=(value,body)=>write(`${base}/patient-authorizations/${id(value)}/review`,body,'SourceReview');
export const revokeResearchPatientAuthorization=(value,body)=>write(`${base}/patient-authorizations/${id(value)}/revoke`,body,'SourceRevoke');
export const previewResearchCase=value=>write(`${base}/cases/preview`,value,'CaptureRequest');
export const createResearchCase=value=>write(`${base}/cases`,value,'CaseCreate');
export const getResearchCase=(value,options)=>read(`${base}/cases/${id(value)}`,audit(options));
export const reviewResearchCase=(value,body)=>write(`${base}/cases/${id(value)}/review`,body,'SourceReview');
export const revokeResearchCase=(value,body)=>write(`${base}/cases/${id(value)}/revoke`,body,'SourceRevoke');
export function getResearchCases(params){
 query(params,['scope_id','page','size']);id(params.scope_id);
 if(params.page!==undefined&&(!Number.isSafeInteger(params.page)||params.page<1||params.page>100000)||params.size!==undefined&&(!Number.isSafeInteger(params.size)||params.size<1||params.size>100))throw new Error('科研病例目录分页必须明确且有界');
 return read(`${base}/cases`,params);
}

function registryPage(params,scoped){
 query(params,scoped?['scope_id','page','size']:['page','size']);
 if(scoped)id(params.scope_id);
 if(params.page!==undefined&&(!Number.isSafeInteger(params.page)||params.page<1||params.page>100000)||params.size!==undefined&&(!Number.isSafeInteger(params.size)||params.size<1||params.size>100))throw new Error('科研治理目录分页须明确且有界');
 return params;
}
export const getResearchScopes=(params={})=>read(`${base}/scopes`,registryPage(params,false));
export const getResearchProjectACLs=params=>read(`${base}/project-acls`,registryPage(params,true));
export const getResearchPatientAuthorizations=params=>read(`${base}/patient-authorizations`,registryPage(params,true));
