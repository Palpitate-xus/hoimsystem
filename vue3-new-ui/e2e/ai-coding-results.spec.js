const {test,expect}=require('@playwright/test');
const actual=require('./fixtures/coding-results-actual.json');
const {startCodingResultsHarness}=require('./fixtures/coding-results-harness.cjs');
let harness;
test.beforeAll(async()=>{harness=await startCodingResultsHarness();});
test.afterAll(async()=>{await harness?.close();});
async function open(page){await page.goto(harness.origin);await expect.poll(()=>page.evaluate(()=>!!window.__codingResultProbe)).toBe(true);}

test('actual same-case preview running success receipt and revoked Super audit retain full original proofs',async({page})=>{
 await open(page);
 const values=await page.evaluate(async a=>{const p=window.__codingResultProbe.api;return[await p.verifyCodingContext(a.preview.data.context),await p.verifyCodingRun(a.running.data),await p.verifyCodingRun(a.detail.data),p.verifyCodingReceipt(a.queued.data,a.detail.data),await p.verifyCodingRun(a.audit.data,{}, {auditOnly:true}),await p.verifyCodingRun(a.audit.data)];},actual);
 expect(values).toEqual([true,true,true,true,true,false]);
});
for(const attack of ['missing_claim','duplicate_claim','wrong_quote','utf16_offset','unknown_document','invent_group','confirmed_summary','wrong_scope','missing_frozen_meta','mixed_source'])test('complete actual coding result rejects '+attack,async({page})=>{
 await open(page);
 const value=await page.evaluate(async({a,attack})=>{const p=window.__codingResultProbe.api,r=structuredClone(a.detail.data),claim=r.result.coding_analysis.claims[0];if(attack==='missing_claim')r.result.coding_analysis.claims=[];if(attack==='duplicate_claim')r.result.coding_analysis.claims.push(structuredClone(claim));if(attack==='wrong_quote')claim.citations[0].quote+='新字';if(attack==='utf16_offset')claim.citations[0].end++;if(attack==='unknown_document')claim.citations[0].document_source_id='another-patient';if(attack==='invent_group')r.result.coding_analysis.group_code='new-group';if(attack==='confirmed_summary')r.result.summary='已确认编码分组正确';if(attack==='wrong_scope')r.patient_id++;if(attack==='missing_frozen_meta')delete r.context_metadata.instructions_digest;if(attack==='mixed_source')r.inventory_findings={};return p.verifyCodingRun(r);},{a:actual,attack});
 expect(value).toBe(false);
});
test('tampered literal body cannot self certify with recalculated outward hashes',async({page})=>{
 await open(page);
 const result=await page.evaluate(async a=>{const p=window.__codingResultProbe,r=structuredClone(a.detail.data),source=r.coding_findings.coding_source;source.documents[0].text+='伪造原文';r.coding_findings.coding_binding.projection_hash=await p.supportDigest(source);r.result.coding_analysis.source_projection_hash=r.coding_findings.coding_binding.projection_hash;return p.api.verifyCodingRun(r);},actual);
 expect(result).toBe(false);
});
test('receipt cannot switch original patient Admission or model Prompt metadata',async({page})=>{
 await open(page);
 const results=await page.evaluate(a=>{const p=window.__codingResultProbe.api;return ['patient_id','encounter_ref','context_metadata','provider_revision'].map(k=>{const r=structuredClone(a.queued.data);r[k]=k==='context_metadata'?{...r[k],model_version:'other'}:k==='patient_id'||k==='provider_revision'?r[k]+1:'another';return p.verifyCodingReceipt(r,a.detail.data);});},actual);
 expect(results).toEqual([false,false,false,false]);
});
test('source evidence resolution returns full authorized original only after complete proof',async({page})=>{
 await open(page);
 const result=await page.evaluate(async a=>{const p=window.__codingResultProbe.api,e=a.detail.data.evidence[0],packet=a.detail.data.coding_findings,value=await p.resolveCodingEvidence(e,packet);return[!!value?.content.includes('identity_secret'),await p.resolveCodingEvidence({...e,content:'arbitrary'},packet),await p.resolveCodingEvidence(e,{...packet,coding_case:null})];},actual);
 expect(result).toEqual([true,null,null]);
});
test('strict coding markers remain present with null bodies or a changed feature discriminator',async({page})=>{
 await open(page);
 const result=await page.evaluate(()=>{const p=window.__codingResultProbe.api;return[{feature_key:'drg_evidence_review'},{coding_findings:null},{result:{coding_analysis:null}},{frozen_request:{payload:{input:{coding_case_id:null}}}},{operational_findings:{source_domain:'single_home_coding_evidence'}},{}].map(p.codingRunHasMarkers);});
 expect(result).toEqual([true,true,true,true,true,false]);
});
test('expired verification lease never restores a coding result after async proof',async({page})=>{
 await open(page);
 const result=await page.evaluate(async a=>{const p=window.__codingResultProbe.api;let calls=0;return p.verifyCodingRun(a.detail.data,{}, {current:()=>++calls<3});},actual);
 expect(result).toBe(false);expect(harness.unhandled).toEqual([]);
});
test('complete Super audit rejects deletion of each of twelve provider and five validation fields',async({page})=>{
 await open(page);
 const results=await page.evaluate(async a=>{const p=window.__codingResultProbe.api,out=[];for(const container of ['provider_snapshot','feature_validation'])for(const key of Object.keys(a.audit.data.frozen_request[container])){const r=structuredClone(a.audit.data);delete r.frozen_request[container][key];out.push(await p.verifyCodingRun(r,{}, {auditOnly:true}));}return out;},actual);
 expect(results).toHaveLength(17);expect(results.every(v=>v===false)).toBe(true);
});
