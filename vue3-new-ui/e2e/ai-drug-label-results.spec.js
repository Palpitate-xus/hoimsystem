const {test,expect}=require('@playwright/test');
const {startDrugLabelTaskHarness}=require('./fixtures/drug-label-task-harness.cjs');
const {load}=require('./fixtures/load-drug-label-tasks.cjs');
let harness;
test.beforeAll(async()=>{harness=await startDrugLabelTaskHarness();});
test.afterAll(async()=>{await harness?.close();});
test.beforeEach(async({page})=>{await page.goto(harness.origin);await page.waitForFunction(()=>!!window.__drugLabelTaskProbe);});
for(const kind of ['chat','responses'])test(`actual ${kind} seven states nullable receipts and complete raw trace`,async({page})=>{
 const packet=load(kind);const values=await page.evaluate(async packet=>{const a=window.__drugLabelTaskProbe.api,out=[];for(const {detail,trace}of Object.values(packet.states)){const expected={runId:detail.run_id,references:{drug_label_source_binding_id:detail.drug_label_source_binding_id},pharmaceuticalId:detail.drug_label_findings.drug_label_source_record.snapshot.identity.pharmaceutical_id};out.push(await a.verifyDrugLabelRun(detail,expected),await a.verifyDrugLabelTrace(trace,detail,expected,{allowFrozenAudit:true}));}const t=packet.revoked_super_trace,base=Object.fromEntries(Object.entries(t).filter(([key])=>!['requested_by','provider_id','snapshot_complete','frozen_request','raw_frozen_json'].includes(key)));out.push(await a.verifyDrugLabelRun(base,{}, {auditOnly:true,allowFrozenAudit:true}),await a.verifyDrugLabelTrace(t,base,{}, {auditOnly:true,allowFrozenAudit:true}),await a.verifyDrugLabelRun(base));return out;},packet);
 expect(values).toEqual([...Array(16).fill(true),false]);
});
for(const mutation of ['mixed_marker','private_seed','remove_anchor','source_text','source_signature','source_public','source_flags','context_hash','evidence','instructions','whole_result_hash','quote','explanation','unknown_to_zero','receipt_actor','run_clock'])test(`actual full task rejects ${mutation}`,async({page})=>{
 expect(await page.evaluate(async({packet,mutation})=>{const p=window.__drugLabelTaskProbe,a=p.api,v=structuredClone(packet.states.succeeded.detail),f=v.drug_label_findings,s=f.drug_label_source,r=f.drug_label_source_record;
  if(mutation==='mixed_marker')v.supply_findings={};if(mutation==='private_seed')v.drug_label_artifact.mapping_seed='a'.repeat(64);if(mutation==='remove_anchor')delete v.drug_label_artifact.input_hash;
  if(mutation==='source_text')r.snapshot.original.snapshot.text=r.snapshot.original.snapshot.text.replace('\r\n','\n');if(mutation==='source_signature')r.professional_review.snapshot.signed_by=r.snapshot.created_by;if(mutation==='source_public')s.sku.name='另一个药品';if(mutation==='source_flags')r.eligible=false;if(mutation==='context_hash')v.context_digest='a'.repeat(64);if(mutation==='evidence')v.evidence.pop();if(mutation==='instructions')v.context_metadata.instructions_digest='a'.repeat(64);
  if(mutation==='whole_result_hash')v.drug_label_artifact.result_hash='a'.repeat(64);if(mutation==='quote'){const d=v.result.drug_label_extraction;d.fields=[{field:'composition',spans:[{start:0,end:1,quote:'伪'}],review_question:'请药师逐字核对。'}];v.result.summary=v.result.summary.replace('0项','1项');v.drug_label_artifact.result_hash=await p.supportDigest(v.result);v.drug_label_artifact.result_bytes=new TextEncoder().encode(p.supportCanonical(v.result)).length;v.usage_receipt.result_hash=v.drug_label_artifact.result_hash;}
  if(mutation==='explanation')v.result.sections[0].content='已验证剂量适用';if(mutation==='unknown_to_zero'){const q=structuredClone(packet.states.failed_partial_usage.detail);q.output_tokens=0;return a.verifyDrugLabelRun(q);}if(mutation==='receipt_actor')v.usage_receipt.requested_by=1;if(mutation==='run_clock')v.create_time+='.123456';return a.verifyDrugLabelRun(v);
 },{packet:load('chat'),mutation})).toBe(false);
});
test('actual task scope refs and null fields cannot expand SKU or switch mode',async({page})=>{
 const values=await page.evaluate(async packet=>{const a=window.__drugLabelTaskProbe.api,v=packet.states.succeeded.detail,id=v.drug_label_source_binding_id;return [await a.verifyDrugLabelRun(v,{references:{drug_label_source_binding_id:id}}),await a.verifyDrugLabelRun(v,{references:{drug_label_source_binding_id:null}}),await a.verifyDrugLabelRun(v,{references:{drug_label_source_binding_id:id,patient_id:1}}),await a.verifyDrugLabelRun(v,{pharmaceuticalId:v.drug_label_findings.drug_label_source_record.snapshot.identity.pharmaceutical_id+1}),await a.verifyDrugLabelRun(v,{runId:'00000000-0000-0000-0000-000000000001'})];},load('chat'));
 expect(values).toEqual([true,false,false,false,false]);
});
test('empty and Unicode whitespace optional questions are legal unchanged, foreign refs are not',async({page})=>{
 const values=await page.evaluate(packet=>{const a=window.__drugLabelTaskProbe.api,id=packet.states.succeeded.detail.drug_label_source_binding_id;return [null,'',' \t\u2003','😀'.repeat(2000),'😀'.repeat(2001)].map(question=>a.drugLabelTaskInputValid({drug_label_source_binding_id:id,question})).concat(a.drugLabelTaskInputValid({drug_label_source_binding_id:id,patient_id:1}),a.drugLabelReferencesValid({drug_label_source_binding_id:null}));},load('chat'));
 expect(values).toEqual([true,true,true,true,false,false,false]);
});
for(const axis of ['raw_hash','duplicate_key_self_rehash','provider_deleted_self_rehash','provider_false_permission','missing_validation','source_pair'])test(`frozen exact original JSON rejects ${axis}`,async({page})=>{
 expect(await page.evaluate(async({packet,axis})=>{const p=window.__drugLabelTaskProbe,a=p.api,run=structuredClone(packet.states.succeeded.detail),trace=structuredClone(packet.states.succeeded.trace);if(axis==='raw_hash')trace.raw_frozen_json.input_json+=' ';
  if(axis==='duplicate_key_self_rehash')trace.raw_frozen_json.input_json=trace.raw_frozen_json.input_json.replace('{','{"catalog_version":"forged",');
  if(axis==='provider_deleted_self_rehash'){delete trace.frozen_request.provider_snapshot.revision;trace.raw_frozen_json.input_json=JSON.stringify(trace.frozen_request);}
  if(axis==='provider_false_permission'){trace.frozen_request.provider_snapshot.allows_patient_data=false;trace.raw_frozen_json.input_json=JSON.stringify(trace.frozen_request);}
  if(axis==='missing_validation'){delete trace.frozen_request.feature_validation.validated_by;trace.raw_frozen_json.input_json=JSON.stringify(trace.frozen_request);}
  if(axis==='source_pair')run.drug_label_findings.drug_label_source.sku.name='不匹配';
  if(axis!=='raw_hash'&&axis!=='source_pair'){const hash=await crypto.subtle.digest('SHA-256',new TextEncoder().encode(trace.raw_frozen_json.input_json));const text=[...new Uint8Array(hash)].map(x=>x.toString(16).padStart(2,'0')).join('');for(const v of [run,trace]){v.drug_label_artifact.input_hash=text;v.usage_receipt.input_hash=text;}}
  return a.verifyDrugLabelTrace(trace,run,{}, {allowFrozenAudit:true});
 },{packet:load('chat'),axis})).toBe(false);
});
test('current crypto caller ticket and explicit frozen audit are mandatory',async({page})=>{
 const values=await page.evaluate(async packet=>{const a=window.__drugLabelTaskProbe.api,v=packet.states.succeeded.detail,t=packet.states.succeeded.trace;let count=0;return [await a.verifyDrugLabelRun(v,{}, {current:()=>++count<4}),await a.verifyDrugLabelTrace(t,v),await a.verifyDrugLabelTrace(t,v,{}, {allowFrozenAudit:true,current:()=>false})];},load('chat'));
 expect(values).toEqual([false,false,false]);
});

