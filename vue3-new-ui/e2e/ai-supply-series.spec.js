const {test,expect}=require('@playwright/test');
const {startSupplySeriesHarness}=require('./fixtures/supply-series-harness.cjs');
const {partial:F,complete,openSupplySeries,begin,capture,fillComplete,inspect,cleared}=require('./fixtures/supply-series-ui.cjs');
let harness;
test.beforeAll(async()=>{harness=await startSupplySeriesHarness();});
test.afterAll(async()=>{expect(harness.unhandled).toEqual([]);await harness.close();});
const published=()=>({list:F.published_directory,detail:F.published_ordinary});
test('完整112日三目标表单不默认单位、参数或确认；实际全部声明经DOM提交',async({page})=>{
 test.setTimeout(120000);const s=await openSupplySeries(page,harness),d=await capture(page,s);
 await expect(d.getByRole('button',{name:'保存全部原件声明和参数草稿',exact:true})).toBeDisabled();
 await expect(d.getByRole('combobox',{name:'本序列明确受审单位',exact:true})).toHaveValue('');
 await expect(d.getByRole('textbox',{name:'alpha_size 分子',exact:true})).toHaveValue('');
 await fillComplete(page,d,s);await expect(d.getByRole('button',{name:'保存全部原件声明和参数草稿',exact:true})).toBeEnabled();
 await d.getByRole('button',{name:'保存全部原件声明和参数草稿',exact:true}).click();
 await expect(page.getByRole('article',{name:'完整物资序列原件',exact:true})).toBeVisible();
 expect(s.writes.find(r=>r.path.endsWith('/supply-series')).body).toEqual(F.create_request);
 expect(s.errors).toEqual([]);
});
test('336个实际日原件跨17页成员和16页日期全部通过真实DOM提交而非只提交当前页',async({page})=>{
 test.setTimeout(180000);const s=await openSupplySeries(page,harness,{fixture:complete}),d=await capture(page,s);
 await fillComplete(page,d,s);await expect(d.getByRole('button',{name:'保存全部原件声明和参数草稿',exact:true})).toBeEnabled();
 await d.getByRole('button',{name:'保存全部原件声明和参数草稿',exact:true}).click();
 await expect(page.getByRole('article',{name:'完整物资序列原件',exact:true})).toBeVisible();
 expect(s.writes.find(r=>r.path.endsWith('/supply-series')).body).toEqual(complete.create_request);
 expect(s.errors).toEqual([]);
});
test('普通选择先GET完整SHA/HMAC再仅发原系列标识，Super普通入口也不读audit',async({page})=>{
 const s=await openSupplySeries(page,harness,{...published(),role:'super_admin'});await inspect(page);
 await page.getByRole('button',{name:'选择此完整受审物资序列',exact:true}).click();
 expect(await page.evaluate(()=>window.__supplySeriesProbe.events.filter(e=>e.type==='select'))).toEqual([{type:'select',value:{supply_series_id:F.published_ordinary.series_id}}]);
 expect(s.reads.every(r=>r.query.audit_only!=='true')).toBe(true);expect(s.errors).toEqual([]);
});
test('Super实际草稿独立发布绑定原参数、版本与本次依据',async({page})=>{
 const s=await openSupplySeries(page,harness,{role:'super_admin',governance:true,list:F.draft_directory,detail:F.draft_super,review:F.published_super});
 await inspect(page,F.draft_super.series_id);await page.getByRole('button',{name:'独立审核发布序列与参数',exact:true}).click();
 const d=page.getByRole('dialog',{name:'独立审核完整物资序列',exact:true});await d.getByRole('textbox',{name:'本次完整物资序列治理依据',exact:true}).fill(F.review_request.basis_note);await d.getByRole('button',{name:'保存本次独立治理',exact:true}).click();
 await expect(page.getByRole('article',{name:'完整物资序列原件',exact:true})).toContainText('已审核发布');
 expect(s.writes.find(r=>r.path.endsWith('/review')).body).toEqual(F.review_request);expect(s.errors).toEqual([]);
});
test('普通撤销严格1000码点限制，实际redacted回执不保留旧自由原文',async({page})=>{
 const s=await openSupplySeries(page,harness,published());await inspect(page);await page.getByRole('button',{name:'按原版本撤销物资序列',exact:true}).click();
 const d=page.getByRole('dialog',{name:'独立审核完整物资序列',exact:true}),field=d.getByRole('textbox',{name:'本次完整物资序列治理依据',exact:true}),save=d.getByRole('button',{name:'保存本次独立治理',exact:true});
 await field.fill('x'.repeat(1001));await expect(save).toBeDisabled();await field.fill('😀'.repeat(1000));await expect(save).toBeEnabled();
 await field.fill(F.revoke_request.basis_note);await save.click();await expect(page.getByRole('article',{name:'完整物资序列原件',exact:true})).toContainText('均已隐去');
 expect(s.writes.find(r=>r.path.endsWith('/revoke')).body).toEqual(F.revoke_request);expect(await page.evaluate(()=>window.__supplySeriesProbe.panel.$.setupState.selected.snapshot)).toBeNull();expect(s.errors).toEqual([]);
});
for(const status of [403,409])test('当前完整件'+status+'清除原文并发失效',async({page})=>{
 const s=await openSupplySeries(page,harness,published());await inspect(page);s.failure=(m,p)=>m==='GET'&&p.endsWith(F.published_ordinary.series_id)?status:null;
 await page.getByRole('row').filter({hasText:F.published_ordinary.series_id}).getByRole('button',{name:'核对完整物资序列',exact:true}).click();await expect(page.locator('p[role=alert]')).toContainText(String(status));await cleared(page);
 expect(await page.evaluate(()=>window.__supplySeriesProbe.events.some(e=>e.type==='invalidate'))).toBe(true);expect(s.errors).toEqual([]);
});
for(const status of [403,409])test('旧会话详情'+status+'迟到不清除新会话已经核对的完整原件',async({page})=>{
 const s=await openSupplySeries(page,harness,{...published(),hold:(m,p)=>m==='GET'&&p.endsWith(F.published_ordinary.series_id)?'old':null,failure:(m,p)=>m==='GET'&&p.endsWith(F.published_ordinary.series_id)?status:null});
 await page.getByRole('row').filter({hasText:F.published_ordinary.series_id}).getByRole('button',{name:'核对完整物资序列',exact:true}).click();await expect.poll(()=>!!s.releases.old).toBe(true);
 s.failure=null;s.hold=null;await page.evaluate(()=>window.__supplySeriesProbe.store.commit('user/token','new-current-session'));await inspect(page);
 s.releases.old();await expect.poll(()=>s.completed.includes('old')).toBe(true);
 await expect(page.getByRole('article',{name:'完整物资序列原件',exact:true})).toContainText(F.published_ordinary.content_hash);expect(s.errors).toEqual([]);
});
test('合法同原件的旧发布回执未绑定本次不同治理依据仍拒绝并清原文',async({page})=>{
 const s=await openSupplySeries(page,harness,{role:'super_admin',governance:true,list:F.draft_directory,detail:F.draft_super,review:F.published_super});await inspect(page,F.draft_super.series_id);
 await page.getByRole('button',{name:'独立审核发布序列与参数',exact:true}).click();const d=page.getByRole('dialog',{name:'独立审核完整物资序列',exact:true});await d.getByRole('textbox',{name:'本次完整物资序列治理依据',exact:true}).fill('这是本次不同的隔离合成治理依据，必须完整逐字绑定保存回执，不能接受其他旧依据。');await d.getByRole('button',{name:'保存本次独立治理',exact:true}).click();
 await expect(page.locator('p[role=alert]')).toContainText('本次治理依据');await cleared(page);expect(s.errors).toEqual([]);
});
for(const change of ['token','role','itemKind','itemId','active','deactivate','destroy'])test('详情迟到跨'+change+'边界不得恢复旧原件',async({page})=>{
 const s=await openSupplySeries(page,harness,{...published(),hold:(m,p)=>m==='GET'&&p.endsWith(F.published_ordinary.series_id)?'detail':null});
 await page.getByRole('row').filter({hasText:F.published_ordinary.series_id}).getByRole('button',{name:'核对完整物资序列',exact:true}).click();await expect.poll(()=>!!s.releases.detail).toBe(true);
 await page.evaluate(change=>{const p=window.__supplySeriesProbe;if(change==='token')p.store.commit('user/token','new-session');else if(change==='role')p.store.commit('user/permissions',['nurse']);else if(change==='itemKind')p.scope.itemKind='consumable';else if(change==='itemId')p.scope.itemId++;else if(change==='active')p.scope.active=false;else if(change==='deactivate')p.scope.mounted=false;else p.scope.destroyed=true;},change);
 s.releases.detail();await expect.poll(()=>s.completed.includes('detail')).toBe(true);await cleared(page);expect(s.errors).toEqual([]);
});
for(const change of ['close','period'])test('真实Crypto待验证时'+change+'不恢复捕获和声明表',async({page})=>{
 const s=await openSupplySeries(page,harness),d=await begin(page,s);
 await page.evaluate(()=>{const original=crypto.subtle.digest.bind(crypto.subtle);window.__holdSupplyCrypto={entered:false,release:null};crypto.subtle.digest=async(...args)=>{const g=window.__holdSupplyCrypto;if(!g.entered){g.entered=true;await new Promise(r=>g.release=r);}return original(...args);};});
 await d.getByRole('button',{name:'读取完整候选、单位与逐日分组',exact:true}).click();await expect.poll(()=>page.evaluate(()=>window.__holdSupplyCrypto.entered)).toBe(true);
 if(change==='close')await d.getByRole('button',{name:'关闭',exact:true}).click();else await d.getByRole('textbox',{name:'明确IANA业务时区',exact:true}).fill('UTC');
 await page.evaluate(()=>window.__holdSupplyCrypto.release());await expect(d.getByRole('region',{name:'完整物资序列声明编辑',exact:true})).toHaveCount(0);expect(await page.evaluate(()=>({preview:window.__supplySeriesProbe.panel.$.setupState.preview,form:window.__supplySeriesProbe.panel.$.setupState.form}))).toEqual({preview:null,form:null});expect(s.errors).toEqual([]);
});
