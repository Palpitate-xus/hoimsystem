const {test,expect}=require('@playwright/test');
const fixture=require('./fixtures/document-evidence/actual.json');
const {startDocumentEvidenceHarness}=require('./fixtures/document-evidence-harness.cjs');
let harness;
test.beforeAll(async()=>{harness=await startDocumentEvidenceHarness();});
test.afterAll(async()=>{await harness?.close();});
test.beforeEach(async({page})=>{await page.goto(harness.origin);await page.waitForFunction(()=>!!window.__documentProbe);});

test('actual original file and full codepoint/knowledge lineage are verified',async({page})=>{
 const checks=await page.evaluate(async f=>{const a=window.__documentProbe.api;return [await a.verifyDocumentOriginal(f.original_draft),await a.verifyDocumentOriginal(f.original_published),await a.verifyDocumentOriginal(f.original_revoked),await a.verifyDocumentOriginal(f.file_original_draft),await a.verifyDocumentCandidate(f.candidate_draft,f.original_published),await a.verifyDocumentCandidate(f.candidate_approved,f.original_published),await a.verifyDocumentCandidate(f.candidate_stale,f.original_revoked),await a.verifyDocumentPublication(f.publication_active,f.candidate_approved,f.original_published),await a.verifyDocumentPublication(f.publication_stale,f.candidate_stale,f.original_revoked),await a.verifyDocumentPublication(f.publication_revoked,f.candidate_stale,f.original_revoked),a.documentEvidenceOptionsValid(f.options),...Object.entries(f.directories).map(([kind,v])=>a.documentDirectoryValid(kind,v))];},fixture);
 expect(checks).toEqual(Array(14).fill(true));
});

test('actual publication mechanically maps every current knowledge field',async({page})=>{
 expect(await page.evaluate(async f=>{const p=window.__documentProbe;return p.supportCanonical(await p.api.projectDocumentKnowledge(f.publication_active))===p.supportCanonical(f.publication_active.knowledge_current);},fixture)).toBe(true);
});

test('actual publication preserves microseconds and explicitly binds legacy knowledge whole seconds',async({page})=>{
 const values=await page.evaluate(async f=>{const p=window.__documentProbe,a=p.api,s=f.publication_active.snapshot,results=[s.published_at.endsWith('.123456Z'),s.knowledge_recorded_at.endsWith('.000000Z'),s.knowledge_clock_basis==='legacy_utc_second_storage'];for(const mutation of ['stored_microseconds','publication_truncated','basis']){const row=structuredClone(f.publication_active);if(mutation==='stored_microseconds')row.snapshot.knowledge_recorded_at=row.snapshot.published_at;if(mutation==='publication_truncated')row.snapshot.published_at=row.snapshot.knowledge_recorded_at;if(mutation==='basis')row.snapshot.knowledge_clock_basis='assumed_same_precision';row.content_hash=await p.supportDigest(row.snapshot);row.knowledge_current.source_snapshot_hash=row.content_hash;results.push(await a.verifyDocumentPublication(row,f.candidate_approved,f.original_published));}return results;},fixture);
 expect(values).toEqual([true,true,true,false,false,false]);
});

test('declared effective ranges require exact legacy whole seconds without implicit flooring',async({page})=>{
 const values=await page.evaluate(async f=>{const results=[];for(const field of ['effective_from','effective_to']){const body=structuredClone(f.requests.publish);body.knowledge[field]='2026-10-21T12:00:00.000001Z';results.push(await window.__documentProbe.api.documentEvidenceRequestValid('PublishRequest',body));body.knowledge[field]='2026-10-21T12:00:00.000000Z';results.push(await window.__documentProbe.api.documentEvidenceRequestValid('PublishRequest',body));}return results;},fixture);
 expect(values).toEqual([false,true,false,true]);
});

for(const mutation of ['text','raw_hash','codepoint','bad_calendar','wrong_method','privacy','extra','surrogate'])test(`original rejects ${mutation}`,async({page})=>{
 expect(await page.evaluate(async({f,mutation})=>{const p=window.__documentProbe,v=structuredClone(f.original_published);if(mutation==='text')v.snapshot.text=v.snapshot.text.replace('\r\n','\n');if(mutation==='raw_hash')v.snapshot.raw_bytes_hash='f'.repeat(64);if(mutation==='codepoint')v.snapshot.codepoint_length++;if(mutation==='bad_calendar'){v.snapshot.recorded_at='2026-02-30T00:00:00.000000Z';v.snapshot.metadata.source_available_at=null;v.governance.reviewed_at=v.snapshot.recorded_at;v.content_hash=await p.supportDigest(v.snapshot);v.governance_hash=await p.supportDigest(v.governance);v.source_id=`document_original:${v.snapshot.original_id}:${v.content_hash.slice(0,12)}`;}if(mutation==='wrong_method')v.snapshot.filename='not-original.pdf';if(mutation==='privacy')v.governance.privacy_review='unknown';if(mutation==='extra')v.patient_name='unknown-private';if(mutation==='surrogate')v.snapshot.text='\ud800';return p.api.verifyDocumentOriginal(v);},{f:fixture,mutation})).toBe(false);
});

