import {supportCanonical as canonical,supportDigest as digest,supportHash as hash,supportId as uuid} from '@/api/inpatientSupport';
import {decodeGeneratedSchemas,generatedSchemaMatches} from '@/api/sofaSchema';
import {chargeCaseReferencesValid,chargeScopeValid,chargeProjectionPolicy,chargePublishedMetadata,verifyChargeReconciliationFrozenCase} from './chargeReconciliationSources';
import {parseOriginalJson,scalarJsonValue} from './nativeOriginalJson';
import packed from './chargeReconciliationResultSchemas.json';
import fixed from './chargeReconciliationUiFixed.json';

const schemas=decodeGeneratedSchemas(packed),encoder=new TextEncoder(),groups=['charges','orders','order_items','executions','administrations'];
const object=v=>v!==null&&typeof v==='object'&&!Array.isArray(v),same=(a,b)=>canonical(a)===canonical(b);
const pick=(v,names)=>Object.fromEntries(names.map(name=>[name,v[name]]));
const keys=(v,names)=>object(v)&&same(Object.keys(v).sort(),[...names].sort());
const positive=v=>Number.isSafeInteger(v)&&v>0&&v<=2147483647,nonnegative=v=>Number.isSafeInteger(v)&&v>=0;
const bytes=v=>encoder.encode(typeof v==='string'?v:canonical(v)).length;
const valid=(name,v)=>scalarJsonValue(v)&&generatedSchemaMatches(schemas,name,v);
const current=options=>!options.current||options.current()===true;
// A surviving native identity is a dispatch requirement, never proof of validity.
// Own-key checks intentionally retain damaged/null native markers for strict rejection.
export function chargeRunHasNativeMarkers(value){
 if(!object(value))return false;
 if(['charge_artifact','charge_findings','charge_case_id'].some(name=>Object.hasOwn(value,name))||Object.hasOwn(value.result||{},'charge_analysis')||Object.hasOwn(value.frozen_request?.payload?.input||{},'charge_case_id'))return true;
 return [value,value.frozen_request?.payload?.context,value.operational_findings].some(context=>object(context)&&(Object.hasOwn(context,'charge_binding')||context.source_domain==='single_admission_recorded_ledger'||object(context.selected_sources)&&Object.hasOwn(context.selected_sources,'charge_case_id')));
}

