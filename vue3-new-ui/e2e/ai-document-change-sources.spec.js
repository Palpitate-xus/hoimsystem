const {test,expect}=require('@playwright/test'),fixture=require('./fixtures/document-change-source/panel-actual.json'),{startDocumentChangeSourceHarness}=require('./fixtures/document-change-source-harness.cjs');
let harness;test.beforeAll(async()=>{harness=await startDocumentChangeSourceHarness({findings:true});});test.afterAll(async()=>{await harness?.close();});
async function setup(page,config={}){
 const r=fixture.responses,calls=[],errors=[],held={},completed=[],state={scope:config.empty?'empty':config.draft?'draft':'published',link:config.empty?'empty':'published'};
 page.on('pageerror',e=>errors.push(e.message));await page.context().route('**/*',route=>new URL(route.request().url()).origin===harness.origin?route.continue():route.abort());
 await page.route('**/api/**',async route=>{
  const req=route.request(),u=new URL(req.url()),path=u.pathname,body=req.postData()?JSON.parse(req.postData()):null;calls.push({path,method:req.method(),body,query:Object.fromEntries(u.searchParams)});let response;
  const base='/api/ai/admin/document-changes';
  if(path===base+'/options')response=r.options;
  else if(path==='/api/ai/admin/document-evidence/originals')response=r.originals;
  else if(path==='/api/ai/admin/document-evidence/originals/'+r.baseline_original.data.snapshot.original_id)response=r.baseline_original;
  else if(path==='/api/ai/admin/document-evidence/originals/'+r.candidate_original.data.snapshot.original_id)response=r.candidate_original;
  else if(path===base+'/target-snapshot')response=body.target_id===r.target_snapshot.data.snapshot.target.target_id?r.target_snapshot:r.outside_target;
  else if(path===base+'/links'&&req.method()==='GET')response=state.link==='empty'?r.initial_link_directory:state.link==='draft'?r.draft_link_directory:r.link_directory;
  else if(path===base+'/scopes'&&req.method()==='GET')response=state.scope==='empty'?r.initial_scope_directory:state.scope==='draft'?r.draft_scope_directory:state.scope==='revoked'?r.revoked_scope_directory:r.scope_directory;
  else if(path===base+'/links'&&req.method()==='POST'){state.link='draft';response=r.link_draft;}
  else if(path===base+'/capture')response=r.capture;
  else if(path===base+'/scopes'&&req.method()==='POST'){state.scope='draft';response=r.scope_draft;}
  else if(path===base+'/scopes/'+r.scope_published.data.snapshot.scope_id)response=config.badScope|| (state.scope==='draft'?r.scope_draft:state.scope==='revoked'?r.scope_revoked:r.scope_detail);
  else if(path===base+'/links/'+r.link_published.data.snapshot.link_id)response=state.link==='draft'?r.link_draft:r.link_detail;
  else if(path===base+'/scopes/'+r.scope_published.data.snapshot.scope_id+'/review'){state.scope='published';response=r.scope_published;}
  else if(path===base+'/scopes/'+r.scope_published.data.snapshot.scope_id+'/revoke'){state.scope='revoked';response=r.scope_revoked;}
  else if(path===base+'/links/'+r.link_published.data.snapshot.link_id+'/review'){state.link='published';response=r.link_published;}
  else if(path===base+'/links/'+r.link_published.data.snapshot.link_id+'/revoke'){state.link='revoked';response=r.link_revoked;}
  else{errors.push('Unhandled isolated '+req.method()+' '+path);await route.fulfill({status:599,json:{code:599,msg:'Missing explicit actual synthetic response'}});return;}
  const key=config.hold?.(path,req.method());if(key)await new Promise(resolve=>held[key]=resolve);
  try{if(config.failure?.(path,req.method()))await route.fulfill({status:409,json:{code:409,msg:'合成当前集合或CAS已改变'}});else await route.fulfill({json:response});}finally{if(key)completed.push(key);}
 });
 await page.addInitScript(value=>window.__documentChangeSourceInitial=value,config.initial||{});await page.goto(harness.origin);await page.waitForFunction(()=>!!window.__documentChangeSourceProbe);
 if(config.role!==undefined)await page.evaluate(role=>window.__documentChangeSourceProbe.store.commit('user/permissions',role),config.role);
 await expect.poll(()=>page.evaluate(()=>!!window.__documentChangeSourceProbe.scope.target)).toBe(true);
 return {r,calls,errors,held,completed,state};
}
async function combo(page,label,option){const input=page.getByRole('combobox',{name:label,exact:true});await page.locator('.el-select').filter({has:input}).click();const controls=await input.getAttribute('aria-controls');expect(controls).toBeTruthy();await page.locator(`[id="${controls}"]`).getByRole('option',{name:option,exact:true}).click();}
async function readScope(page){await page.getByLabel('有限范围目录',{exact:true}).getByRole('button',{name:'读取完整件与治理',exact:true}).click();await expect(page.getByLabel('完整来源与显式治理',{exact:true})).toBeVisible();}
async function selectPair(page){
 for(const [label,key]of [['基线原文','baseline_original'],['候选原文','candidate_original']]){const id=fixture.responses[key].data.snapshot.original_id,group=page.getByLabel(label,{exact:true});await group.locator('tr').filter({hasText:id}).getByRole('button',{name:'选择并核对完整原件',exact:true}).click();await expect(group.getByRole('status')).toBeVisible();}
}
async function target(page){await combo(page,'目标种类','临床路径');await page.getByLabel('真实目标标识',{exact:true}).fill(String(fixture.responses.target_snapshot.data.snapshot.target.target_id));await page.getByRole('button',{name:'读取完整当前目标',exact:true}).click();await expect(page.getByLabel('已核对当前目标',{exact:true})).toBeVisible();}
async function scopeForm(page){await selectPair(page);await target(page);await page.getByRole('button',{name:'明确加入本次有限范围',exact:true}).click();await combo(page,'两原文关系声明','只做比较，不声明替代');await page.getByLabel('原文关系依据',{exact:true}).fill(fixture.requests.capture.relationship.basis_note);await page.getByLabel('有限范围依据',{exact:true}).fill(fixture.requests.capture.declaration_basis_note);}
async function cleared(page){await expect(page.getByLabel('完整来源与显式治理',{exact:true})).toHaveCount(0);await expect(page.getByLabel('完整私有比较来源',{exact:true})).toHaveCount(0);}
test('actual complete paired sources capture all dependencies then explicitly register, review and revoke the finite Scope',async({page})=>{
 const s=await setup(page,{empty:true});await scopeForm(page);await page.getByRole('button',{name:'捕获全部依赖供人工核对',exact:true}).click();await expect(page.getByLabel('待登记完整比较捕获',{exact:true})).toContainText(String(s.r.capture.data.member_count));await page.getByRole('button',{name:'按此完整摘要登记范围草稿',exact:true}).click();await expect(page.getByLabel('完整来源与显式治理',{exact:true})).toContainText('待审核');
 await combo(page,'审核决定','明确批准发布本次声明');for(const label of ['隐私审核','原意审核','依赖与声明核对'])await combo(page,label,'明确确认');await page.getByLabel('本次审核依据',{exact:true}).fill(fixture.requests.scope_published.basis_note);await page.getByRole('button',{name:'仅保存本次明确审核',exact:true}).click();await expect(page.getByLabel('完整来源与显式治理',{exact:true})).toContainText('已审核发布');
 await page.getByLabel('明确撤销依据',{exact:true}).fill(fixture.requests.scope_revoked.basis_note);await page.getByRole('button',{name:'明确撤销当前原件',exact:true}).click();await expect(page.getByLabel('完整来源与显式治理',{exact:true})).toContainText('已撤销');
 expect(s.calls.find(c=>c.path.endsWith('/capture')).body).toEqual(fixture.requests.capture);expect(s.calls.find(c=>c.method==='POST'&&c.path.endsWith('/scopes')).body).toEqual(fixture.requests.scope_draft);expect(s.calls.find(c=>c.path.endsWith('/review')).body).toEqual(fixture.requests.scope_published);expect(s.calls.filter(c=>c.path.includes('/runs')||c.path.includes('/knowledge'))).toEqual([]);expect(s.errors).toEqual([]);
});
test('literal CP link is an unverified draft and never auto-published',async({page})=>{
 const s=await setup(page,{empty:true});await selectPair(page);await target(page);await combo(page,'关联原文侧','基线原文');await page.getByLabel('关联起点',{exact:true}).fill(String(fixture.requests.link_draft.span.start));await page.getByLabel('关联终点',{exact:true}).fill(String(fixture.requests.link_draft.span.end));await combo(page,'声明的关联关系','声明实施');await page.getByLabel('关联声明依据',{exact:true}).fill(fixture.requests.link_draft.basis_note);await expect(page.getByLabel('逐字关联引文',{exact:true})).toHaveText(fixture.requests.link_draft.span.quote);await page.getByRole('button',{name:'仅登记关联草稿',exact:true}).click();await expect(page.getByLabel('完整来源与显式治理',{exact:true})).toContainText('待审核');expect(s.calls.find(c=>c.method==='POST'&&c.path.endsWith('/links')).body).toEqual(fixture.requests.link_draft);expect(s.calls.filter(c=>c.path.endsWith('/review'))).toEqual([]);expect(s.errors).toEqual([]);
});
test('full published private record is displayed only after complete proof and explicitly closed',async({page})=>{
 const s=await setup(page);await readScope(page);await page.getByRole('button',{name:'展开完整私有原件',exact:true}).click();expect(JSON.parse(await page.getByLabel('完整私有比较来源',{exact:true}).textContent()).snapshot.inventory.baseline_original.snapshot.text).toBe(s.r.scope_published.data.snapshot.inventory.baseline_original.snapshot.text);await page.getByRole('button',{name:'关闭并清除当前治理详情',exact:true}).click();await cleared(page);expect(s.errors).toEqual([]);
});
test('approve without explicit three decisions causes zero review writes',async({page})=>{
 const s=await setup(page,{draft:true});await readScope(page);await combo(page,'审核决定','明确批准发布本次声明');await page.getByLabel('本次审核依据',{exact:true}).fill(fixture.requests.scope_published.basis_note);await page.getByRole('button',{name:'仅保存本次明确审核',exact:true}).click();await expect(page.getByRole('alert').filter({hasText:'未自动重发'})).toBeVisible();expect(s.calls.filter(c=>c.path.endsWith('/review'))).toEqual([]);
});
for(const change of ['token','username','roles','active','deactivate','unmount'])test(`governance private original and notes clear immediately on ${change}`,async({page})=>{
 await setup(page);await readScope(page);await page.getByRole('button',{name:'展开完整私有原件',exact:true}).click();await page.evaluate(change=>{const p=window.__documentChangeSourceProbe;if(change==='token'||change==='username')p.store.commit('user/'+change,'new-session');else if(change==='roles')p.store.commit('user/permissions',['doctor']);else if(change==='active')p.scope.active=false;else if(change==='deactivate')p.scope.mounted=false;else p.scope.destroyed=true;},change);await cleared(page);
});
for(const phase of ['detail','capture'])test(`late ${phase} response is discarded after permissions change`,async({page})=>{
 const s=await setup(page,{hold:(path,method)=>phase==='capture'?path.endsWith('/capture')?'held':null:path.endsWith('/'+fixture.responses.scope_published.data.snapshot.scope_id)&&method==='GET'?'held':null});
 if(phase==='capture'){await scopeForm(page);await page.getByRole('button',{name:'捕获全部依赖供人工核对',exact:true}).click();}else await page.getByLabel('有限范围目录',{exact:true}).getByRole('button',{name:'读取完整件与治理',exact:true}).click();
 await expect.poll(()=>!!s.held.held).toBe(true);await page.evaluate(()=>window.__documentChangeSourceProbe.store.commit('user/permissions',['admin']));s.held.held();await expect.poll(()=>s.completed.includes('held')).toBe(true);await cleared(page);await expect(page.getByLabel('待登记完整比较捕获',{exact:true})).toHaveCount(0);expect(s.errors).toEqual([]);
});
test('changed whole capture CAS returns409 once and never automatically registers again',async({page})=>{
 const s=await setup(page,{empty:true,failure:(path,method)=>path.endsWith('/scopes')&&method==='POST'});await scopeForm(page);await page.getByRole('button',{name:'捕获全部依赖供人工核对',exact:true}).click();await expect(page.getByLabel('待登记完整比较捕获',{exact:true})).toBeVisible();await page.getByRole('button',{name:'按此完整摘要登记范围草稿',exact:true}).click();await expect(page.getByRole('alert').filter({hasText:'未自动重发'})).toBeVisible();expect(s.calls.filter(c=>c.method==='POST'&&c.path.endsWith('/scopes'))).toHaveLength(1);await cleared(page);
});
test('same Original on both sides cannot capture a comparison Scope',async({page})=>{
 const s=await setup(page);for(const label of ['基线原文','候选原文'])await page.getByLabel(label,{exact:true}).locator('tr').filter({hasText:s.r.baseline_original.data.snapshot.original_id}).getByRole('button',{name:'选择并核对完整原件',exact:true}).click();await expect(page.getByText('必须明确选择两件不同的原文，不能将同一原件作为两侧',{exact:true})).toBeVisible();await expect(page.getByRole('button',{name:'捕获全部依赖供人工核对',exact:true})).toBeDisabled();expect(s.calls.filter(c=>c.path.endsWith('/capture'))).toEqual([]);
});
test('bad complete record with self-changed hash cannot become a governance detail',async({page})=>{
 const corrupt=structuredClone(fixture.responses.scope_detail);corrupt.data.snapshot.inventory.baseline_original.snapshot.text+='NOT_BOUND';const s=await setup(page,{badScope:corrupt});await page.getByLabel('有限范围目录',{exact:true}).getByRole('button',{name:'读取完整件与治理',exact:true}).click();await expect(page.getByRole('alert').filter({hasText:'无法核对'})).toBeVisible();await cleared(page);expect(s.errors).toEqual([]);
});

