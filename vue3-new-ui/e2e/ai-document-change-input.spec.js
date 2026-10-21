const {test,expect}=require('@playwright/test'),fixture=require('./fixtures/document-change-source/actual.json'),{startDocumentChangeInputHarness}=require('./fixtures/document-change-input-harness.cjs');
let harness;test.beforeAll(async()=>{harness=await startDocumentChangeInputHarness();});test.afterAll(async()=>{await harness?.close();});
async function setup(page,config={}){
 const calls=[],errors=[],held={},completed=[],r=fixture.responses,scopeId=r.scope_published.data.snapshot.scope_id;
 page.on('pageerror',e=>errors.push(e.message));await page.context().route('**/*',route=>new URL(route.request().url()).origin===harness.origin?route.continue():route.abort());
 await page.route('**/api/**',async route=>{const req=route.request(),url=new URL(req.url()),path=url.pathname;calls.push({path,method:req.method(),query:Object.fromEntries(url.searchParams)});let response;
  if(path==='/api/ai/admin/document-changes/scopes')response={...r.scope_directory,data:config.directory||r.scope_directory.data};
  else if(path==='/api/ai/admin/document-changes/scopes/'+scopeId)response={...r.scope_detail,data:config.scope||r.scope_detail.data};
  else if(path==='/api/ai/admin/document-changes/scopes/'+scopeId+'/public-source')response={...r.public_source,data:config.publicSource||r.public_source.data};
  else{errors.push('Unhandled isolated '+path);await route.fulfill({status:599,json:{code:599,msg:'Missing synthetic route'}});return;}
  const key=config.hold?.(path);if(key)await new Promise(resolve=>held[key]=resolve);try{await route.fulfill({json:response});}finally{if(key)completed.push(key);}
 });
 await page.addInitScript(v=>window.__documentChangeInputInitial=v,config.initial||{});await page.goto(harness.origin);await page.waitForFunction(()=>!!window.__documentChangeInputProbe);return {calls,errors,held,completed,scopeId};
}
async function choose(page){await page.getByRole('button',{name:'读取完整件并选择',exact:true}).click();}
async function accepted(page){await expect(page.getByLabel('已核对完整双原文范围',{exact:true})).toBeVisible();}
async function selection(page){return page.evaluate(()=>window.__documentChangeInputProbe.scope.selection);}
async function empty(page){await expect(page.getByLabel('已核对完整双原文范围',{exact:true})).toHaveCount(0);expect(await selection(page)).toBeNull();}
test('explicitly chosen actual published Scope verifies private/public whole objects before emitting only the ID reference',async({page})=>{
 const s=await setup(page);await expect(page.getByRole('button',{name:'读取完整件并选择',exact:true})).toBeVisible();expect(await selection(page)).toBeNull();expect(s.calls).toHaveLength(1);await choose(page);await accepted(page);
 const value=await selection(page);expect(value.references).toEqual({document_change_scope_id:s.scopeId});expect(value.scope).toEqual(fixture.responses.scope_published.data);expect(value.publicSource).toEqual(fixture.responses.public_source.data);expect(s.calls.map(c=>c.method)).toEqual(['GET','GET','GET']);expect(s.errors).toEqual([]);
 await page.getByRole('button',{name:'清除所选范围',exact:true}).click();await empty(page);
});
test('an explicit initial Scope reference loads the actual full record and exact public projection',async({page})=>{
 const s=await setup(page,{initial:{references:{document_change_scope_id:fixture.responses.scope_published.data.snapshot.scope_id}}});await accepted(page);expect((await selection(page)).references.document_change_scope_id).toBe(s.scopeId);expect(s.errors).toEqual([]);
});
for(const roles of [[],['admin'],'super_admin',null])test(`source selection requires actual Super roles array ${JSON.stringify(roles)}`,async({page})=>{
 const s=await setup(page,{initial:{roles}});await expect(page.getByText('仅当前超级管理员可以读取和选择完整原文范围',{exact:true})).toBeVisible();expect(s.calls).toEqual([]);expect(await selection(page)).toBeNull();expect(s.errors).toEqual([]);
});
for(const references of [{document_change_scope_id:null},{patient_id:1},{document_change_scope_id:fixture.responses.scope_published.data.snapshot.scope_id,question:'不应进入引用'}])test(`invalid reference ${JSON.stringify(references)} makes zero Source requests`,async({page})=>{
 const s=await setup(page,{initial:{references}});await expect(page.getByText('比较范围引用须仅含规范的 document_change_scope_id，不接受患者、就诊或其它输入',{exact:true})).toBeVisible();expect(s.calls).toEqual([]);expect(await selection(page)).toBeNull();
});
for(const change of ['token','username','roles','active','deactivate','unmount'])test(`accepted private Scope immediately clears after ${change}`,async({page})=>{
 await setup(page);await choose(page);await accepted(page);await page.evaluate(change=>{const p=window.__documentChangeInputProbe;if(change==='token'||change==='username')p.store.commit('user/'+change,'new-session');else if(change==='roles')p.store.commit('user/permissions',['doctor']);else if(change==='active')p.scope.active=false;else if(change==='deactivate')p.scope.mounted=false;else p.scope.destroyed=true;},change);await empty(page);
});
for(const phase of ['detail','public'])test(`held ${phase} response cannot restore the old private selection after token change`,async({page})=>{
 const s=await setup(page,{hold:path=>phase==='public'?path.endsWith('/public-source')?'response':null:path.endsWith('/'+fixture.responses.scope_published.data.snapshot.scope_id)?'response':null});await choose(page);await expect.poll(()=>!!s.held.response).toBe(true);await page.evaluate(()=>window.__documentChangeInputProbe.store.commit('user/token','different-session'));s.held.response();await expect.poll(()=>s.completed.includes('response')).toBe(true);await empty(page);expect(s.errors).toEqual([]);
});
test('a real WebCrypto completion after close cannot restore original text or emitted selection',async({page})=>{
 await setup(page);await page.evaluate(()=>{const p=window.__documentChangeInputProbe,real=crypto.subtle.digest.bind(crypto.subtle);p.started=false;p.release=null;crypto.subtle.digest=async(...args)=>{if(!p.started){p.started=true;await new Promise(resolve=>p.release=resolve);}return real(...args);};});await choose(page);await expect.poll(()=>page.evaluate(()=>window.__documentChangeInputProbe.started)).toBe(true);await page.evaluate(()=>{const p=window.__documentChangeInputProbe;p.scope.active=false;p.release();});await empty(page);
});
test('initial old reference is not automatically reselected after identity changes',async({page})=>{
 const s=await setup(page,{initial:{references:{document_change_scope_id:fixture.responses.scope_published.data.snapshot.scope_id}}});await accepted(page);await page.evaluate(()=>window.__documentChangeInputProbe.store.commit('user/token','new-token'));await empty(page);await expect.poll(()=>s.calls.filter(c=>c.path.endsWith('/scopes')).length).toBe(2);expect(s.calls.filter(c=>c.path.endsWith('/public-source'))).toHaveLength(1);
});
test('initially inactive or unauthenticated selection does not revive an old initial reference on later authentication',async({page})=>{
 const s=await setup(page,{initial:{token:'',references:{document_change_scope_id:fixture.responses.scope_published.data.snapshot.scope_id}}});expect(s.calls).toEqual([]);await page.evaluate(()=>window.__documentChangeInputProbe.store.commit('user/token','fresh-session'));await expect(page.getByRole('button',{name:'读取完整件并选择',exact:true})).toBeVisible();await empty(page);expect(s.calls).toHaveLength(1);
});
for(const mutation of ['stale','foreign_id','metadata','public_projection'])test(`selection rejects ${mutation} full response without emitting a ready reference`,async({page})=>{
 const config={};if(mutation==='stale')config.scope=fixture.responses.scope_stale.data;
 if(mutation==='foreign_id'){config.scope=structuredClone(fixture.responses.scope_detail.data);config.scope.snapshot.scope_id=fixture.responses.baseline_original.data.snapshot.original_id;}
 if(mutation==='metadata'){config.directory=structuredClone(fixture.responses.scope_directory.data);config.directory.items[0].content_hash='f'.repeat(64);}
 if(mutation==='public_projection'){config.publicSource=structuredClone(fixture.responses.public_source.data);config.publicSource.rule_links.pop();config.publicSource.member_count--;}
 const s=await setup(page,config);await choose(page);await expect(page.getByText('当前完整原文、关联、目标集合或审核状态无法核对，请重新选择',{exact:true})).toBeVisible();await empty(page);expect(s.errors).toEqual([]);
});
