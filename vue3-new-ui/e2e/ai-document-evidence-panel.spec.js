const {test,expect}=require('@playwright/test');
const {startDocumentEvidenceHarness}=require('./fixtures/document-evidence-harness.cjs');
const {setupDocumentEvidence,fixture:f}=require('./fixtures/document-evidence-ui.cjs');
let harness;
test.beforeAll(async()=>{harness=await startDocumentEvidenceHarness({findings:true});});
test.afterAll(async()=>{await harness?.close();});
async function ready(page,config={}){const ctx=await setupDocumentEvidence(page,config);await page.goto(harness.origin);await expect(page.getByRole('button',{name:'登记原文草稿',exact:true})).toBeEnabled();return ctx;}
async function inspectOriginal(page,title=f.original_published.snapshot.metadata.title){await page.getByRole('row').filter({hasText:title}).getByRole('button',{name:'核对完整原件'}).click();await expect(page.getByRole('dialog',{name:'完整原文、定位与治理核对'})).toBeVisible();}
async function inspectTab(page,label){await page.getByRole('tab',{name:label,exact:true}).click();await page.getByRole('button',{name:'核对完整原件'}).first().click();await expect(page.getByRole('dialog',{name:'完整原文、定位与治理核对'})).toBeVisible();}
async function choose(page,label,option){const input=page.getByRole('combobox',{name:label,exact:true});await input.locator('xpath=ancestor::div[contains(concat(" ",normalize-space(@class)," ")," el-select " )]').click();await page.getByRole('option',{name:option,exact:true}).click();if(await input.getAttribute('aria-expanded')==='true')await page.keyboard.press('Escape');}
async function review(page){await choose(page,'审核决定','批准');await choose(page,'隐私审核','已核对隐私与允许披露范围');await choose(page,'原意审核','已核对原文与适用条件');await page.getByLabel('逐项审核依据',{exact:true}).fill(f.requests.original_review.basis_note);}
async function fillOriginal(page,body){const labels={title:'原文标题',version:'提交方声明的版本',declared_source_uri:'声明出处（仅保存，不访问外部地址）',declared_publisher:'声明发布方（未记录留空）',source_available_at:'原可得UTC（未记录留空）',applicability_note:'适用范围原说明',authorization_note:'授权使用说明'};for(const[key,label]of Object.entries(labels))if(body.metadata[key]!==null)await page.getByLabel(label,{exact:true}).fill(body.metadata[key]);await choose(page,'文档类型','指南原文');}
async function holdCrypto(page){await page.evaluate(()=>{const actual=crypto.subtle.digest.bind(crypto.subtle);let once=true;window.__documentCryptoHeld=false;crypto.subtle.digest=async(...args)=>{if(once){once=false;window.__documentCryptoHeld=true;await new Promise(resolve=>{window.__documentCryptoRelease=resolve;});}return actual(...args);};});}

test('actual original byte proof and explicit per-axis review without automatic knowledge',async({page})=>{
 const ctx=await ready(page,{stage:'original_draft'});await inspectOriginal(page);
 await expect(page.getByText('隐私与原意尚待', {exact:false})).toHaveCount(0);
 await page.getByRole('button',{name:'提交逐项审核'}).click();await expect(page.getByText('未知不会补成确认',{exact:false})).toBeVisible();expect(ctx.calls.filter(x=>x.method==='POST')).toHaveLength(0);
 await review(page);await page.getByRole('button',{name:'提交逐项审核'}).click();await expect(page.getByText('状态：原文已发布',{exact:false})).toBeVisible();expect(ctx.calls.filter(x=>x.path.endsWith('/publish'))).toHaveLength(0);expect(ctx.badBodies).toEqual([]);expect(ctx.errors).toEqual([]);
});

test('actual explicit codepoint zero span creates an unreviewed candidate with exact BOM and CRLF',async({page})=>{
 const ctx=await ready(page,{stage:'original_published'});await inspectOriginal(page);await page.getByRole('button',{name:'登记精确区间候选'}).click();await page.getByLabel('候选标题',{exact:true}).fill(f.requests.candidate_create.proposed_heading);await choose(page,'条款类型','推荐条款');await page.getByLabel('开始codepoint',{exact:true}).fill('0');await page.getByLabel('结束codepoint',{exact:true}).fill(String(f.requests.candidate_create.end));
 expect(await page.getByLabel('候选区间预览').textContent()).toBe(f.requests.candidate_create.quote);await page.getByRole('button',{name:'登记候选草稿',exact:true}).click();await expect(page.getByText('候选草稿已登记，尚未发布知识。',{exact:true})).toBeVisible();expect(ctx.badBodies).toEqual([]);expect(ctx.calls.filter(x=>x.path.endsWith('/publish'))).toHaveLength(0);
});