const unknownLabels = require('./fixtures/native-unknown-usage.cjs').loadUnknownUsage('drug-label');
test('actual Chat and Responses retry success retain unknown usage and accepted result receipts',async({page})=>{
 expect(await page.evaluate(async packets=>Promise.all(packets.map(async p=>{
  const a=window.__drugLabelTaskProbe.api,u=p.detail.usage_receipt;
  return [await a.verifyDrugLabelRun(p.detail),await a.verifyDrugLabelTrace(p.trace,p.detail,{}, {allowFrozenAudit:true}),u.input_tokens,u.output_tokens,u.model_call_attempted];
 })),unknownLabels)).toEqual(Array.from({length:2},()=>[true,true,null,null,true]));
});
test('unknown successful label extraction refuses count divergence and a denied or unknown model attempt',async({page})=>{
 expect(await page.evaluate(async packets=>{
  const out=[];
  for(const p of packets)for(const change of ['counts','attempt','unknown_attempt']){
   const q=structuredClone(p);
   if(change==='counts')q.detail.usage_receipt.input_tokens=0;
   else q.detail.usage_receipt.model_call_attempted=change==='attempt'?false:null;
   out.push(await window.__drugLabelTaskProbe.api.verifyDrugLabelRun(q.detail));
  }
  return out;
 },unknownLabels)).toEqual(Array(6).fill(false));
});
test('unknown successful label extraction retains receipt result hashes and an accepted lease',async({page})=>{
 expect(await page.evaluate(async packets=>{
  const out=[];
  for(const p of packets)for(const change of ['hash','lease']){
   const q=structuredClone(p);if(change==='hash')q.detail.usage_receipt.result_hash='f'.repeat(64);else q.detail.usage_receipt.lease_token=null;
   out.push(await window.__drugLabelTaskProbe.api.verifyDrugLabelRun(q.detail));
  }
  return out;
 },unknownLabels)).toEqual(Array(4).fill(false));
});
