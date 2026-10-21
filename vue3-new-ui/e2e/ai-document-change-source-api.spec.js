const {test,expect}=require('@playwright/test');
const fixture=require('./fixtures/document-change-source/actual.json');
const {startDocumentChangeSourceHarness}=require('./fixtures/document-change-source-harness.cjs');
let harness;test.beforeAll(async()=>{harness=await startDocumentChangeSourceHarness();});test.afterAll(async()=>{await harness?.close();});
async function open(page){await page.goto(harness.origin);await page.waitForFunction(()=>!!window.__documentChangeSourceProbe);}
test('actual JWT Source lifecycle retains draft, published, stale and revoked whole captures',async({page})=>{
 await open(page);const checks=await page.evaluate(async f=>{const a=window.__documentChangeSourceProbe.api,r=f.responses,out={};for(const name of ['scope_draft','scope_published','scope_detail','scope_stale','scope_revoked'])out[name]=await a.verifyDocumentChangeScope(r[name].data);out.options=a.documentChangeOptionsValid(r.options.data);out.scopes=a.documentChangeDirectoryValid('scopes',r.scope_directory.data);out.links=a.documentChangeDirectoryValid('links',r.link_directory.data);out.capture=await a.verifyDocumentChangeCapture(r.capture.data,f.requests.capture);return out;},fixture);
 expect(Object.values(checks)).toEqual(Array(9).fill(true));
});
test('actual full private Scope projects every public field and retains outside and unreviewed dependencies',async({page})=>{
 await open(page);const checks=await page.evaluate(async f=>{const p=window.__documentChangeSourceProbe,a=p.api,r=f.responses,s=r.scope_published.data,pub=r.public_source.data;return [p.supportCanonical(await a.projectDocumentChangeScope(s))===p.supportCanonical(pub),await a.verifyDocumentChangeSource(pub,{scope:s}),pub.targets.some(t=>t.within_declared_scope===false),pub.rule_links.some(l=>l.current===false),pub.publications.length===1,!JSON.stringify(pub).includes('私有路径不外发'),!JSON.stringify(pub).includes('私有目标标题禁止外发')];},fixture);
 expect(checks).toEqual(Array(7).fill(true));
});
test('actual links bind original CP text, full raw target and all governance states',async({page})=>{
 await open(page);const result=await page.evaluate(async f=>{const a=window.__documentChangeSourceProbe.api,r=f.responses,out=[];for(const name of ['link_draft','link_published','link_detail','link_revoked'])out.push(await a.verifyDocumentChangeLink(r[name].data,{original:r.baseline_original.data,target:r.target_snapshot.data.snapshot}));out.push(a.documentChangeTargetValid(r.target_snapshot.data.snapshot),a.documentChangeTargetValid(r.outside_target.data.snapshot));return out;},fixture);expect(result).toEqual(Array(6).fill(true));
});
for(const mutation of ['wrong_side_reference','duplicate_target','raw_clock','unknown_property','false_boolean','raw_original_text','link_quote','link_target','publication_body','lost_loser'])test(`private capture refuses ${mutation} even when attacker recomputes outer hashes`,async({page})=>{
 await open(page);expect(await page.evaluate(async({f,mutation})=>{const p=window.__documentChangeSourceProbe,a=p.api,v=structuredClone(f.responses.scope_published.data),s=v.snapshot,i=s.inventory;
 if(mutation==='wrong_side_reference')s.request.baseline_original.governance_hash='f'.repeat(64);
 if(mutation==='duplicate_target'){i.targets.push(structuredClone(i.targets[0]));i.member_count++;}
 if(mutation==='raw_clock')s.recorded_at='2026-02-30T12:00:00.123456Z';
 if(mutation==='unknown_property')s.patient_name='unexpected-private-field';
 if(mutation==='false_boolean')v.automatic_supersession=0;
 if(mutation==='raw_original_text')i.baseline_original.snapshot.text+='未绑定的追加';
 if(mutation==='link_quote'){const l=i.rule_links[0];l.snapshot.proposal.span.quote+='改';l.content_hash=await p.supportDigest(l.snapshot);}
 if(mutation==='link_target'){const l=i.rule_links[0];l.snapshot.target_snapshot.columns.steps='{"changed":true}';l.content_hash=await p.supportDigest(l.snapshot);}
 if(mutation==='publication_body')i.publications[0].publication.knowledge_current.content+='已修改';
 if(mutation==='lost_loser'){i.rule_links.pop();i.member_count--;}
 s.inventory_hash=await p.supportDigest(i);v.content_hash=await p.supportDigest(s);
 return mutation==='lost_loser'?a.documentChangeMetadataMatches('scopes',v,f.responses.scope_directory.data.items[0]):await a.verifyDocumentChangeScope(v);
 },{f:fixture,mutation})).toBe(false);
});
for(const mutation of ['omit_link','omit_publication','private_target','change_text','quote_hash','boolean_count'])test(`publicSource refuses ${mutation} against full actual Scope`,async({page})=>{
 await open(page);expect(await page.evaluate(async({f,mutation})=>{const a=window.__documentChangeSourceProbe.api,v=structuredClone(f.responses.public_source.data);if(mutation==='omit_link'){v.rule_links.pop();v.member_count--;}if(mutation==='omit_publication'){v.publications.pop();v.member_count-=3;}if(mutation==='private_target')v.targets[0].raw_rules='unexpected body';if(mutation==='change_text')v.baseline.text+='改';if(mutation==='quote_hash')v.rule_links[0].quote_bytes_hash='f'.repeat(64);if(mutation==='boolean_count')v.member_count=true;return a.verifyDocumentChangeSource(v,{scope:f.responses.scope_published.data});},{f:fixture,mutation})).toBe(false);
});
test('every actual request is typed and caller cannot claim automatic hospital-wide scope or null target identity',async({page})=>{
 await open(page);const result=await page.evaluate(async f=>{const a=window.__documentChangeSourceProbe.api,out=[];for(const [key,model]of [['capture','ScopeCaptureRequest'],['scope_draft','ScopeCreate'],['link_draft','LinkCreate'],['link_published','ReviewRequest'],['scope_published','ReviewRequest'],['scope_revoked','RevokeRequest'],['target_snapshot','TargetReference']])out.push(await a.documentChangeRequestValid(model,f.requests[key]));for(const v of [{...f.requests.capture,hospital_wide_rule_inventory:'complete'},{...f.requests.capture,baseline_original:f.requests.capture.candidate_original},{...f.requests.capture,declaration_basis_note:'\u0085\u001c '.repeat(30)}])out.push(await a.documentChangeRequestValid('ScopeCaptureRequest',v));out.push(await a.documentChangeRequestValid('TargetReference',{kind:'clinical_pathway',target_id:null}));return out;},fixture);expect(result).toEqual([...Array(7).fill(true),false,false,false,false]);
});
test('directory binds hashes and complete page metadata before selecting a fresh whole record',async({page})=>{
 await open(page);const result=await page.evaluate(f=>{const a=window.__documentChangeSourceProbe.api,dir=f.responses.scope_directory.data,row=dir.items[0],s=f.responses.scope_published.data;return [a.documentChangeMetadataMatches('scopes',s,row),a.documentChangeMetadataMatches('scopes',{...s,content_hash:'f'.repeat(64)},row),a.documentChangeDirectoryValid('scopes',{...dir,total:dir.total+1}),a.documentChangeDirectoryValid('scopes',{...dir,page:true}),a.documentChangeDirectoryValid('scopes',{...dir,items:[{...row,detail_required:1}]})];},fixture);expect(result).toEqual([true,false,false,false,false]);
});