for(const mutation of ['utf16','false_zero','quote','parent','parent_governance'])test(`candidate rejects ${mutation}`,async({page})=>{
 expect(await page.evaluate(async({f,mutation})=>{const p=window.__documentProbe,v=structuredClone(f.candidate_approved),s=v.snapshot.proposal;if(mutation==='utf16')s.end++;if(mutation==='false_zero')s.start=false;if(mutation==='quote')s.quote=s.quote.replace('😀','X');if(mutation==='parent')s.original.original_id='00000000-0000-0000-0000-000000000099';if(mutation==='parent_governance')s.original.governance_hash='f'.repeat(64);v.content_hash=await p.supportDigest(v.snapshot);v.source_id=`document_candidate:${v.snapshot.candidate_id}:${v.content_hash.slice(0,12)}`;return p.api.verifyDocumentCandidate(v,f.original_published);},{f:fixture,mutation})).toBe(false);
});

test('a current knowledge change requires exact ineligibility instead of eligible true',async({page})=>{
 const value=await page.evaluate(async f=>{const p=window.__documentProbe,v=structuredClone(f.publication_active);v.knowledge_current.title='实际修改标题';const bad=await p.api.verifyDocumentPublication(v,f.candidate_approved,f.original_published);v.eligible=false;v.ineligibility_reasons=['knowledge_changed'];return [bad,await p.api.verifyDocumentPublication(v,f.candidate_approved,f.original_published)];},fixture);
 expect(value).toEqual([false,true]);
});

test('all actual request types plus review/publication/revoke transitions bind original CAS',async({page})=>{
 const result=await page.evaluate(async f=>{const a=window.__documentProbe.api,models={direct_ui_create:'OriginalCreate',original_create:'OriginalCreate',file_create:'OriginalCreate',original_review:'ReviewRequest',candidate_create:'CandidateCreate',candidate_review:'ReviewRequest',publish:'PublishRequest',original_revoke:'RevokeRequest',publication_revoke:'RevokeRequest'},valid=await Promise.all(Object.entries(f.requests).map(([key,v])=>a.documentEvidenceRequestValid(models[key],v)));valid.push(await a.verifyDocumentCreatedOriginal(f.original_draft,f.requests.original_create),await a.verifyDocumentCreatedOriginal(f.file_original_draft,f.requests.file_create),await a.verifyDocumentTransition('originals',f.original_published,f.original_draft,'review',f.requests.original_review),await a.verifyDocumentTransition('candidates',f.candidate_approved,f.candidate_draft,'review',f.requests.candidate_review,{original:f.original_published}),await a.verifyDocumentTransition('candidates',f.publication_active,f.candidate_approved,'publish',f.requests.publish,{original:f.original_published}),await a.verifyDocumentTransition('originals',f.original_revoked,f.original_published,'revoke',f.requests.original_revoke),await a.verifyDocumentTransition('publications',f.publication_revoked,f.publication_stale,'revoke',f.requests.publication_revoke,{original:f.original_revoked,candidate:f.candidate_stale}));return valid;},fixture);
 expect(result.every(Boolean)).toBe(true);
});

test('actual file bytes preserve BOM CRLF emoji and combining sequences',async({page})=>{
 const result=await page.evaluate(async f=>{const a=window.__documentProbe.api,s=f.original_published.snapshot.text,value=await a.readDocumentFile(new File([new TextEncoder().encode(s)],'合成原文.md'));return [value.expected_bytes_hash===f.requests.file_create.content.expected_bytes_hash,value.bytes_base64===f.requests.file_create.content.bytes_base64,a.documentCodepointSlice(s,9,12)==='😀e\u0301'];},fixture);
 expect(result).toEqual([true,true,true]);
});

test('unknown schema prototype boolean clock and unsupported files fail closed',async({page})=>{
 const result=await page.evaluate(async f=>{const a=window.__documentProbe.api;let rejected=false;try{await a.readDocumentFile(new File([new Uint8Array([255])],'source.txt'));}catch{rejected=true;}return [a.documentSchemaMatches('constructor',f.original_draft),a.documentSchemaMatches('__proto__',{}),a.documentSchemaMatches('OriginalRecord',JSON.parse('{"__proto__":{}}')),a.documentClock(false),a.documentClock('2026-02-30T12:00:00.000000Z'),rejected];},fixture);
 expect(result).toEqual([false,false,false,false,false,true]);
});
