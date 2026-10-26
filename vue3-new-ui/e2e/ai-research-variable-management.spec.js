const { expectManagementEntry, selectManagementTab } = require('./fixtures/ai-management-navigation.cjs');
const{test,expect}=require('@playwright/test');
const{startResearchVariableManagementHarness}=require('./fixtures/research-variable-management-harness.cjs');
const{loadResearchVariableSource}=require('./fixtures/research-variable-source-ui.cjs');
const F=loadResearchVariableSource(),dictionaryId=F.data('dictionary.published.metadata').record_id;let harness;test.beforeAll(async()=>{harness=await startResearchVariableManagementHarness();});test.afterAll(async()=>{await harness?.close();});
async function open(page,{initial={},hold=null}={}){
 const state={calls:[],errors:[],unknown:[],release:null};page.on('pageerror',e=>state.errors.push(e.message));await page.addInitScript(v=>{window.__researchVariableManagementInitial=v;},initial);await page.context().route('**/*',r=>new URL(r.request().url()).origin===harness.origin?r.continue():r.abort());
 await page.route('**/api/**',async route=>{const q=route.request(),u=new URL(q.url()),path=u.pathname;state.calls.push({method:q.method(),path,query:Object.fromEntries(u.searchParams)});
  // Six unrelated management bootstrap lists are controlled empty transport,
  // not Source proof fixtures. Every Source response below is actual same-case HTTP.
  if(['/features','/providers','/knowledge','/grants','/audit','/usage'].some(s=>path==='/api/ai/admin'+s))return route.fulfill({json:{code:200,msg:'success',data:[]}});
  let stage;
  if(path==='/api/ai/research-cohort/scopes')stage='scope.admin_candidates';
  if(path==='/api/ai/research-cohort/scopes/'+F.source.scope_reference.scope_id)stage='scope.super_current';
  if(path==='/api/ai/research-variables/technical/dictionaries')stage='withdrawn.super_admin_user.technical.dictionaries.directory';
  if(path==='/api/ai/research-variables/dictionaries')stage='directory.dictionaries.current';
  if(path.startsWith('/api/ai/research-variables/technical/dictionaries/')){const row=F.record('withdrawn.super_admin_user.technical.dictionaries.metadata');return route.fulfill({status:row.status,body:row.body,headers:row.response_headers});}
  if(path.startsWith('/api/ai/research-variables/dictionaries/'))stage=path.includes('/parts/')?'dictionary.published.'+path.split('/').at(-1):'dictionary.published.metadata';
  if(stage){if(hold===stage)await new Promise(resolve=>{state.release=resolve;});const row=F.record(stage);return route.fulfill({status:row.status,body:row.body,headers:row.response_headers});}
  state.unknown.push(path);return route.fulfill({status:599,json:{detail:'Unmocked explicit management route'}});
 });await page.goto(harness.origin);await page.waitForFunction(()=>!!window.__researchVariableManagementProbe?.component);return state;
}
const sourceCalls=s=>s.calls.filter(v=>v.path.includes('/research-variables/')||v.path.includes('/research-cohort/'));
async function tab(page){await selectManagementTab(page, '科研变量字典与完整批次治理');await expect(page.getByRole('region',{name:'科研变量来源治理'})).toBeVisible();}
async function technical(page){await tab(page);await page.getByText('仅技术元数据目录（不恢复正文或执行权限）',{exact:true}).click();await page.getByRole('button',{name:'刷新变量来源目录',exact:true}).click();await page.getByRole('row').filter({hasText:dictionaryId}).getByRole('button',{name:'核对本件技术元数据',exact:true}).click();await expect(page.getByText('只有已核验的技术元数据。完整原件、临床正文和当前执行资格均未恢复。',{exact:true})).toBeVisible();}
test('real management mounts explicit Source governance and a technical directory never requests private parts',async({page})=>{
 const s=await open(page);await tab(page);expect(sourceCalls(s)).toEqual([]);await page.getByText('仅技术元数据目录（不恢复正文或执行权限）',{exact:true}).click();await page.getByRole('button',{name:'刷新变量来源目录',exact:true}).click();await page.getByRole('row').filter({hasText:dictionaryId}).getByRole('button',{name:'核对本件技术元数据',exact:true}).click();await expect(page.getByText('只有已核验的技术元数据。完整原件、临床正文和当前执行资格均未恢复。',{exact:true})).toBeVisible();expect(sourceCalls(s).every(v=>v.method==='GET'&&v.path.includes('/technical/'))).toBe(true);expect(s.unknown).toEqual([]);expect(s.errors).toEqual([]);
});
for(const initial of [{roles:['admin']},{roles:'super_admin'},{roles:['super_admin',3]},{token:'   '},{username:'   '}])test('malformed or non-Super management session has no variable Source tab '+JSON.stringify(initial),async({page})=>{
 const s=await open(page,{initial});await expectManagementEntry(page, '科研变量字典与完整批次治理', false);expect(sourceCalls(s)).toEqual([]);expect(s.errors).toEqual([]);
});
for(const change of ['token','username','deactivate'])test('technical Source detail is cleared when management '+change,async({page})=>{
 const s=await open(page);await technical(page);await page.evaluate(change=>{const p=window.__researchVariableManagementProbe;if(change==='token')p.store.commit('user/token','replacement');if(change==='username')p.store.commit('user/username','replacement');if(change==='deactivate')p.scope.mounted=false;},change);await expect(page.getByRole('dialog',{name:'变量来源完整核对',exact:true})).toHaveCount(0);expect(s.errors).toEqual([]);expect(s.unknown).toEqual([]);
});
test('ordinary Source governance inside real management requires explicit project and complete current dictionary parts',async({page})=>{
 const s=await open(page);await tab(page);await page.getByRole('button',{name:'读取明确项目目录',exact:true}).click();await page.getByRole('button',{name:'核对并明确本项目',exact:true}).click();await expect(page.getByText(/明确项目 .*；用途已记录/)).toBeVisible();await page.getByRole('button',{name:'刷新变量来源目录',exact:true}).click();await page.getByRole('button',{name:'按当前授权读取完整两件',exact:true}).click();await expect(page.getByText(/两份完整分件、原件字面值、治理关系和末次元数据已核对/)).toBeVisible();expect(sourceCalls(s).filter(v=>v.path.includes('/parts/')).map(v=>v.path.split('/').at(-1))).toEqual(['definition','scope']);expect(sourceCalls(s).every(v=>v.method==='GET')).toBe(true);expect(s.unknown).toEqual([]);expect(s.errors).toEqual([]);
});
test('leaving the management tab while a full Source part is held clears it and cannot request the remaining private part',async({page})=>{
 const s=await open(page,{hold:'dictionary.published.definition'});await tab(page);await page.getByRole('button',{name:'读取明确项目目录',exact:true}).click();await page.getByRole('button',{name:'核对并明确本项目',exact:true}).click();await expect(page.getByText(/明确项目 .*；用途已记录/)).toBeVisible();await page.getByRole('button',{name:'刷新变量来源目录',exact:true}).click();await page.getByRole('button',{name:'按当前授权读取完整两件',exact:true}).click();await expect.poll(()=>!!s.release).toBe(true);await selectManagementTab(page, '能力与启用');s.release();await expect(page.getByRole('dialog',{name:'变量来源完整核对',exact:true})).toHaveCount(0);await expect(page.getByRole('region',{name:'科研变量来源治理'})).toHaveCount(0);expect(sourceCalls(s).some(v=>v.path.endsWith('/parts/scope'))).toBe(false);expect(s.unknown).toEqual([]);expect(s.errors).toEqual([]);
});