test('real request client sends only exact typed bodies and closed directory filters',async({page})=>{
 const calls=[];await page.route('**/api/**',async route=>{const r=route.request(),u=new URL(r.url());calls.push({method:r.method(),path:u.pathname,query:Object.fromEntries(u.searchParams),raw:r.postData()});await route.fulfill({json:fixture.responses.options});});await open(page);
 const result=await page.evaluate(async f=>{const a=window.__documentChangeSourceProbe.api,id=f.responses.scope_published.data.snapshot.scope_id;await a.getDocumentChangeOptions();await a.getDocumentChangeScopes({page:1,page_size:20,original_id:f.responses.baseline_original.data.snapshot.original_id});await a.captureDocumentChangeScope(f.requests.capture);await a.createDocumentChangeLink(f.requests.link_draft);await a.getDocumentChangeScope(id);await a.getDocumentChangePublicSource(id);let refused=0;for(const fn of [()=>a.getDocumentChangeScopes({page:true}),()=>a.getDocumentChangeScopes({patient_id:1}),()=>a.getDocumentChangeScope('../invalid'),()=>a.getDocumentChangeTarget({kind:'clinical_pathway',target_id:null})])try{await fn();}catch{refused++;}return refused;},fixture);
 expect(result).toBe(4);expect(calls.map(c=>c.method)).toEqual(['GET','GET','POST','POST','GET','GET']);expect(calls[1].query).toEqual({page:'1',page_size:'20',original_id:fixture.responses.baseline_original.data.snapshot.original_id});expect(calls[2].raw).toBe(JSON.stringify(fixture.requests.capture));expect(calls[3].raw).toBe(JSON.stringify(fixture.requests.link_draft));
});
test('an actual 409 CAS conflict is not automatically posted again',async({page})=>{
 let calls=0;await page.route('**/api/**',async route=>{calls++;await route.fulfill({status:409,json:{code:409,msg:'合成CAS已变化'}});});await open(page);expect(await page.evaluate(async f=>{try{await window.__documentChangeSourceProbe.api.createDocumentChangeScope(f.requests.scope_draft);return false;}catch{return true;}},fixture)).toBe(true);expect(calls).toBe(1);
});
