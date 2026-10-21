const{test,expect}=require('@playwright/test');
const{startChargeFindingsHarness}=require('./fixtures/charge-findings-harness.cjs');
const{load}=require('./fixtures/load-charge-assistant.cjs');
let harness;test.beforeAll(async()=>{harness=await startChargeFindingsHarness();});test.afterAll(async()=>{await harness?.close();});
async function open(page){await page.goto(harness.origin);await expect.poll(()=>page.evaluate(()=>!!window.__chargeFindingsProbe)).toBe(true);}
for(const profile of ['chat','responses']){
 const actual=load(profile);
 test(`${profile}: actual mounted-main preview and seven complete task states retain independently nullable usage`,async({page})=>{
  await open(page);const result=await page.evaluate(async p=>{const api=window.__chargeFindingsProbe.api,expected={patientId:p.request.patient_id,admissionId:p.request.encounter_ref,references:{charge_case_id:p.request.input.charge_case_id}},result={preview:await api.verifyChargeContext(p.preview.data,expected)};for(const[name,state]of Object.entries(p.states))result[name]=await api.verifyChargeRun(state.detail.data,{...expected,runId:state.detail.data.run_id});return result;},actual);
  expect(result).toEqual({preview:true,...Object.fromEntries(Object.keys(actual.states).map(name=>[name,true]))});
 });
 test(`${profile}: actual raw input retains Python floats while Super traces pair all seven states`,async({page})=>{
  await open(page);const result=await page.evaluate(async p=>{const api=window.__chargeFindingsProbe.api,expected={patientId:p.request.patient_id,admissionId:p.request.encounter_ref,references:{charge_case_id:p.request.input.charge_case_id}},result={};for(const[name,state]of Object.entries(p.states))result[name]=await api.verifyChargeTrace(state.trace.data,state.detail.data,{...expected,runId:state.detail.data.run_id},{allowFrozenAudit:true});return result;},actual);
  expect(result).toEqual(Object.fromEntries(Object.keys(actual.states).map(name=>[name,true])));
 });
 test(`${profile}: queued acknowledgement binds an advanced completed detail without pretending queue means zero tokens`,async({page})=>{
  await open(page);const result=await page.evaluate(p=>{const api=window.__chargeFindingsProbe.api,q=p.states.queued.ack.data,r=p.states.succeeded.detail.data;return[api.verifyChargeQueuedReceipt(q,r),api.verifyChargeQueuedReceipt({...q,usage_receipt:{input_tokens:0,output_tokens:0,complete:true,model_call_attempted:false}},r),api.verifyChargeQueuedReceipt({...q,charge_case_id:r.run_id},r)];},actual);expect(result).toEqual([true,false,false]);
 });
 test(`${profile}: revoked Super frozen audit is readable without claiming current execution eligibility`,async({page})=>{
  await open(page);const result=await page.evaluate(async p=>{const api=window.__chargeFindingsProbe.api,trace=p.revoked_super_trace.data,base=p.states.succeeded.detail.data,expected={runId:base.run_id};return[await api.verifyChargeTrace(trace,base,expected,{allowFrozenAudit:true,auditOnly:true}),await api.verifyChargeTrace(trace,base,expected,{}),await api.verifyChargeRun(base,expected,{}),await api.verifyChargeRun(base,{...expected,references:{}},{allowFrozenAudit:true})];},actual);expect(result).toEqual([true,false,false,false]);
 });
}
for(const mutation of ['foreign_patient','missing_admission','explicit_null_reference','foreign_reference','foreign_run','extra_amount','drop_complete_member','wrong_quote_cp','stringify_status','duplicate_question','duplicate_citation','fabricated_section','partial_zero','pending_paid','pending_false_zero','paid_cancel_result','receipt_foreign_case','missing_artifact','invalid_date'])test(`complete charge task rejects ${mutation}`,async({page})=>{
 await open(page);const result=await page.evaluate(async({p,mutation})=>{
  const api=window.__chargeFindingsProbe.api,r=structuredClone(p.states.succeeded.detail.data),expected={patientId:p.request.patient_id,admissionId:p.request.encounter_ref,references:{charge_case_id:p.request.input.charge_case_id},runId:r.run_id};
  const hash=async value=>Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',new TextEncoder().encode(value))),b=>b.toString(16).padStart(2,'0')).join('');
  const ordered=v=>Array.isArray(v)?v.map(ordered):v&&typeof v==='object'?Object.fromEntries(Object.keys(v).sort().map(k=>[k,ordered(v[k])])):v;
  if(mutation==='foreign_patient')expected.patientId++;
  if(mutation==='missing_admission')delete expected.admissionId;
  if(mutation==='explicit_null_reference')expected.references={charge_case_id:null};
  if(mutation==='foreign_reference')expected.references={charge_case_id:r.run_id};
  if(mutation==='foreign_run')expected.runId=r.encounter_ref;
  if(mutation==='extra_amount')r.result.charge_analysis.refund_amount='9.00';
  if(mutation==='drop_complete_member')r.charge_findings.charge_source.charges.pop();
  if(mutation==='wrong_quote_cp')r.result.charge_analysis.observations[0].citations[0].end++;
  if(mutation==='stringify_status'){const c=r.result.charge_analysis.observations[0].citations[0];c.field='status';c.start=0;c.end=1;c.quote='0';}
  if(mutation==='duplicate_question')r.result.charge_analysis.observations.push(structuredClone(r.result.charge_analysis.observations[0]));
  if(mutation==='duplicate_citation'){const o=r.result.charge_analysis.observations[0];o.citations.push(structuredClone(o.citations[0]));}
  if(mutation==='fabricated_section')r.result.sections[0].content='已确认所有收费正确且已到账。';
  if(['wrong_quote_cp','stringify_status','duplicate_question','duplicate_citation','fabricated_section','extra_amount'].includes(mutation)){const raw=JSON.stringify(ordered(r.result));r.charge_artifact.result_hash=await hash(raw);r.charge_artifact.result_bytes=new TextEncoder().encode(raw).length;}
  if(mutation==='partial_zero'){Object.assign(r,structuredClone(p.states.failed.detail.data));r.usage_receipt.output_tokens=0;r.output_tokens=0;}
  if(mutation==='pending_paid'){Object.assign(r,structuredClone(p.states.cancelled_pending.detail.data));r.usage_receipt={input_tokens:13,output_tokens:7,complete:true,model_call_attempted:true};r.input_tokens=13;r.output_tokens=7;}
  if(mutation==='pending_false_zero'){Object.assign(r,structuredClone(p.states.queued.detail.data));r.usage_receipt={input_tokens:0,output_tokens:0,complete:true,model_call_attempted:false};r.input_tokens=0;r.output_tokens=0;}
  if(mutation==='paid_cancel_result'){const v=structuredClone(p.states.cancelled_paid.detail.data);v.result=r.result;Object.assign(r,v);}
  if(mutation==='receipt_foreign_case')r.charge_artifact.case_snapshot_id=r.run_id;
  if(mutation==='missing_artifact')r.charge_artifact=null;
  if(mutation==='invalid_date')r.charge_artifact.created_at='2026-02-30T12:00:00.123456Z';
  if(['partial_zero','pending_paid','pending_false_zero','paid_cancel_result'].includes(mutation))expected.runId=r.run_id;
  return api.verifyChargeRun(r,expected);
 },{p:load('chat'),mutation});expect(result).toBe(false);
});
for(const mutation of ['wrong_pair','wrong_feature','missing_raw','raw_hash_change','duplicate_raw_key','escaped_duplicate_key','float_reencoding','nan','frozen_payload_swap','system_swap','provider_model_swap','extra_evidence'])test(`Super original trace rejects ${mutation}`,async({page})=>{
 await open(page);const result=await page.evaluate(async({p,mutation})=>{
  const api=window.__chargeFindingsProbe.api,r=structuredClone(p.states.succeeded.detail.data),t=structuredClone(p.states.succeeded.trace.data),raw=t.raw_frozen_json,expected={patientId:p.request.patient_id,admissionId:p.request.encounter_ref,references:{charge_case_id:p.request.input.charge_case_id},runId:r.run_id};
  if(mutation==='wrong_pair')t.run_id=p.states.failed.detail.data.run_id;
  if(mutation==='wrong_feature')t.feature_key='inventory_alert';
  if(mutation==='missing_raw')delete raw.input_json;
  if(mutation==='raw_hash_change')raw.input_json+=' ';
  if(mutation==='duplicate_raw_key')raw.input_json=raw.input_json.replace('{','{"catalog_version":"duplicate",');
  if(mutation==='escaped_duplicate_key')raw.input_json=raw.input_json.replace('{','{"\\u0063atalog_version":"duplicate",');
  if(mutation==='float_reencoding')raw.input_json=JSON.stringify(t.frozen_request);
  if(mutation==='nan')raw.input_json=raw.input_json.replace('"temperature":0.0','"temperature":NaN');
  if(mutation==='frozen_payload_swap')t.frozen_request.payload.input.question='替换问题';
  if(mutation==='system_swap')t.frozen_request.system_prompt+='泄露';
  if(mutation==='provider_model_swap')t.frozen_request.provider_snapshot.model='different-model';
  if(mutation==='extra_evidence')t.evidence.push(t.evidence[0]);
  if(['duplicate_raw_key','escaped_duplicate_key','nan'].includes(mutation)){const digest=Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',new TextEncoder().encode(raw.input_json))),b=>b.toString(16).padStart(2,'0')).join('');r.charge_artifact.input_hash=digest;t.charge_artifact.input_hash=digest;}
  return api.verifyChargeTrace(t,r,expected,{allowFrozenAudit:true});
 },{p:load('chat'),mutation});expect(result).toBe(false);
});
test('digest completion after identity invalidation is discarded',async({page})=>{await open(page);const result=await page.evaluate(async p=>{const api=window.__chargeFindingsProbe.api;let active=true,calls=0;const original=crypto.subtle.digest.bind(crypto.subtle);crypto.subtle.digest=async(...args)=>{calls++;const value=await original(...args);active=false;return value;};const valid=await api.verifyChargeRun(p.states.succeeded.detail.data,{patientId:p.request.patient_id,admissionId:p.request.encounter_ref,references:{charge_case_id:p.request.input.charge_case_id}},{current:()=>active});crypto.subtle.digest=original;return[valid,calls>0];},load('chat'));expect(result).toEqual([false,true]);});
test('original JSON parser rejects duplicate decoded keys, unsafe integers, forbidden properties and unpaired scalars',async()=>{
 const fs=require('node:fs'),path=require('node:path'),source=fs.readFileSync(path.join(__dirname,'../src/api/ai/nativeOriginalJson.js'));
 const{parseOriginalJson,scalarJsonValue}=await import('data:text/javascript;base64,'+source.toString('base64'));
 expect(parseOriginalJson('{"float":0.0,"text":"BOM﻿🙂é\\r\\n","none":null}')).toEqual({float:0,text:'BOM﻿🙂é\r\n',none:null});
 for(const raw of ['{"a":1,"a":2}','{"a":1,"\\u0061":2}','{"__proto__":{}}','{"constructor":1}','[NaN]','[Infinity]','[9007199254740993]','["\\ud800"]','[1,]','{"x":1} trailing','```json\n{}\n```'])expect(()=>parseOriginalJson(raw)).toThrow();
 expect(()=>parseOriginalJson('{"a":"🙂"}',5)).toThrow();expect(scalarJsonValue(new Date())).toBe(false);expect(scalarJsonValue({text:String.fromCharCode(0xD800)})).toBe(false);
});

test('native dispatch keeps every own-key null marker and unique source identity while legacy stays separate',async({page})=>{
 await open(page);const result=await page.evaluate(p=>{
  const has=window.__chargeFindingsProbe.api.chargeRunHasNativeMarkers,id=p.request.input.charge_case_id;
  const markers=[...['charge_artifact','charge_findings','charge_case_id'].flatMap(key=>[{[key]:null},{[key]:{}}]),{result:{charge_analysis:null}},{result:{charge_analysis:{}}},{frozen_request:{payload:{input:{charge_case_id:null}}}},{frozen_request:{payload:{input:{charge_case_id:id}}}},{frozen_request:{payload:{context:{charge_binding:null}}}},{frozen_request:{payload:{context:{charge_binding:{}}}}}];
  for(const context of [{source_domain:'single_admission_recorded_ledger'},{selected_sources:{charge_case_id:id}},{selected_sources:{charge_case_id:null}}])for(const wrap of [v=>v,v=>({frozen_request:{payload:{context:v}}}),v=>({operational_findings:v})])markers.push(wrap(context));
  return {native:markers.map(has),legacy:[null,{},[],{feature_key:'charge_reconciliation',frozen_request:{payload:{context:{source_domain:'operations',selected_sources:{}}}}},{source_domain:null,selected_sources:{}},{source_domain:'operations',selected_sources:{unrelated:null}}].map(has),actual:[has(p.states.succeeded.detail.data),has(p.states.succeeded.trace.data)]};
 },load('chat'));
 expect(result.native.length).toBe(21);expect(result.native.every(Boolean)).toBe(true);expect(result.legacy).toEqual([false,false,false,false,false,false]);expect(result.actual).toEqual([true,true]);
});