test('actual candidate review remains separate from explicit knowledge publication',async({page})=>{
 const ctx=await ready(page,{stage:'candidate_draft'});await inspectTab(page,'条款候选');await review(page);await page.getByRole('button',{name:'提交逐项审核'}).click();await expect(page.getByRole('button',{name:'明确发布为知识版本'})).toBeVisible();expect(ctx.calls.filter(x=>x.path.endsWith('/publish'))).toHaveLength(0);expect(ctx.badBodies).toEqual([]);
});

test('actual approved full quote explicitly publishes a bound knowledge version',async({page})=>{
 const ctx=await ready(page,{stage:'candidate_approved'});await inspectTab(page,'条款候选');await page.getByRole('button',{name:'明确发布为知识版本'}).click();const body=f.requests.publish;
 await page.getByLabel('知识标题',{exact:true}).fill(body.knowledge.title);await page.getByLabel('知识版本',{exact:true}).fill(body.knowledge.version);await page.getByLabel('知识发布依据',{exact:true}).fill(body.basis_note);await choose(page,'知识类别','临床知识');
 for(const key of body.knowledge.feature_keys){const label=f.options.knowledge_features.find(item=>item.key===key).name;await choose(page,'知识适用功能',label);}
 await page.getByRole('button',{name:'显式发布完整引文',exact:true}).click();await expect(page.getByText('完整引文已显式发布为知识；未启用任何临床功能或规则。',{exact:true})).toBeVisible();await expect(page.getByText('真实知识当前状态：已发布',{exact:false})).toBeVisible();expect(ctx.badBodies).toEqual([]);expect(await page.evaluate(()=>window.__documentProbe.events)).toEqual([f.publication_active.snapshot.knowledge_document_id]);
});

test('actual original revoke preserves full evidence and stops candidate creation',async({page})=>{
 const ctx=await ready(page,{stage:'publication_active'});await inspectOriginal(page);await page.getByLabel('撤销依据',{exact:true}).fill(f.requests.original_revoke.basis_note);await page.getByRole('button',{name:'按当前版本撤销',exact:true}).click();await expect(page.getByText('状态：已撤销',{exact:false})).toBeVisible();await expect(page.getByRole('button',{name:'登记精确区间候选'})).toHaveCount(0);await page.getByText('展开完整原文',{exact:true}).click();expect(await page.getByLabel('完整原文字节对应文本').textContent()).toBe(f.original_published.snapshot.text);expect(ctx.badBodies).toEqual([]);
});

test('actual stale publication remains auditable and explicit revoke retires current knowledge',async({page})=>{
 const ctx=await ready(page,{stage:'stale'});await inspectTab(page,'知识发布');await expect(page.getByText('原文或原审核版本已失效',{exact:false})).toBeVisible();await page.getByLabel('撤销依据',{exact:true}).fill(f.requests.publication_revoke.basis_note);await page.getByRole('button',{name:'按当前版本撤销',exact:true}).click();await expect(page.getByText('真实知识当前状态：已停用',{exact:false})).toBeVisible();expect(ctx.badBodies).toEqual([]);
});

test('actual file form preserves bytes without text normalization',async({page})=>{
 const ctx=await ready(page,{stage:'publication_active'});await page.getByRole('button',{name:'登记原文草稿',exact:true}).click();await fillOriginal(page,f.requests.file_create);await page.getByRole('radio',{name:'原UTF8文件',exact:true}).locator('xpath=ancestor::label').click();await page.getByLabel('UTF8原文件',{exact:true}).setInputFiles({name:f.requests.file_create.content.filename,mimeType:'text/markdown',buffer:Buffer.from(f.requests.file_create.content.bytes_base64,'base64')});await expect(page.getByText('已核对原文件字节：',{exact:false})).toBeVisible();await page.getByRole('button',{name:'核对字节并登记草稿',exact:true}).click();await expect(page.getByText('原文草稿已登记；隐私与原意尚待逐项审核。',{exact:true})).toBeVisible();expect(ctx.badBodies).toEqual([]);
});

