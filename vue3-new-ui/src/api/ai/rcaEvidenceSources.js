import request from '@/utils/request';
import {rcaSchema,rcaBound,rcaReply,parseRcaJson,rcaBasis,rcaPositive,rcaId,rcaKeys,rcaSame,rcaClock,rcaOriginalRequestValid,verifyRcaGrant,verifyRcaOriginal,verifyRcaCase} from './rcaEvidenceProofs';
export * from './rcaEvidenceProofs';
const base='ai/admin/rca-evidence',id=v=>{if(!rcaId(v))throw new Error('需要规范RCA原件UUID');return v;},event=v=>{if(!rcaPositive(v))throw new Error('需要明确实际事件PK');return v;};
const read=async(url,params={})=>rcaReply(await request({url,params,method:'get',responseType:'arraybuffer',retry:0}));
const write=async(url,data,model)=>{if(!rcaRequestValid(model,data))throw new Error('请明确填写实际RCA范围、逐字原件与本次审核依据');return rcaReply(await request({url,data:JSON.stringify(data),method:'post',responseType:'arraybuffer',headers:{'Content-Type':'application/json'},retry:0}));};
export const rcaCAS=row=>({expected_revision:row.governance.revision,expected_content_hash:row.content_hash,expected_governance_hash:row.governance_hash});
export function rcaRequestValid(model,value){try{
 if(!['GrantCreate','OriginalCreate','CaseCreate','SourceReview','Revoke'].includes(model)||!rcaSchema(model,value)||!rcaBound(value))return false;
 if(model==='OriginalCreate')return rcaOriginalRequestValid(value);
 if(!rcaBasis(value.basis_note))return false;
 if(model==='GrantCreate')return rcaClock(value.valid_until)&&(value.permission_kind!=='associated_patient_processing'||value.expected_event_patient_id!==null);
 if(model==='SourceReview')return (value.decision==='publish')===['privacy_review','faithfulness_review','provenance_review'].every(k=>value[k]==='confirmed');
 return true;
}catch{return false;}}
export const getRcaOptions=()=>read(base+'/options');
export async function getRcaSuperUsers(page=1){
 if(!Number.isSafeInteger(page)||page<1||page>4096)throw new Error('需要完整用户目录分页');
 const raw=await request({url:'user/getList',params:{role:'super_admin',page,page_size:100},method:'get',responseType:'arraybuffer',retry:0});
 if(!(raw instanceof ArrayBuffer)||raw.byteLength>8388608)throw new Error('完整实际用户目录超过字节预算');
 const value=parseRcaJson(new TextDecoder('utf-8',{fatal:true,ignoreBOM:true}).decode(new Uint8Array(raw)));
 if(!rcaKeys(value,['code','msg','data','total'])||value.code!==200||value.msg!=='success'||!Array.isArray(value.data)||!Number.isSafeInteger(value.total)||value.total<0||value.total>4096||value.data.length!==Math.max(0,Math.min(100,value.total-(page-1)*100)))throw new Error('完整实际用户目录无法核对');
 let last=0;for(const user of value.data){if(!rcaKeys(user,['user_id','username','user_role'])||!rcaPositive(user.user_id)||user.user_id<=last||typeof user.username!=='string'||!user.username||Array.from(user.username).length>100||user.user_role!=='super_admin')throw new Error('实际用户身份目录不完整');last=user.user_id;}
 return value;
}
export const getRcaCapture=eventId=>read(`${base}/events/${event(eventId)}/capture`);
export const getRcaDirectory=(eventId,kind,{page=1,pageSize=20}={})=>{if(!['grants','originals','cases'].includes(kind)||!Number.isSafeInteger(page)||page<1||page>4096||!Number.isSafeInteger(pageSize)||pageSize<1||pageSize>100)throw new Error('需要明确RCA目录和完整分页');return read(`${base}/events/${event(eventId)}/directory/${kind}`,{page,page_size:pageSize});};
export const getRcaLegacyWitness=(eventId,kind,recordId)=>{if(!['legacy_event','legacy_rca'].includes(kind))throw new Error('需要明确实际旧原件类型');return read(`${base}/events/${event(eventId)}/legacy-witness`,{kind,record_id:event(recordId)});};
export const createRcaGrant=data=>write(base+'/grants',data,'GrantCreate');
export const getRcaGrant=value=>read(`${base}/grants/${id(value)}`);
export const revokeRcaGrant=(value,data)=>write(`${base}/grants/${id(value)}/revoke`,data,'Revoke');
export const createRcaOriginal=data=>write(base+'/originals',data,'OriginalCreate');
export const getRcaOriginal=value=>read(`${base}/originals/${id(value)}`);
export const reviewRcaOriginal=(value,data)=>write(`${base}/originals/${id(value)}/review`,data,'SourceReview');
export const revokeRcaOriginal=(value,data)=>write(`${base}/originals/${id(value)}/revoke`,data,'Revoke');
export const createRcaCase=data=>write(base+'/cases',data,'CaseCreate');
export const getRcaCase=value=>read(`${base}/cases/${id(value)}`);
export const getRcaPublicSource=value=>read(`${base}/cases/${id(value)}/public-source`);
export const reviewRcaCase=(value,data)=>write(`${base}/cases/${id(value)}/review`,data,'SourceReview');
export const revokeRcaCase=(value,data)=>write(`${base}/cases/${id(value)}/revoke`,data,'Revoke');
export function rcaOptionsValid(v){return rcaKeys(v,['schema_version','purpose','requires_event_purpose','requires_patient_purpose_if_associated','original_max_utf8_bytes','whole_response_max_utf8_bytes','combined_dependency_cap','span_coordinate_space','normalization','automatic_model_calls','automatic_clinical_writes','causal_verification'])&&rcaSame(v,{schema_version:'rca_evidence_options_v1',purpose:'incident_rca',requires_event_purpose:true,requires_patient_purpose_if_associated:true,original_max_utf8_bytes:4194304,whole_response_max_utf8_bytes:8388608,combined_dependency_cap:4096,span_coordinate_space:'unicode_codepoint_half_open',normalization:'none',automatic_model_calls:false,automatic_clinical_writes:false,causal_verification:'not_provided'});}
export function rcaDirectoryValid(v,{eventId,kind,page=1,pageSize=20}){try{
 if(!rcaSchema('Directory',v)||!rcaBound(v)||v.event_id!==eventId||v.kind!==kind||v.page!==page||v.page_size!==pageSize||v.items.length!==Math.max(0,Math.min(pageSize,v.total-(page-1)*pageSize)))return false;
 const field={originals:'original_id',cases:'case_id',grants:'grant_id'}[kind],schema={originals:'OriginalMetadata',cases:'CaseMetadata',grants:'GrantMetadata'}[kind];let last=null;
 return !!field&&v.items.every(row=>{const identifier=row[field];if(!rcaSchema(schema,row)||row.event_id!==eventId||last!==null&&identifier<=last||!['draft','active','published','rejected','revoked'].includes(row.status)||!rcaClock(kind==='grants'?row.issued_at:row.recorded_at)||kind==='grants'&&!rcaClock(row.valid_until)||(row.status==='draft'||row.status==='active'?row.revision!==1:row.status==='revoked'?![2,3].includes(row.revision):row.revision!==2))return false;last=identifier;return true;});
}catch{return false;}}
export function rcaMetadataMatches(row,meta,kind){try{
 if(!meta)return true;const s=kind==='grants'?row.identity:row.immutable,field={originals:'original_id',cases:'case_id',grants:'grant_id'}[kind];
 return s[field]===meta[field]&&s.event_id===meta.event_id&&row.content_hash===meta.content_hash&&row.governance.status===meta.status&&row.governance.revision===meta.revision&&(kind==='grants'?s.issued_at===meta.issued_at&&s.valid_until===meta.valid_until&&s.grantee_id===meta.grantee_id&&s.permission_kind===meta.permission_kind:s.recorded_at===meta.recorded_at&&s.created_by===meta.created_by&&(kind==='originals'?s.origin_kind===meta.origin_kind:s.capture.collection_hash===meta.collection_hash));
}catch{return false;}}
const recordVerifier={grants:verifyRcaGrant,originals:verifyRcaOriginal,cases:verifyRcaCase};
export async function verifyRcaCreated(after,body,kind,{current=()=>true}={}){try{
 const model={grants:'GrantCreate',originals:'OriginalCreate',cases:'CaseCreate'}[kind],verify=recordVerifier[kind];
 if(!model||!rcaRequestValid(model,body)||!await verify(after,{current}))return false;
 const s=kind==='grants'?after.identity:after.immutable;
 if(s.event_id!==body.event_id||(kind==='grants'?s.patient_id_at_grant:s.patient_id_at_capture)!==body.expected_event_patient_id||after.governance.revision!==1)return false;
 if(kind==='grants')return after.governance.status==='active'&&after.current_scope&&['grantee_id','permission_kind','purpose','valid_until','basis_note','explicit_scope_review'].every(k=>rcaSame(s[k],body[k]));
 if(after.governance.status!=='draft')return false;
 if(kind==='cases')return after.current_collection_matches&&s.capture.collection_hash===body.expected_collection_hash&&s.basis_note===body.basis_note;
 return after.current_raw_witness_matches&&['origin_kind','text','provenance','timeline'].every(k=>rcaSame(s[k],body[k]));
}catch{return false;}}
export async function verifyRcaTransition(after,before,body,kind,action,{current=()=>true}={}){try{
 const verify=recordVerifier[kind],model=action==='review'?'SourceReview':'Revoke';
 if(!verify||!rcaRequestValid(model,body)||!rcaSame(rcaCAS(before),Object.fromEntries(Object.keys(rcaCAS(before)).map(k=>[k,body[k]])))||!await verify(after,{current})||after.content_hash!==before.content_hash||!rcaSame(kind==='grants'?after.identity:after.immutable,kind==='grants'?before.identity:before.immutable)||after.governance.revision!==before.governance.revision+1)return false;
 const a=after.governance,b=before.governance;
 if(action==='review')return kind!=='grants'&&b.status==='draft'&&a.status===(body.decision==='publish'?'published':'rejected')&&a.review_basis_note===body.basis_note&&['privacy_review','faithfulness_review','provenance_review'].every(k=>a[k]===body[k])&&a.created_audit_event_id===b.created_audit_event_id;
 if(action!=='revoke'||b.status==='revoked'||a.status!=='revoked'||a.revoke_reason!==body.basis_note)return false;
 const preserve=Object.keys(b).filter(k=>!['status','revision','revoked_by','revoked_at','revoke_reason','revoked_audit_event_id'].includes(k));
 return preserve.every(k=>rcaSame(a[k],b[k]));
}catch{return false;}}