for(const roles of [[],['admin'],'super_admin',null])test(`governance requires actual Super array ${JSON.stringify(roles)} before every Source request`,async({page})=>{
 const s=await setup(page,{initial:{roles}});await expect(page.getByText('仅当前超级管理员可以读取和治理这些完整原件',{exact:true})).toBeVisible();expect(s.calls).toEqual([]);expect(s.errors).toEqual([]);
});
test('empty token makes zero source or directory requests',async({page})=>{
 const s=await setup(page,{initial:{token:''}});await expect(page.getByText('仅当前超级管理员可以读取和治理这些完整原件',{exact:true})).toBeVisible();expect(s.calls).toEqual([]);
});
test('actual WebCrypto close discards the late whole-private proof',async({page})=>{
 await setup(page);await page.evaluate(()=>{const p=window.__documentChangeSourceProbe,original=crypto.subtle.digest.bind(crypto.subtle);p.started=false;p.release=null;crypto.subtle.digest=async(...args)=>{if(!p.started){p.started=true;await new Promise(resolve=>p.release=resolve);}return original(...args);};});await page.getByLabel('有限范围目录',{exact:true}).getByRole('button',{name:'读取完整件与治理',exact:true}).click();await expect.poll(()=>page.evaluate(()=>window.__documentChangeSourceProbe.started)).toBe(true);await page.evaluate(()=>{const p=window.__documentChangeSourceProbe;p.scope.active=false;p.release();});await cleared(page);
});
