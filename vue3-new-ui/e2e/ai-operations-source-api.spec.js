// isolated_mock: actual mounted Main/JWT synthetic-source HTTP bytes, real API,
// crypto and canonical Babel. No backend socket, model call or process execution.
const{test,expect}=require('@playwright/test');
const{startOperationsHarness}=require('./fixtures/operations-support-harness.cjs');
const{loadOperationsPackets}=require('./fixtures/operations-support-packets.cjs');
const source=loadOperationsPackets('sources'),main=loadOperationsPackets('main-custom-prompt');let harness;
test.beforeAll(async()=>{harness=await startOperationsHarness();});test.afterAll(async()=>{await harness?.close();});
test.beforeEach(async({page})=>{await page.goto(harness.origin);await expect.poll(()=>page.evaluate(()=>!!window.__operationsProbe)).toBe(true);});
const row=(i)=>source.data(source.rows[i]);
test('actual complete Source lifecycle metadata, private transform and public projection agree',async({page})=>{
 const result=await page.evaluate(async values=>{const a=window.__operationsProbe.api,[om,o,dm,d,pm,doc,cm,publicBody,privateBody]=values;return[
 a.verifyOperationsOriginalMetadata(om),await a.verifyOperationsOriginal(o,om),a.verifyOperationsReleaseMetadata(dm),await a.verifyOperationsReleaseDraft(d,dm,o),a.verifyOperationsReleaseMetadata(pm),await a.verifyOperationsReleasedDocument(doc),a.verifyOperationsCaseMetadata(cm),await a.verifyOperationsCaseParts(cm,{source:a.decodeOperationsPart(publicBody),private:a.decodeOperationsPart(privateBody)}),a.operationsSame(await a.projectOperationsCollection(JSON.parse(privateBody)),JSON.parse(publicBody))];},[row(0),row(2),row(3),row(5),row(6),row(7),row(8),source.rows[10].body,source.rows[11].body]);
 expect(result).toEqual(Array(9).fill(true));
});
test('actual bounded directories keep Sup and ordinary opaque rows distinct',async({page})=>{
 expect(await page.evaluate(values=>{const a=window.__operationsProbe.api;return values.map(([v,k,s])=>a.verifyOperationsSourceDirectory(v,k,{superAdmin:s}));},[[row(12),'originals',true],[row(13),'releases',true],[row(14),'cases',true],[row(15),'releases',false]])).toEqual([true,true,true,true]);
});
test('actual revoked originals releases and Case remain technical metadata without selectable body',async({page})=>{
 expect(await page.evaluate(values=>{const a=window.__operationsProbe.api;return[a.verifyOperationsCaseMetadata(values[0]),a.verifyOperationsReleaseMetadata(values[1]),a.verifyOperationsOriginalMetadata(values[2]),values[0].source_accessible];},[row(16),row(17),row(18)])).toEqual([true,true,true,false]);
});
for(const raw of ['{"a":1,"a":2}','{"__proto__":{}}','{"n":1.0}','{"n":1e0}','{"n":NaN}','{"n":9007199254740992}','{"s":"\\ud800"}'])test('strict raw wire rejects '+raw,async({page})=>{
 expect(await page.evaluate(raw=>{try{window.__operationsProbe.api.decodeOperationsPart(raw);return false;}catch{return true;}},raw)).toBe(true);
});
test('fatal UTF8 and whole8MiB checks never decode a prefix',async({page})=>{
 expect(await page.evaluate(()=>{const a=window.__operationsProbe.api;return[new Uint8Array([0xc0,0x80]),new Uint8Array(8388609)].map(x=>{try{a.decodeOperationsPart(x);return false;}catch{return true;}});})).toEqual([true,true]);
});
test('explicit scalar-codepoint redactions preserve BOM CRLF emoji and never scan automatically',async({page})=>{
 expect(await page.evaluate(()=>{const a=window.__operationsProbe.api;return[a.operationsRedact('\ufeffA😀\r\nZ',[{start_codepoint:2,end_codepoint:3,method:'mask'}]),a.operationsRedact('A😀B',[]),a.operationsRequestValid('ReleaseCreate',{original_id:'11111111-1111-1111-1111-111111111111',original_full_sha256:'a'.repeat(64),released_title:'材料',released_component:null,released_version:null,redactions:[{start_codepoint:2,end_codepoint:1,method:'remove'}]})];})).toEqual(['\ufeffA[已遮盖]\r\nZ','A😀B',false]);
});
test('invalid calendar is rejected even after recomputing all public digest material',async({page})=>{
 expect(await page.evaluate(async body=>{const a=window.__operationsProbe.api;body.assembled_at='2026-02-30T12:00:00.000000Z';return a.verifyOperationsPublicSource(body);},row(10))).toBe(false);
});
test('ordinary Source guard cannot use a digest-only metadata claim to invent the protected body',async({page})=>{
 const cm=row(8),body=source.rows[10].body;
 expect(await page.evaluate(async({cm,body})=>{const a=window.__operationsProbe.api;return[await a.verifyOperationsCaseParts(cm,{source:a.decodeOperationsPart(body)}),await a.verifyOperationsCaseParts(cm,{source:a.decodeOperationsPart(body),private:{raw:'null',value:null}})];},{cm,body})).toEqual([true,false]);
});
test('same-case actual UUID Prompt task, queued running success metadata and full parts close',async({page})=>{
 const body=index=>main.data(main.rows[index]),meta=body(29),cm=body(10),parts=Object.fromEntries(['task','source','binding','result'].map((name,i)=>[name,main.rows[25+i].body]));
 const result=await page.evaluate(async({meta,cm,parts,queued,running,trace})=>{const a=window.__operationsProbe.api;const decoded=Object.fromEntries(Object.entries(parts).map(([k,r])=>[k,a.decodeOperationsPart(r)]));return[a.verifyOperationsTaskMetadata(queued),a.verifyOperationsTaskMetadata(running),a.verifyOperationsTaskMetadata(meta),a.verifyOperationsTrace(trace),await a.verifyOperationsTaskParts(meta,decoded,{caseMetadata:cm}),a.operationsId(decoded.binding.value.prompt_id)];},{meta,cm,parts,queued:body(22),running:body(24),trace:body(30)});
 expect(result).toEqual(Array(6).fill(true));
});
for(const variant of ['wrong-case','quote-utf16','manual-log-instruction','unknown-key'])test('current task rejects '+variant,async({page})=>{
 const body=index=>main.data(main.rows[index]),data={metadata:body(29),cm:body(10),parts:Object.fromEntries(['task','source','binding','result'].map((name,i)=>[name,main.rows[25+i].body])),variant};
 expect(await page.evaluate(async v=>{const a=window.__operationsProbe.api,parts=Object.fromEntries(Object.entries(v.parts).map(([k,x])=>[k,a.decodeOperationsPart(x)]));if(v.variant==='wrong-case')v.cm.case_id='11111111-1111-1111-1111-111111111111';else{const result=structuredClone(parts.result.value);if(v.variant==='quote-utf16')result.observations[0].evidence[0].end_codepoint++;if(v.variant==='unknown-key')result.execute_command='not permitted';if(v.variant==='manual-log-instruction')result.manual_checks=[{purpose:'人为添加',instruction_reference:result.observations[0].evidence[0],applicability:'requires_current_environment_and_admin_review',impact:'not_established_by_this_draft',execution:'reference_only_no_automatic_execution'}];parts.result=a.decodeOperationsPart(a.operationsCanonical(result));}return a.verifyOperationsTaskParts(v.metadata,parts,{caseMetadata:v.cm});},data)).toBe(false);
});
test('structural native markers include null fields but not question literals',async({page})=>{
 expect(await page.evaluate(()=>{const a=window.__operationsProbe.api;return[{operations_case_id:null},{feature_key:'operations_support'},{question:'operations_case_id'},{raw_frozen_json:null}].map(a.operationsRunHasMarkers);})).toEqual([true,true,false,false]);
});
test('explicit request closure rejects patients free questions and noncanonical foreign references',async({page})=>{
 expect(await page.evaluate(()=>{const a=window.__operationsProbe.api,v={operations_case_id:'11111111-1111-1111-1111-111111111111',objective:'explain_observations'};return[a.operationsRequestValid('OperationsTaskSelection',v),a.operationsRequestValid('OperationsTaskSelection',{...v,patient_id:1}),a.operationsRequestValid('OperationsTaskSelection',{...v,question:'free'}),a.operationsRequestValid('OperationsTaskSelection',{...v,objective:'execute'})];})).toEqual([true,false,false,false]);
});