const metadataNames=['snapshot_time','source_count','department_ids','context_digest','clinical_context_fingerprint','missing_data'];
const extraMetadata=['feature_revision','validation_status','tool_fingerprint','instructions_digest','model_version'];
const shortNames=['scope','source_domain','department_ids','selected_sources','charge_binding','scope_note','missing_data','truncated_sources','snapshot_time'];
const runNames=['run_id','feature_key','status','preview','prompt_version','provider_revision','context_digest','patient_id','encounter_ref','error_code','error_message','latency_ms','create_time','start_time','finish_time','feature_name','requires_human_review','context_metadata','charge_case_id','usage_receipt','input_tokens','output_tokens','usage_receipt_status','charge_artifact','charge_findings','result','evidence'];
const whitespace=new Set(fixed.python_whitespace_codepoints);
const meaningful=v=>{const p=Array.from(v);let start=0,end=p.length;while(start<end&&whitespace.has(p[start].codePointAt(0)))start++;while(end>start&&whitespace.has(p[end-1].codePointAt(0)))end--;return end-start>=4&&bytes(v)<=8000;};
function utc(v){try{return typeof v==='string'&&/^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{6}Z$/.test(v)&&!v.startsWith('0000-')&&new Date(v.slice(0,23)+'Z').toISOString()===v.slice(0,23)+'Z';}catch{return false;}}
function legacyClock(v,space=false){if(typeof v!=='string'||!new RegExp('^\\d{4}-\\d\\d-\\d\\d'+(space?'[T ]':'T')+'\\d\\d:\\d\\d:\\d\\d(?:\\.\\d{6})?$').test(v))return false;const normalized=v.replace(' ','T');return utc(normalized+(normalized.includes('.')?'':'.000000')+'Z');}
async function textHash(v){return Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',encoder.encode(v))),b=>b.toString(16).padStart(2,'0')).join('');}
function expectedScope(caseProof,expected,options,task){
 const suppliedScope=expected.patientId!==null&&expected.patientId!==undefined||expected.admissionId!==null&&expected.admissionId!==undefined;
 if(suppliedScope&&(!chargeScopeValid({patient_id:expected.patientId,admission_id:expected.admissionId})||caseProof.patient_id!==expected.patientId||caseProof.admission_id!==expected.admissionId))return false;
 const refs=expected.references,hasReferences=refs!==null&&refs!==undefined;
 if(hasReferences&&(!chargeCaseReferencesValid(refs)||refs.charge_case_id!==caseProof.case_snapshot_id))return false;
 return suppliedScope&&hasReferences||task&&options.allowFrozenAudit===true&&uuid(expected.runId);
}
function inputValid(value,caseId){return object(value)&&Object.hasOwn(value,'charge_case_id')&&Object.keys(value).every(k=>['charge_case_id','question'].includes(k))&&value.charge_case_id===caseId&&(!Object.hasOwn(value,'question')||value.question===null||typeof value.question==='string'&&Array.from(value.question).length<=2000&&bytes(value.question)<=8000);}
async function bindingForCase(value){
 const collection=value.snapshot.collection,published=await chargePublishedMetadata(value);
 return{schema_version:'charge_context_binding_v1',case_snapshot_id:value.case_snapshot_id,patient_id:value.patient_id,admission_id:value.admission_id,source_id:value.source_id,content_hash:value.content_hash,collection_digest:value.collection_digest,publication_governance_hash:published.governance_hash,projection_hash:value.projection_hash,manifest_hash:collection.manifest_hash,policy_hash:await digest(chargeProjectionPolicy),captured_at:collection.captured_at,float_capture_basis:collection.float_capture_basis,department_ids:collection.admission.department_id===null?[]:[collection.admission.department_id]};
}
async function verifyPacket(packet,expected,options,task){
 const required=task?['charge_binding','charge_source','charge_case','input','context']:[...shortNames,'charge_source','charge_case'];
 if(!keys(packet,required)||!scalarJsonValue(packet)||bytes(packet)>16777216)return null;
 const c=packet.charge_case,b=packet.charge_binding,short=task?packet.context:pick(packet,shortNames);
 if(!object(c)||!expectedScope(c,expected,options,task))return null;
 if(task){
  if(!await verifyChargeReconciliationFrozenCase(c,{patientId:c.patient_id,admissionId:c.admission_id})||!current(options))return null;
  if(c.audit_only===true){if(options.allowFrozenAudit!==true||c.eligible!==false)return null;}
  else if(c.audit_only!==false||c.scope_current!==true||c.eligible!==true)return null;
  if(!inputValid(packet.input,c.case_snapshot_id)||Object.hasOwn(expected,'input')&&!same(expected.input,packet.input))return null;
 }else if(!await verifyChargeReconciliationFrozenCase(c,{patientId:c.patient_id,admissionId:c.admission_id})||c.eligible!==true||c.scope_current!==true||c.audit_only!==false||!current(options))return null;
 if(!valid('ChargeContextBinding',b)||!same(b,await bindingForCase(c))||!current(options)||!same(packet.charge_source,c.public_source)||await digest(packet.charge_source)!==b.projection_hash)return null;
 if(!keys(short,shortNames)||!utc(short.snapshot_time)||short.snapshot_time<b.captured_at)return null;
 const expectedShort={scope:'patient',source_domain:'single_admission_recorded_ledger',department_ids:b.department_ids,selected_sources:{charge_case_id:b.case_snapshot_id},charge_binding:b,scope_note:fixed.scope_note,missing_data:fixed.context_missing,truncated_sources:[],snapshot_time:short.snapshot_time};
 if(!same(short,expectedShort))return null;
 const {snapshot_time,...fingerprint}=short;
 const metadata={snapshot_time,source_count:1,department_ids:b.department_ids,context_digest:await digest(short),clinical_context_fingerprint:await digest(fingerprint),missing_data:fixed.context_missing};
 const evidence=[{source_id:b.source_id,kind:fixed.evidence_kind,title:fixed.evidence_title,content:canonical({charge_binding:b})}];
 return current(options)?{binding:b,source:packet.charge_source,caseProof:c,short,metadata,evidence}:null;
}
export async function verifyChargeContext(value,expected={},options={}){try{
 if(!current(options)||!keys(value,['context','metadata','evidence']))return false;
 const checked=await verifyPacket(value.context,expected,options,false);
 return !!checked&&same(value.metadata,checked.metadata)&&same(value.evidence,checked.evidence)&&current(options);
}catch{return false;}}
function members(source){const result=new Map();for(const group of groups)for(const row of source[group]){if(result.has(row.source_id))throw new Error('Duplicate member');result.set(row.source_id,row);}if(result.size>8192)throw new Error('Oversized membership');return result;}
function draftValid(draft,source,projectionHash){
 if(!valid('ChargeReconciliationDraft',draft)||draft.source_id!==source.source_id||draft.source_projection_hash!==projectionHash||bytes(draft)>8388608)return false;
 const rows=members(source),identities=new Set();
 for(const observation of draft.observations){
  const refs=observation.referenced_source_ids,identity=canonical([observation.kind,[...refs].sort()]);
  if(new Set(refs).size!==refs.length||refs.some(id=>!rows.has(id))||identities.has(identity)||!meaningful(observation.review_note)||!meaningful(observation.clarification_question)||observation.kind!=='insufficient_evidence'&&!observation.citations.length)return false;
  identities.add(identity);const citations=new Set();
  for(const quote of observation.citations){
   const key=canonical([quote.source_id,quote.field,quote.start,quote.end]);
   if(!refs.includes(quote.source_id)||citations.has(key)||quote.end<=quote.start||bytes(quote.quote)>16000)return false;
   let text=rows.get(quote.source_id);for(const field of quote.field.split('.')){if(!object(text)||!Object.hasOwn(text,field))return false;text=text[field];}
   if(typeof text!=='string')return false;const points=Array.from(text);
   if(quote.end>points.length||points.slice(quote.start,quote.end).join('')!==quote.quote)return false;
   citations.add(key);
  }
 }
 return true;
}
function resultValid(value,source,projectionHash){
 if(!valid('ChargeReconciliationResult',value)||!draftValid(value.charge_analysis,source,projectionHash)||bytes(value)>8388608)return false;
 const counts=Object.fromEntries(groups.map(name=>[name+'_count',source[name].length]));
 counts.observations_count=value.charge_analysis.observations.length;
 for(const [name,state]of [['association_not_recorded','not_recorded'],['association_same_admission','recorded_same_admission'],['association_unresolved','unresolved_or_out_of_scope']])counts[name]=source.charges.filter(row=>row.order_association===state).length;
 const format=text=>text.replace(/\{([a-z_]+)\}/g,(_,name)=>String(counts[name]));
 const expected={summary:format(fixed.result_templates.summary),sections:fixed.result_templates.sections.map(section=>({...section,content:format(section.content),source_ids:[source.source_id]})),warnings:fixed.output_warnings,missing_data:fixed.output_missing,charge_analysis:value.charge_analysis};
 return same(value,expected);
}
function usageValid(run){
 const u=run.usage_receipt,a=run.charge_artifact;
 if(!valid('ChargeUsage',u)||u.complete!==(u.input_tokens!==null&&u.output_tokens!==null)||u.model_call_attempted===false&&(u.input_tokens!==0||u.output_tokens!==0)||u.model_call_attempted===null&&(u.input_tokens!==null||u.output_tokens!==null)||run.input_tokens!==u.input_tokens||run.output_tokens!==u.output_tokens)return false;
 const pending=run.status==='queued'||run.status==='running'||run.status==='cancelled'&&run.latency_ms===null;
 if(pending)return run.latency_ms===null&&run.usage_receipt_status==='pending'&&same(u,{input_tokens:null,output_tokens:null,complete:false,model_call_attempted:null})&&a.receipt_event_id===null&&a.accepted_lease===null&&a.result_hash===null&&a.result_bytes===null&&run.result===null;
 return nonnegative(run.latency_ms)&&run.usage_receipt_status==='recorded'&&positive(a.receipt_event_id)&&(u.model_call_attempted!==null||['failed','cancelled'].includes(run.status)&&run.error_code==='WORKER_INTERRUPTED')&&(a.accepted_lease!==null||u.model_call_attempted===false&&run.status==='cancelled');
}
export async function verifyChargeRun(run,expected={},options={}){try{
 if(!current(options)||!keys(run,runNames)||!scalarJsonValue(run)||run.feature_key!=='charge_reconciliation'||!uuid(run.run_id)||expected.runId!==null&&expected.runId!==undefined&&expected.runId!==run.run_id||!['queued','running','succeeded','failed','cancelled'].includes(run.status)||![0,1].includes(run.preview)||!Number.isSafeInteger(run.preview)||!nonnegative(run.prompt_version)||!positive(run.provider_revision)||run.requires_human_review!==true||typeof run.feature_name!=='string'||!legacyClock(run.create_time)||[run.start_time,run.finish_time].some(v=>v!==null&&!legacyClock(v))||![null,'string'].includes(run.error_code===null?null:typeof run.error_code)||run.error_message!==null&&typeof run.error_message!=='string')return false;
 const checked=await verifyPacket(run.charge_findings,expected,options,true);if(!checked)return false;
 const b=checked.binding,a=run.charge_artifact,meta=run.context_metadata;
 if(run.patient_id!==b.patient_id||run.encounter_ref!==b.admission_id||run.charge_case_id!==b.case_snapshot_id||!valid('ChargeArtifactRecord',a)||a.run_id!==run.run_id||a.case_snapshot_id!==b.case_snapshot_id||!utc(a.created_at)||a.created_at<checked.short.snapshot_time||!keys(meta,[...metadataNames,...extraMetadata])||!same(pick(meta,metadataNames),checked.metadata)||!positive(meta.feature_revision)||!['unreviewed','pilot','validated','suspended'].includes(meta.validation_status)||typeof meta.model_version!=='string'||!meta.model_version||!hash(meta.instructions_digest)||meta.tool_fingerprint!==await digest({})||run.context_digest!==checked.metadata.context_digest||a.context_digest!==run.context_digest||a.source_binding_hash!==await digest(b)||!same(run.evidence,checked.evidence)||a.evidence_hash!==await digest(run.evidence)||a.metadata_hash!==await digest(meta)||!usageValid(run)||!current(options))return false;
 if(run.status!=='succeeded')return run.result===null&&a.result_hash===null&&a.result_bytes===null&&current(options);
 return run.error_code===null&&run.error_message===null&&run.usage_receipt.model_call_attempted===true&&run.usage_receipt.complete===true&&uuid(a.accepted_lease)&&resultValid(run.result,checked.source,b.projection_hash)&&a.result_bytes===bytes(run.result)&&a.result_hash===await digest(run.result)&&current(options);
}catch{return false;}}
export function verifyChargeQueuedReceipt(receipt,run){try{
 const names=['run_id','feature_key','preview','prompt_version','provider_revision','context_digest','patient_id','encounter_ref','feature_name','requires_human_review','context_metadata','charge_case_id'];
 return object(run)&&keys(receipt,runNames.filter(name=>!['charge_artifact','charge_findings','result','evidence'].includes(name)))&&scalarJsonValue(receipt)&&receipt.status==='queued'&&same(pick(receipt,names),pick(run,names))&&receipt.error_code===null&&receipt.error_message===null&&receipt.latency_ms===null&&receipt.start_time===null&&receipt.finish_time===null&&receipt.create_time===run.create_time&&receipt.input_tokens===null&&receipt.output_tokens===null&&receipt.usage_receipt_status==='pending'&&same(receipt.usage_receipt,{input_tokens:null,output_tokens:null,complete:false,model_call_attempted:null});
}catch{return false;}}
export async function verifyChargeTrace(trace,run,expected={},options={}){try{
 if(options.allowFrozenAudit!==true||!current(options)||!object(trace)||!object(run)||trace.run_id!==run.run_id||trace.snapshot_complete!==true||!positive(trace.provider_id)||trace.requested_by!==run.charge_artifact?.requested_by||!await verifyChargeRun(run,expected,options))return false;
 const paired=pick(trace,runNames);
 if(!await verifyChargeRun(paired,{...expected,runId:run.run_id},options)||!same(pick(paired,runNames.filter(name=>name!=='charge_findings')),pick(run,runNames.filter(name=>name!=='charge_findings')))||!same(pick(paired.charge_findings,['charge_binding','charge_source','input','context']),pick(run.charge_findings,['charge_binding','charge_source','input','context'])))return false;
 const raw=trace.raw_frozen_json;
 if(!keys(raw,['input_json','evidence_json','context_metadata_json']))return false;
 const a=run.charge_artifact;
 if(await textHash(raw.input_json)!==a.input_hash||await textHash(raw.evidence_json)!==a.evidence_hash||await textHash(raw.context_metadata_json)!==a.metadata_hash||!current(options))return false;
 const input=parseOriginalJson(raw.input_json),evidence=parseOriginalJson(raw.evidence_json),metadata=parseOriginalJson(raw.context_metadata_json);
 if(!same(input,trace.frozen_request)||!same(evidence,run.evidence)||!same(metadata,run.context_metadata)||!keys(input,['catalog_version','system_prompt','task_prompt','payload','provider_snapshot','feature_validation'])||typeof input.catalog_version!=='string'||!input.catalog_version||typeof input.system_prompt!=='string'||typeof input.task_prompt!=='string'||!input.task_prompt||!keys(input.payload,['input','context','tools','evidence'])||!same(input.payload.input,run.charge_findings.input)||!same(input.payload.context,run.charge_findings.context)||!same(input.payload.tools,{})||!same(input.payload.evidence,evidence)||!valid('ChargeFrozenProvider',input.provider_snapshot)||!valid('ChargeFrozenValidation',input.feature_validation))return false;
 const provider=input.provider_snapshot,validation=input.feature_validation;
 return provider.provider_id===trace.provider_id&&provider.revision===run.provider_revision&&provider.model===metadata.model_version&&provider.effective_output_limit<=provider.max_output_tokens&&validation.feature_revision===metadata.feature_revision&&validation.status===metadata.validation_status&&(validation.validated_at===null||legacyClock(validation.validated_at,true))&&await textHash(input.system_prompt)===fixed.system_prompt_digest&&await textHash(input.system_prompt+'\n\n'+input.task_prompt)===metadata.instructions_digest&&await digest([input.system_prompt,input.task_prompt])===a.prompt_hash&&current(options);
}catch{return false;}}