test('actual direct-text form submits its exact submitted UTF8 quantity',async({page})=>{
 const ctx=await ready(page,{stage:'file_draft'});await page.getByRole('button',{name:'登记原文草稿',exact:true}).click();await fillOriginal(page,f.requests.direct_ui_create);await page.getByLabel('原文正文',{exact:true}).fill(f.requests.direct_ui_create.content.text);await page.getByRole('button',{name:'核对字节并登记草稿',exact:true}).click();await expect(page.getByText('原文草稿已登记；隐私与原意尚待逐项审核。',{exact:true})).toBeVisible();expect(ctx.badBodies).toEqual([]);
});

for(const change of ['token','role','deactivate','active'])test(`verified private original is cleared on ${change}`,async({page})=>{
 await ready(page);await inspectOriginal(page);await page.getByText('展开完整原文',{exact:true}).click();await expect(page.getByLabel('完整原文字节对应文本')).toBeVisible();await page.evaluate(change=>{const p=window.__documentProbe;if(change==='token')p.store.commit('user/token','new-document-session');if(change==='role')p.store.commit('user/permissions',['admin']);if(change==='deactivate')p.scope.mounted=false;if(change==='active')p.scope.active=false;},change);await expect(page.getByLabel('完整原文字节对应文本')).toHaveCount(0);
 if(['active','deactivate'].includes(change)){await page.evaluate(change=>{window.__documentProbe.scope[change==='active'?'active':'mounted']=true;},change);await expect(page.getByRole('button',{name:'登记原文草稿',exact:true})).toBeEnabled();await expect(page.getByRole('dialog')).toHaveCount(0);}
});

test('late crypto cannot restore original after role change',async({page})=>{
 await ready(page);await holdCrypto(page);await page.getByRole('row').filter({hasText:f.original_published.snapshot.metadata.title}).getByRole('button',{name:'核对完整原件'}).click();await page.waitForFunction(()=>window.__documentCryptoHeld);await page.evaluate(()=>window.__documentProbe.store.commit('user/permissions',['admin']));await page.evaluate(()=>window.__documentCryptoRelease());await expect(page.getByRole('dialog')).toHaveCount(0);await expect(page.getByLabel('完整原文字节对应文本')).toHaveCount(0);
});

test('closing a pending direct-text digest prevents upload and stale restoration',async({page})=>{
 const ctx=await ready(page,{stage:'file_draft'});await page.getByRole('button',{name:'登记原文草稿',exact:true}).click();await fillOriginal(page,f.requests.direct_ui_create);await page.getByLabel('原文正文',{exact:true}).fill(f.requests.direct_ui_create.content.text);await holdCrypto(page);await page.getByRole('button',{name:'核对字节并登记草稿',exact:true}).click();await page.waitForFunction(()=>window.__documentCryptoHeld);await page.getByRole('button',{name:'取消登记',exact:true}).click();await page.evaluate(()=>window.__documentCryptoRelease());await expect(page.getByRole('dialog')).toHaveCount(0);expect(ctx.calls.filter(x=>x.method==='POST')).toHaveLength(0);
});

test('closing after actual review receipt but held proof cannot restore raw material',async({page})=>{
 const ctx=await ready(page,{stage:'original_draft'});await inspectOriginal(page);await review(page);await holdCrypto(page);await page.getByRole('button',{name:'提交逐项审核'}).click();await page.waitForFunction(()=>window.__documentCryptoHeld);await page.getByRole('button',{name:'关闭原件核对',exact:true}).click();await page.evaluate(()=>window.__documentCryptoRelease());await expect(page.getByRole('dialog')).toHaveCount(0);expect(ctx.calls.filter(x=>x.method==='POST')).toHaveLength(1);
});

for(const mode of ['wrong_id','corrupt','forbidden'])test(`actual detail ${mode} is refused before any raw display`,async({page})=>{
 const oid=f.original_published.snapshot.original_id;const config={mutate:async(value,{path})=>{if(path===`/originals/${oid}`){if(mode==='wrong_id')value.snapshot.original_id='00000000-0000-0000-0000-000000000099';if(mode==='corrupt')value.snapshot.text+='PRIVATE_UNVERIFIED_SENTINEL';}return value;},status:({path})=>mode==='forbidden'&&path===`/originals/${oid}`?403:null};
 await ready(page,config);await page.getByRole('row').filter({hasText:f.original_published.snapshot.metadata.title}).getByRole('button',{name:'核对完整原件'}).click();await expect(page.getByRole('dialog')).toHaveCount(0);await expect(page.getByText('PRIVATE_UNVERIFIED_SENTINEL',{exact:false})).toHaveCount(0);await expect(page.getByText(mode==='forbidden'?'会话或权限已变化':'本次资料未展示',{exact:false})).toBeVisible();
});