test('actual descriptor and queued cancellation ACK bind closed fields and actual receipt PK',async({page})=>{
 expect(await page.evaluate(({descriptor,ack})=>{const a=window.__operationsProbe.api;return[a.verifyOperationsTaskDescriptor(descriptor),a.verifyOperationsTaskDescriptor({...descriptor,parts:['source']}),a.verifyOperationsCancelAck(ack,{runId:ack.run_id}),a.verifyOperationsCancelAck({...ack,usage_event_id:null}),a.verifyOperationsCancelAck(ack,{runId:'11111111-1111-1111-1111-111111111111'})];},{descriptor:main.data(main.rows[1]),ack:main.data(main.rows[20])})).toEqual([true,false,true,false,false]);
});
test('actual feature configuration is required for execution while Super preview remains explicit',async({page})=>{
 const feature=main.data(main.rows[0]).find(v=>v.key==='operations_support');expect(await page.evaluate(f=>{const a=window.__operationsProbe.api;return[a.operationsFeatureAllowed(f,'admin'),a.operationsFeatureAllowed({...f,enabled:false},'admin'),a.operationsFeatureAllowed({...f,validation_status:'unreviewed'},'admin'),a.operationsFeatureAllowed({...f,enabled:false,validation_status:'unreviewed'},'super_admin',{preview:true}),a.operationsFeatureAllowed(f,'doctor'),a.operationsFeatureAllowed({...f,input_mode:'chat'},'super_admin')];},feature)).toEqual([true,false,false,true,false,false]);
});
test('selection refs have one canonical Case key and no patient free question or objective',async({page})=>{
 expect(await page.evaluate(()=>{const a=window.__operationsProbe.api,v={operations_case_id:'11111111-1111-1111-1111-111111111111'};return[a.operationsReferencesValid(v),a.operationsReferencesValid({...v,objective:'explain_observations'}),a.operationsReferencesValid({...v,patient_id:1}),a.operationsReferencesValid({...v,question:'free'}),a.operationsReferencesValid({operations_case_id:null})];})).toEqual([true,false,false,false,false]);
});
