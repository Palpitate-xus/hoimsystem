const {test,expect}=require('@playwright/test');
const f=require('./fixtures/drug-label-sources/actual.json');
const {startDrugLabelHarness}=require('./fixtures/drug-label-source-harness.cjs');
let harness;
test.beforeAll(async()=>{harness=await startDrugLabelHarness();});
test.afterAll(async()=>{await harness?.close();});
test.beforeEach(async({page})=>{await page.goto(harness.origin);await page.waitForFunction(()=>!!window.__drugLabelProbe);});
const rows=f=>Object.values(f.states).flatMap(v=>Object.values(v).filter(x=>x?.schema_version==='drug_label_source_record_v1'));
test('all actual main Source states preserve whole original and independent signatures',async({page})=>{
 const values=await page.evaluate(async rows=>Promise.all(rows.map(v=>window.__drugLabelProbe.api.verifyDrugLabelSource(v,{auditOnly:v.audit_only}))),rows(f));
 expect(values).toEqual(Array(rows(f).length).fill(true));
});
test('actual options catalog and exact metadata pages validate without executable metadata',async({page})=>{
 const values=await page.evaluate(async f=>{const a=window.__drugLabelProbe.api,id=f.catalog.items[0].identity.pharmaceutical_id;return [a.drugLabelOptionsValid(f.super_options,{role:'super_admin'}),a.drugLabelOptionsValid(f.pharmacist_options,{role:'pharmacist'}),await a.verifyDrugLabelCatalog(f.catalog,{afterId:id-1,pageSize:1}),a.drugLabelDirectoryValid(f.directory,{pharmaceuticalId:id,pageSize:100}),a.drugLabelDirectoryValid(f.admin_directory,{auditOnly:true,pageSize:100}),await a.verifyDrugLabelSource(f.directory.items[0])];},f);
 expect(values).toEqual([true,true,true,true,true,false]);
});
test('all actual create sign review revoke receipts bind unchanged source and submitted CAS',async({page})=>{
 const values=await page.evaluate(async f=>{const a=window.__drugLabelProbe.api,out=[];for(const v of Object.values(f.states)){out.push(await a.verifyDrugLabelCreated(v.draft_super,v.create_request,f.original_parent),await a.verifyDrugLabelTransition(v.signed,v.draft_pharmacist,'sign',v.signature_request,{role:'pharmacist',actorId:f.pharmacist_options.professional_signer_user_id}),await a.verifyDrugLabelTransition(v.reviewed_super,v.signed,'review',v.technical_review_request,{role:'super_admin'}));}const p=f.states.published,w=f.states.professional_withdrawn;out.push(await a.verifyDrugLabelTransition(p.source_revoked,p.reviewed_super,'revoke',p.source_revoke_request,{role:'super_admin'}),await a.verifyDrugLabelTransition(w.signature_revoked,w.reviewed_super,'professional_revoke',w.signature_revoke_request,{role:'pharmacist'}));return out;},f);
 expect(values).toEqual(Array(11).fill(true));
});
for(const mutation of ['raw_text','cp','identity','original_governance','source_hash','signature_parent','signature_hash','self_signer','unknown_published','boolean_revision','missing','foreign'])test(`full source rejects ${mutation}`,async({page})=>{
 expect(await page.evaluate(async({f,mutation})=>{const p=window.__drugLabelProbe,v=structuredClone(f.states.published.ordinary_current),s=v.snapshot,q=v.professional_review;if(mutation==='raw_text')s.original.snapshot.text=s.original.snapshot.text.replace('\r\n','\n');if(mutation==='cp')s.original.snapshot.codepoint_length++;if(mutation==='identity')s.identity.name='伪造名称';if(mutation==='original_governance')s.original.governance.review_basis_note+='X';if(mutation==='source_hash')v.content_hash='f'.repeat(64);if(mutation==='signature_parent')q.snapshot.source_content_hash='f'.repeat(64);if(mutation==='signature_hash')q.content_hash='f'.repeat(64);if(mutation==='self_signer')q.snapshot.signed_by=s.created_by;if(mutation==='unknown_published')q.snapshot.catalog_match_review='unknown';if(mutation==='boolean_revision')q.governance.revision=true;if(mutation==='missing')v.missing_evidence=[];if(mutation==='foreign')v.bed_findings={};return p.api.verifyDrugLabelSource(v);},{f,mutation})).toBe(false);
});
test('self rehash of wrong signature source cannot establish a binding',async({page})=>{
 expect(await page.evaluate(async f=>{const p=window.__drugLabelProbe,v=structuredClone(f.states.published.ordinary_current);v.professional_review.snapshot.source_content_hash='f'.repeat(64);v.professional_review.content_hash=await p.supportDigest(v.professional_review.snapshot);v.governance.professional.content_hash=v.professional_review.content_hash;v.governance_hash=await p.supportDigest(v.governance);return p.api.verifyDrugLabelSource(v);},f)).toBe(false);
});
test('audit and current failed qualifications do not become execution eligibility',async({page})=>{
 const values=await page.evaluate(async f=>{const a=window.__drugLabelProbe.api,p=f.states.published;return [await a.verifyDrugLabelSource(p.ordinary_current,{execution:true}),await a.verifyDrugLabelSource(p.super_frozen,{auditOnly:true,execution:true}),await a.verifyDrugLabelSource(p.revoked_super_frozen,{auditOnly:true}),await a.verifyDrugLabelSource(p.revoked_super_frozen,{auditOnly:true,execution:true})];},f);
 expect(values).toEqual([true,false,true,false]);
});
test('unknown professional decisions and exact Unicode bounds are never defaulted',async({page})=>{
 const values=await page.evaluate(f=>{const a=window.__drugLabelProbe.api,v=f.states.unknown_rejected;return[a.drugLabelRequestValid('ProfessionalSign',v.signature_request),a.drugLabelBasis('😀'.repeat(1000),true),a.drugLabelBasis('a'.repeat(1001),true),a.drugLabelBasis(' '.repeat(20)),a.drugLabelRequestValid('ProfessionalSign',{...v.signature_request,signed_by:1}),a.drugLabelSchemaMatches('__proto__',{})];},f);
 expect(values).toEqual([true,true,false,false,false,false]);
});
test('current crypto ticket prevents a result after caller scope changes',async({page})=>{
 expect(await page.evaluate(async f=>{let calls=0;return window.__drugLabelProbe.api.verifyDrugLabelSource(f.states.published.ordinary_current,{current:()=>++calls<3});},f)).toBe(false);
});
test('real request client sends exact native JSON auth through all nine routes',async({page})=>{
 const calls=[];await page.route('**/api/ai/drug-label-sources**',async route=>{const r=route.request();calls.push({path:new URL(r.url()).pathname,method:r.method(),body:r.method()==='POST'?r.postDataJSON():null,token:r.headers().accesstoken,content:r.headers()['content-type']});await route.fulfill({status:200,contentType:'application/json',body:JSON.stringify({code:200,msg:'success',data:{}})});});
 await page.evaluate(async f=>{const a=window.__drugLabelProbe.api,v=f.states.published,id=v.draft_super.snapshot.source_binding_id;await a.getDrugLabelOptions();await a.getDrugLabelCatalog({after_id:0,page_size:20});await a.getDrugLabelSources({pharmaceutical_id:v.create_request.pharmaceutical_id});await a.getDrugLabelSource(id);await a.createDrugLabelSource(v.create_request);await a.signDrugLabelSource(id,v.signature_request);await a.reviewDrugLabelSource(id,v.technical_review_request);await a.revokeDrugLabelSource(id,v.source_revoke_request);await a.revokeDrugLabelProfessional(id,f.states.professional_withdrawn.signature_revoke_request);},f);
 expect(calls).toHaveLength(9);expect(calls.every(v=>v.token==='synthetic-drug-label-session')).toBe(true);for(const call of calls.filter(v=>v.method==='POST'))expect(call.content).toContain('application/json');expect(calls[4].body).toEqual(f.states.published.create_request);expect(calls[5].body).toEqual(f.states.published.signature_request);
});
