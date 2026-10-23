import request from '@/utils/request';
import {parseOriginalJson} from './nativeOriginalJson';
import {basis,bytes,canonical,clock,digest,fixed,keys,modelValid,nonblank,object,same,schema,unique,uuid,verifyPrivateCollection,verifyProfile,verifyPublicSource,verifyRegistryRecord,verifyScenario,windowValid} from './infectionClusterProofs';
export {schema as infectionSchema,verifyRegistryRecord,verifyPrivateCollection,verifyPublicSource,verifyScenario,verifyProfile};
export const infectionReferencesValid=v=>keys(v,['infection_cluster_scenario_id'])&&uuid(v.infection_cluster_scenario_id);
const validRole=new Set(['admin','super_admin','director','doctor','nurse','cashier','pharmacist','guide','patient','lab_technician','registrar']);
export function infectionRequestValid(name,v){try{
 if(!modelValid(name,v))return false;
 if(Object.hasOwn(v,'basis_note')&&!basis(v.basis_note))return false;
 if(name==='GrantCreate')return clock(v.valid_from)&&clock(v.valid_to)&&v.valid_from<v.valid_to;
 if(name==='DefinitionCreate')return nonblank(v.version_label)&&nonblank(v.definition_text)&&unique(v.infection_type_codes)&&unique(v.pathogen_codes);
 if(name==='GovernReview'||name==='ScenarioReview'){const flags=[v.privacy_review,v.faithfulness_review,...(name==='ScenarioReview'?[v.parameters_review]:[])];return(v.decision==='publish')===flags.every(f=>f==='confirmed');}
 if(name==='CaseReviewCreate')return['infection_type','pathogen'].every(f=>{const m=v[f];return basis(m.basis_note)&&(m.assessment==='mapped')===(m.reviewed_code!==null)&&(m.assessment!=='mapped'||m.original_state==='present');});
 if(name==='SnapshotCreate')return unique(v.patient_ids)&&windowValid(v.window);
 if(name==='ScenarioCreate')return unique(v.department_ids)&&unique(v.windows.map(w=>canonical(w)))&&v.windows.every(windowValid)&&v.department_ids.length*v.windows.length<=256&&/^0\.[0-9]{1,12}$/.test(v.alpha_decimal)&&/[1-9]/.test(v.alpha_decimal.slice(2));
 if(name==='ProfileCreate')return nonblank(v.version_label)&&unique(v.scope.department_ids)&&unique(v.scope.pathogen_codes)&&unique(v.scope.alpha_decimals)&&v.scope.alpha_decimals.every(a=>/^0\.[0-9]{1,12}$/.test(a)&&/[1-9]/.test(a.slice(2)))&&windowValid(v.scope.source_window)&&basis(v.validation_basis_note)&&v.expected_implementation_hash!==null&&(!['pilot','validated'].includes(v.validation_status)||v.validation_evidence_reference!==null)&&(v.validation_evidence_reference===null||nonblank(v.validation_evidence_reference)&&bytes(v.validation_evidence_reference)<=4000);
 if(name==='LocalConfigWrite')return unique(v.allowed_roles)&&v.allowed_roles.every(r=>validRole.has(r))&&(!v.enabled||v.profile_id!==null&&v.validation_status==='validated')&&(!['pilot','validated'].includes(v.validation_status)||typeof v.validation_note==='string'&&Array.from(v.validation_note.replace(/^[\s\u0085\u001c-\u001f]+|[\s\u0085\u001c-\u001f]+$/gu,'')).length>=10)&&(v.validation_note===null||bytes(v.validation_note)<=20000);
 return name==='CAS';
}catch{return false;}}
function lexical(raw){let depth=0,tokens=0,string=false,escaped=false;for(const char of raw){if(string){if(escaped)escaped=false;else if(char==='\\')escaped=true;else if(char==='"')string=false;}else if(char==='"'){tokens++;string=true;}else if(char==='['||char==='{'){depth++;tokens++;if(depth>fixed.max_json_depth)throw new Error('完整JSON深度超限');}else if(char===']'||char==='}')depth--;else if(char===','||char===':')tokens++;if(tokens>fixed.max_json_tokens)throw new Error('完整JSON结构工作量超限');}}
export function decodeInfectionResponse(value){if(!(value instanceof ArrayBuffer)&&!ArrayBuffer.isView(value))throw new Error('须保留完整HTTP原字节');const rawBytes=value instanceof ArrayBuffer?new Uint8Array(value):new Uint8Array(value.buffer,value.byteOffset,value.byteLength);if(rawBytes.length===0||rawBytes.length>fixed.whole_bytes)throw new Error('完整响应超过8MiB，未接受截取件');const raw=new TextDecoder('utf-8',{fatal:true,ignoreBOM:true}).decode(rawBytes);lexical(raw);const wrapper=parseOriginalJson(raw,fixed.whole_bytes);if(!keys(wrapper,['code','msg','data'])||wrapper.code!==200||typeof wrapper.msg!=='string')throw new Error('来源回执不是完整闭集成功响应');return wrapper;}
export async function infectionHttp(path,{method='get',params,data}={}){const raw=await request({url:'/ai/infection-cluster'+path,method,params,...(data===undefined?{}:{data:JSON.stringify(data),headers:{'Content-Type':'application/json'}}),responseType:'arraybuffer',retry:0});return decodeInfectionResponse(raw);}
const id=value=>{if(!uuid(value))throw new Error('须明确规范原件UUID');return value;};
const kind=value=>{if(!['grant','definition','review'].includes(value))throw new Error('须明确来源登记类型');return value;};
const query=(page,size)=>{if(!Number.isSafeInteger(page)||page<1||!Number.isSafeInteger(size)||size<1||size>100)throw new Error('须明确完整分页');return{page,size};};
const write=(path,name,value,method='post')=>{if(!infectionRequestValid(name,value))throw new Error('须完整明确本次来源、治理依据、原始参数和CAS');return infectionHttp(path,{method,data:value});};
export const getInfectionRegistry=(value,{page=1,size=20}={})=>infectionHttp('/registry/'+kind(value),{params:query(page,size)});
export const getInfectionRegistryRecord=(type,value)=>infectionHttp('/registry/'+kind(type)+'/'+id(value));
export const createInfectionRegistry=(type,value)=>write({grant:'/grants',definition:'/definitions',review:'/case-reviews'}[kind(type)],{grant:'GrantCreate',definition:'DefinitionCreate',review:'CaseReviewCreate'}[type],value);
export const reviewInfectionRegistry=(type,value,body)=>write('/registry/'+kind(type)+'/'+id(value)+'/review','GovernReview',body);
export const revokeInfectionRegistry=(type,value,body)=>write('/registry/'+kind(type)+'/'+id(value)+'/revoke','CAS',body);
export const previewInfectionRoots=value=>write('/roots/preview','SnapshotCreate',value);
export const createInfectionSnapshot=value=>write('/snapshots','SnapshotCreate',value);
export const getInfectionSnapshots=({page=1,size=20}={})=>infectionHttp('/snapshots',{params:query(page,size)});
export const getInfectionSnapshotPart=(value,part)=>{if(!['private','public'].includes(part))throw new Error('须明确完整来源读取件');return infectionHttp('/snapshots/'+id(value)+'/parts/'+part);};
export const getInfectionScenarios=({page=1,size=20,snapshotId=null}={})=>infectionHttp('/scenarios',{params:{...query(page,size),...(snapshotId===null?{}:{snapshot_id:id(snapshotId)})}});
export const getInfectionScenario=value=>infectionHttp('/scenarios/'+id(value));
export const createInfectionScenario=value=>write('/scenarios','ScenarioCreate',value);
export const reviewInfectionScenario=(value,body)=>write('/scenarios/'+id(value)+'/review','ScenarioReview',body);
export const revokeInfectionScenario=(value,body)=>write('/scenarios/'+id(value)+'/revoke','CAS',body);
export const getInfectionProfiles=({page=1,size=20}={})=>infectionHttp('/local-profiles',{params:query(page,size)});
export const getInfectionProfile=value=>infectionHttp('/local-profiles/'+id(value));
export const createInfectionProfile=value=>write('/local-profiles','ProfileCreate',value);
export const reviewInfectionProfile=(value,body)=>write('/local-profiles/'+id(value)+'/review','ScenarioReview',body);
export const revokeInfectionProfile=(value,body)=>write('/local-profiles/'+id(value)+'/revoke','CAS',body);
export const getInfectionConfiguration=({management=false}={})=>{if(typeof management!=='boolean')throw new Error('须明确配置读取模式');return infectionHttp('/local-configuration',{params:{management}});};
export const configureInfectionLocal=value=>write('/local-configuration','LocalConfigWrite',value,'put');
export function infectionRegistryDirectoryValid(v,{kind,page=1,size=20}={}){try{return keys(v,['schema_version','kind','items','total','page','size','clinical_parts_available_in_directory'])&&v.schema_version==='infection_registry_directory_v1'&&v.kind===kind&&v.clinical_parts_available_in_directory===false&&v.page===page&&v.size===size&&Number.isSafeInteger(v.total)&&v.total>=0&&Array.isArray(v.items)&&v.items.length===Math.min(size,Math.max(0,v.total-(page-1)*size))&&unique(v.items.map(r=>r.record_id))&&v.items.every(r=>keys(r,['record_id','content_hash','status','revision','recorded_at','create_event_id','review_event_id','revoke_event_id','detail_required'])&&uuid(r.record_id)&&/^[a-f0-9]{64}$/.test(r.content_hash)&&clock(r.recorded_at)&&r.detail_required===true&&['draft','published','rejected','revoked'].includes(r.status)&&Number.isSafeInteger(r.revision)&&r.revision>=1&&Number.isSafeInteger(r.create_event_id)&&r.create_event_id>0&&[r.review_event_id,r.revoke_event_id].every(x=>x===null||Number.isSafeInteger(x)&&x>0));}catch{return false;}}
const snapshotKeys=['schema_version','snapshot_id','captured_at','private_hash','public_hash','witness_hash','detail_required','parts_separately_bounded','denominator','clinical_parts_require_current_patient_purpose','can_execute'];
export function infectionSnapshotMetadataValid(v){return keys(v,snapshotKeys)&&v.schema_version==='infection_snapshot_metadata_v1'&&uuid(v.snapshot_id)&&clock(v.captured_at)&&['private_hash','public_hash','witness_hash'].every(k=>typeof v[k]==='string'&&/^[a-f0-9]{64}$/.test(v[k]))&&v.detail_required===true&&v.parts_separately_bounded===true&&v.denominator==='not_provided'&&v.clinical_parts_require_current_patient_purpose===true&&v.can_execute===false;}
export async function verifyInfectionSnapshotPart(v,{snapshotId=null,part=null,current=()=>true}={}){try{
 if(!current()||!keys(v,['metadata','part','value','proof_basis'])||!infectionSnapshotMetadataValid(v.metadata)||snapshotId!==null&&snapshotId!==v.metadata.snapshot_id||part!==null&&part!==v.part||v.proof_basis!=='server_current_sql_and_exact_hashes_private_key_not_disclosed')return false;
 if(v.part==='private')return await verifyPrivateCollection(v.value,{current})&&current()&&v.value.collection_id===v.metadata.snapshot_id&&v.value.captured_at===v.metadata.captured_at&&await digest(v.value)===v.metadata.private_hash&&current();
 return v.part==='public'&&await verifyPublicSource(v.value,{current})&&current()&&v.value.captured_at===v.metadata.captured_at&&v.value.private_collection_hash===v.metadata.private_hash&&await digest(v.value)===v.metadata.public_hash&&current();
}catch{return false;}}
export function infectionCas(record,basisNote){if(!basis(basisNote)||!object(record)||!object(record.governance))throw new Error('须重新核对完整原件和本次明确依据');return{expected_revision:record.governance.revision,expected_content_hash:record.content_hash,expected_governance_hash:record.governance_hash,basis_note:basisNote};}
