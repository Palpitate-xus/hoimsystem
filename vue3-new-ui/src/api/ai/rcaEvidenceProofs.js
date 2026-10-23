// Data integrity only. Current event/patient-purpose authorization is server-side.
import registry from './rcaEvidenceSchemas.json';
import {decodeGeneratedSchemas,generatedSchemaMatches} from '../sofaSchema';
import {supportCanonical,supportDigest,supportId,supportHash} from '../inpatientSupport';
import {documentUtf8,documentBytesHash,documentClock,documentCodepointSlice} from './documentEvidence';
import {parseOriginalJson,scalarJsonValue} from './nativeOriginalJson';

export const RCA_WIRE=8388608,RCA_ORIGINAL=4194304;
const schemas=decodeGeneratedSchemas(registry);
export const rcaSchema=(name,value)=>generatedSchemaMatches(schemas,name,value);
export const rcaSchemaDefinition=name=>schemas[name]||null;
export const rcaSame=(a,b)=>supportCanonical(a)===supportCanonical(b);
export const rcaBytes=value=>documentUtf8(typeof value==='string'?value:supportCanonical(value)).length;
export const rcaHash=documentBytesHash,rcaDigest=supportDigest,rcaId=supportId,rcaSha=supportHash,rcaClock=documentClock;
export const rcaPositive=value=>Number.isSafeInteger(value)&&value>=1&&value<=2147483647;
export const rcaKeys=(v,names)=>v!==null&&typeof v==='object'&&!Array.isArray(v)&&Object.keys(v).sort().join(',')===[...names].sort().join(',');
export const rcaPlain=(value,maxBytes)=>{try{return typeof value==='string'&&value.replace(/[\u0009-\u000d\u001c-\u0020\u0085\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000]/gu,'').length>0&&rcaBytes(value)<=maxBytes;}catch{return false;}};
export const rcaBasis=value=>rcaPlain(value,4000)&&Array.from(value).length<=1000;
export function rcaBound(value){try{return scalarJsonValue(value)&&rcaBytes(value)<=RCA_WIRE;}catch{return false;}}
export function parseRcaJson(raw){
 if(typeof raw!=='string'||!raw.length||rcaBytes(raw)>RCA_WIRE)throw new Error('完整RCA响应超过8MiB或UTF8无效');
 let depth=0,tokens=0,quoted=false,escaped=false,atom=false;
 for(const char of raw){if(quoted){if(escaped)escaped=false;else if(char==='\\')escaped=true;else if(char==='"')quoted=false;continue;}if(char==='"'){quoted=true;tokens++;}else if(char==='['||char==='{'){depth++;tokens++;}else if(char===']'||char==='}'){depth--;atom=false;}else if(char===','||char===':'||/\s/u.test(char))atom=false;else if(!atom){atom=true;tokens++;}if(depth>32||tokens>200000)throw new Error('完整RCA JSON结构预算超限');}
 return parseOriginalJson(raw,RCA_WIRE);
}
export function rcaReply(value){
 if(value instanceof ArrayBuffer&&value.byteLength>RCA_WIRE)throw new Error('完整RCA响应超过8MiB，未解码或裁剪');
 const raw=value instanceof ArrayBuffer?new TextDecoder('utf-8',{fatal:true,ignoreBOM:true}).decode(new Uint8Array(value)):value;
 if(typeof raw!=='string')throw new Error('需要保留原HTTP UTF8字节的RCA响应');
 const result=parseRcaJson(raw);if(!rcaKeys(result,['code','msg','data'])||result.code!==200||result.msg!=='success')throw new Error('RCA完整响应合同无效');return result;
}
const checked=(name,v)=>rcaSchema(name,v)&&rcaBound(v);
function date(value){try{return /^\d{4}-\d{2}-\d{2}$/u.test(value)&&new Date(value+'T00:00:00Z').toISOString().slice(0,10)===value;}catch{return false;}}
function legacy(value){try{return value===null||value.basis==='stored_naive_no_timezone'&&/^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d{1,6})?$/u.test(value.text)&&documentClock(value.text.split('.')[0]+'.'+(value.text.split('.')[1]||'').padEnd(6,'0')+'Z');}catch{return false;}}
export function rcaRawValid(kind,value){if(!checked(kind==='legacy_event'?'EventSnapshot':'RcaSnapshot',value))return false;return kind==='legacy_event'?legacy(value.report_time):legacy(value.create_time)&&legacy(value.update_time)&&[value.due_date,value.completed_date].every(v=>v===null||date(v));}
export function rcaOccurrence(v){return checked(v?.status==='unknown'?'OccurrenceUnknown':v?.status==='human_declared_exact'?'OccurrenceExact':'OccurrenceInterval',v)&&(v.status==='unknown'||v.status==='human_declared_exact'&&rcaClock(v.at)||v.status==='human_declared_interval'&&rcaClock(v.start_at)&&rcaClock(v.end_at)&&v.start_at<v.end_at);}
const quote=(v,text)=>v.start<v.end&&Array.from(v.quote).length===v.end-v.start&&rcaBytes(v.quote)<=65535&&documentCodepointSlice(text,v.start,v.end)===v.quote&&v.end<=Array.from(text).length;
export const rcaQuoteValid=quote;
export function rcaGovernance(g,recorded){
 if(!checked('SourceGovernance',g)||!rcaClock(recorded))return false;
 const review=[g.reviewed_by,g.reviewed_at,g.reviewed_audit_event_id],rev=[g.revoked_by,g.revoked_at,g.revoked_audit_event_id],hasReview=review.every(v=>v!==null)&&rcaBasis(g.review_basis_note),noReview=review.every(v=>v===null)&&g.review_basis_note===''&&['privacy_review','faithfulness_review','provenance_review'].every(k=>g[k]==='unknown'),noRev=rev.every(v=>v===null)&&g.revoke_reason==='';
 if(hasReview&&(!rcaClock(g.reviewed_at)||g.reviewed_at<recorded)||!noRev&&(!rev.every(v=>v!==null)||!rcaClock(g.revoked_at)||g.revoked_at<(g.reviewed_at||recorded)||!rcaBasis(g.revoke_reason)))return false;
 const ids=[g.created_audit_event_id,g.reviewed_audit_event_id,g.revoked_audit_event_id].filter(v=>v!==null);if(new Set(ids).size!==ids.length)return false;
 const confirmed=['privacy_review','faithfulness_review','provenance_review'].every(k=>g[k]==='confirmed');
 if(g.status==='draft')return g.revision===1&&noReview&&noRev;
 if(g.status==='revoked')return !noRev&&(g.revision===(noReview?2:3))&&(noReview||hasReview);
 return g.revision===2&&hasReview&&noRev&&(g.status==='published'?confirmed:g.status==='rejected'&&!confirmed);
}
export async function verifyRcaGrant(v,{current=()=>true}={}){try{
 if(!current()||!checked('GrantRecord',v))return false;
 const s=v.identity,g=v.governance;
 if(!rcaClock(s.issued_at)||!rcaClock(s.valid_until)||s.valid_until<=s.issued_at||!rcaBasis(s.basis_note)||s.permission_kind==='associated_patient_processing'&&s.patient_id_at_grant===null||!rcaClock(v.evaluated_at))return false;
 if(await rcaDigest(s)!==v.content_hash||await rcaDigest({grant_id:s.grant_id,content_hash:v.content_hash,governance:g})!==v.governance_hash)return false;
 if(g.status==='active'?g.revision!==1||g.revoked_by!==null||g.revoked_at!==null||g.revoked_audit_event_id!==null||g.revoke_reason!=='':g.revision!==2||g.revoked_by===null||g.revoked_audit_event_id===null||g.revoked_audit_event_id===g.created_audit_event_id||!rcaClock(g.revoked_at)||g.revoked_at<s.issued_at||!rcaBasis(g.revoke_reason))return false;
 const reasons=[...(s.valid_until<=v.evaluated_at?['grant_expired']:[]),...(g.status==='revoked'?['grant_revoked']:[]),...(s.patient_id_at_grant!==v.event_patient_id_now?['event_patient_changed']:[]),...(!v.grantee_current_super?['grantee_not_current_super']:[])];
 return current()&&rcaSame(v.scope_reasons,reasons)&&v.current_scope===!reasons.length;
}catch{return false;}}
export function rcaOriginalRequestValid(v){try{
 if(!checked('OriginalCreate',v)||rcaBytes(v.text)>RCA_ORIGINAL||!rcaBasis(v.provenance.provenance_note))return false;
 const p=v.provenance;
 if(p.method==='human_declared_derivative'?v.origin_kind!==p.witness_kind:!['manual_evidence','human_timeline'].includes(v.origin_kind))return false;
 if((v.origin_kind==='human_timeline')!==!!v.timeline.length||new Set(v.timeline.map(t=>t.entry_id)).size!==v.timeline.length||v.timeline.length+v.timeline.reduce((n,t)=>n+t.evidence.length,0)>4096)return false;
 return v.timeline.every(t=>rcaOccurrence(t.occurred_time)&&rcaPlain(t.statement,16000)&&v.text.includes(t.statement)&&t.evidence.every(q=>quote(q,v.text)));
}catch{return false;}}
export async function verifyRcaOriginal(v,{current=()=>true}={}){try{
 if(!current()||!checked('OriginalRecord',v))return false;const s=v.immutable,g=v.governance,p=s.provenance;
 if(!rcaClock(s.recorded_at)||!rcaClock(v.evaluated_at)||v.evaluated_at<s.recorded_at||!rcaGovernance(g,s.recorded_at)||!rcaOriginalRequestValid({event_id:s.event_id,expected_event_patient_id:s.patient_id_at_capture,origin_kind:s.origin_kind,text:s.text,provenance:p,timeline:s.timeline})||(s.patient_id_at_capture===null)!==(s.patient_grant_id===null)||s.event_grant_id===s.patient_grant_id)return false;
 if(await rcaHash(s.text)!==s.text_hash||await rcaDigest(s)!==v.content_hash||await rcaDigest({original_id:s.original_id,content_hash:v.content_hash,governance:g})!==v.governance_hash)return false;
 if(p.method==='human_authored_record'){if(s.raw_witness!==null)return false;}else{const w=s.raw_witness;if(!rcaRawValid(p.witness_kind,w)||w.event_id!==s.event_id||(p.witness_kind==='legacy_event'?w.event_id:w.rca_id)!==p.witness_id||p.witness_kind==='legacy_event'&&w.patient_id!==s.patient_id_at_capture||await rcaDigest(w)!==p.expected_raw_hash)return false;}
 return current()&&v.eligible===(g.status==='published'&&v.current_raw_witness_matches);
}catch{return false;}}
export function rcaStableOriginal(item){if(item.visibility==='association_changed_not_disclosed')return item;const v=item.record;return {original_id:v.immutable.original_id,event_id:v.immutable.event_id,patient_id_at_capture:v.immutable.patient_id_at_capture,content_hash:v.content_hash,governance_hash:v.governance_hash,current_raw_witness_matches:v.current_raw_witness_matches,visibility:item.visibility};}
const sortedUnique=values=>new Set(values).size===values.length&&rcaSame(values,[...values].sort((a,b)=>typeof a==='number'?a-b:a<b?-1:a>b?1:0));
export async function verifyRcaCapture(v,{current=()=>true}={}){try{
 if(!current()||!checked('Capture',v)||!rcaRawValid('legacy_event',v.event)||1+v.rcas.length+v.originals.length>4096||!sortedUnique(v.rcas.map(x=>x.rca_id))||!sortedUnique(v.originals.map(x=>rcaStableOriginal(x).original_id)))return false;
 for(const row of v.rcas)if(row.event_id!==v.event.event_id||!rcaRawValid('legacy_rca',row))return false;
 for(const item of v.originals){const s=rcaStableOriginal(item);if(s.event_id!==v.event.event_id)return false;if(item.visibility==='current_patient_purpose_authorized'&&(s.patient_id_at_capture!==v.event.patient_id||!await verifyRcaOriginal(item.record,{current})))return false;}
 return current()&&await rcaDigest({event:v.event,rcas:v.rcas,originals:v.originals.map(rcaStableOriginal)})===v.collection_hash;
}catch{return false;}}
export async function verifyRcaCase(v,{current=()=>true,frozen=false}={}){try{
 if(!current()||!checked(frozen?'RcaFrozenCase':'CaseRecord',v))return false;const s=v.immutable,g=v.governance;
 if(!rcaClock(s.recorded_at)||!rcaBasis(s.basis_note)||!rcaGovernance(g,s.recorded_at)||s.event_id!==s.capture.event.event_id||s.patient_id_at_capture!==s.capture.event.patient_id||(s.patient_id_at_capture===null)!==(s.patient_grant===null)||!await verifyRcaCapture(s.capture,{current}))return false;
 for(const [grant,kind] of [[s.event_grant,'event_investigation'],[s.patient_grant,'associated_patient_processing']]){
  if(grant===null)continue;const x=grant.identity;
  if(!await verifyRcaGrant(grant,{current})||!grant.current_scope||x.event_id!==s.event_id||x.patient_id_at_grant!==s.patient_id_at_capture||x.grantee_id!==s.created_by||x.permission_kind!==kind||x.issued_at>s.recorded_at||x.valid_until<=s.recorded_at)return false;
 }
 if(s.patient_grant!==null&&s.patient_grant.identity.grant_id===s.event_grant.identity.grant_id)return false;
 for(const member of s.capture.originals)if(member.visibility==='current_patient_purpose_authorized'&&member.record.immutable.recorded_at>s.recorded_at)return false;
 if(await rcaDigest(s)!==v.content_hash||await rcaDigest({case_id:s.case_id,content_hash:v.content_hash,governance:g})!==v.governance_hash)return false;
 if(frozen)return current()&&g.status==='published'&&g.revision===2;
 return current()&&rcaClock(v.evaluated_at)&&v.evaluated_at>=s.recorded_at&&v.current_collection_matches===(v.current_collection_hash===s.capture.collection_hash)&&v.eligible===(g.status==='published'&&v.current_collection_matches);
}catch{return false;}}
export async function rcaOpaque(secret,namespace,value,uuid=true){
 if(!rcaSha(secret))throw new Error('需要已授权Case的私有映射原件');
 const key=await crypto.subtle.importKey('raw',Uint8Array.from(secret.match(/../g),v=>parseInt(v,16)),{name:'HMAC',hash:'SHA-256'},false,['sign']);
 const b=await crypto.subtle.sign('HMAC',key,documentUtf8(supportCanonical([namespace,value]))),hex=Array.from(new Uint8Array(b),n=>n.toString(16).padStart(2,'0')).join('');
 return uuid?`${hex.slice(0,8)}-${hex.slice(8,12)}-${hex.slice(12,16)}-${hex.slice(16,20)}-${hex.slice(20,32)}`:hex;
}
export async function projectRcaCase(record,{current=()=>true,frozen=false}={}){
 if(!await verifyRcaCase(record,{current,frozen})||!frozen&&!record.eligible)throw new Error('完整Case与实际发布链无法核对');
 const b=record.immutable,event=b.capture.event,members=[],items=[],timeline=[],token=(ns,id,uuid=true)=>rcaOpaque(b.identity_secret,ns,id,uuid);
 members.push({member_id:await token('legacy_event',event.event_id),kind:'legacy_event',content_hash:await rcaDigest(event),governance_hash:null,release_status:'not_released'});
 for(const raw of b.capture.rcas)members.push({member_id:await token('legacy_rca',raw.rca_id),kind:'legacy_rca',content_hash:await rcaDigest(raw),governance_hash:null,release_status:'not_released'});
 for(const member of b.capture.originals){const restricted=member.visibility==='association_changed_not_disclosed',raw=restricted?member:member.record,s=restricted?member:raw.immutable,itemId=await token('original',s.original_id),kind=s.origin_kind==='human_timeline'?'human_timeline':'manual_evidence',released=!restricted&&raw.eligible;
  members.push({member_id:itemId,kind,content_hash:raw.content_hash,governance_hash:restricted?null:raw.governance_hash,release_status:released?'released':'not_released'});
  if(!released)continue;
  items.push({item_id:itemId,kind,content_hash:raw.content_hash,governance_hash:raw.governance_hash,text:s.text,text_hash:s.text_hash,available_at:s.recorded_at,availability_basis:'original_registration'});
  for(const t of s.timeline)timeline.push({entry_id:await token('timeline',[s.original_id,t.entry_id]),source_item_id:itemId,statement:t.statement,occurred_time:{...t.occurred_time,basis_hash:await token('timeline_basis',t.occurred_time.basis_hash,false)},recorded_at:s.recorded_at,evidence:t.evidence.map(q=>({item_id:itemId,...q})),assertion_status:t.assertion_status});
 }
 members.sort((a,b)=>a.member_id.localeCompare(b.member_id));items.sort((a,b)=>a.item_id.localeCompare(b.item_id));timeline.sort((a,b)=>a.entry_id.localeCompare(b.entry_id));
 const value={schema_version:'rca_evidence_source_v1',case_id:b.case_id,source_id:`rca_case:${b.case_id}:${record.content_hash.slice(0,12)}`,content_hash:record.content_hash,governance_hash:record.governance_hash,snapshot_time:record.governance.reviewed_at,review_mode:'current_retrospective_investigation_not_historical_prediction',event_state:{recorded_severity:event.severity,recorded_status:event.status,report_time:event.report_time,patient_association:event.patient_id===null?'not_recorded':'recorded_patient',encounter_assignment:'not_recorded',causal_approval:'not_provided'},publication:{status:'published',privacy_review:'confirmed',faithfulness_review:'confirmed',provenance_review:'confirmed',reviewed_at:record.governance.reviewed_at},members,member_manifest_hash:await rcaDigest(members),items,timeline,evidence_coverage:'finite_declared_snapshot_not_complete_causality_or_hospital_coverage'};
 if(!await verifyRcaPublic(value,{current}))throw new Error('完整公开Source超限或依赖不闭合');return value;
}
export async function verifyRcaPublic(v,{current=()=>true}={}){try{
 if(!current()||!checked('RcaEvidenceSource',v)||!rcaClock(v.snapshot_time)||!rcaClock(v.publication.reviewed_at)||v.publication.reviewed_at>v.snapshot_time||v.source_id!==`rca_case:${v.case_id}:${v.content_hash.slice(0,12)}`||!legacy(v.event_state.report_time))return false;
 if(v.members.length+v.items.length+v.timeline.length+v.timeline.reduce((n,t)=>n+t.evidence.length,0)>4096||v.members.filter(m=>m.kind==='legacy_event').length!==1||!sortedUnique(v.members.map(m=>m.member_id))||!sortedUnique(v.items.map(m=>m.item_id))||!sortedUnique(v.timeline.map(m=>m.entry_id))||await rcaDigest(v.members)!==v.member_manifest_hash)return false;
 const members=new Map(v.members.map(m=>[m.member_id,m])),items=new Map(v.items.map(m=>[m.item_id,m]));
 if(!rcaSame(v.members.filter(m=>m.release_status==='released').map(m=>m.member_id).sort(),v.items.map(m=>m.item_id)))return false;
 for(const item of v.items){const m=members.get(item.item_id);if(!m||m.release_status!=='released'||m.kind!==item.kind||m.content_hash!==item.content_hash||m.governance_hash!==item.governance_hash||rcaBytes(item.text)>RCA_ORIGINAL||await rcaHash(item.text)!==item.text_hash||!rcaClock(item.available_at)||item.available_at>v.snapshot_time)return false;}
 for(const t of v.timeline){const item=items.get(t.source_item_id);if(!item||item.kind!=='human_timeline'||!item.text.includes(t.statement)||!rcaPlain(t.statement,16000)||!rcaOccurrence(t.occurred_time)||!rcaClock(t.recorded_at)||t.recorded_at>v.snapshot_time||!t.evidence.every(q=>items.has(q.item_id)&&quote(q,items.get(q.item_id).text)))return false;}
 return current();
}catch{return false;}}
