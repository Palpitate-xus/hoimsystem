const {test,expect}=require('@playwright/test');
const {startSupplySeriesHarness}=require('./fixtures/supply-series-harness.cjs');
const {F,openSupplyInput,selectMenu,horizon,selectSeries,bound,cleared}=require('./fixtures/supply-input-ui.cjs');
const complete=require('./fixtures/supply-series/input-complete.json');
let harness;test.beforeAll(async()=>{harness=await startSupplySeriesHarness({mode:'input'});});test.afterAll(async()=>{expect(harness.unhandled).toEqual([]);await harness.close();});
test('业务SKU锁定，未声明期限时不能选择；明确H14后真实全件二次核对再发精确两引用',async({page})=>{
 const s=await openSupplyInput(page,harness);await expect(page.getByRole('combobox',{name:'预测物资类型',exact:true})).toBeDisabled();await expect(page.getByRole('combobox',{name:'预测物资',exact:true})).toBeDisabled();
 await selectSeries(page);await cleared(page);await expect(page.locator('p[role=alert]')).toContainText('先明确选择');
 await horizon(page,14);await page.getByRole('button',{name:'选择此完整受审物资序列',exact:true}).click();await bound(page);
 expect(await page.evaluate(()=>window.__supplySeriesProbe.events.filter(e=>e.type==='selection'&&e.value).at(-1))).toEqual({type:'selection',value:{supply_series_id:F.published.series_id,horizon_days:14}});expect(s.errors).toEqual([]);
});
test('无业务绑定入口不默认目录首项，真实DOM选择药品/SKU/H7后才可用',async({page})=>{
 const s=await openSupplyInput(page,harness,{business:false});await cleared(page);await expect(page.getByRole('combobox',{name:'预测物资',exact:true})).toHaveValue('');
 await selectMenu(page,'预测物资类型');await page.getByRole('option',{name:'药品',exact:true}).click();
 await selectMenu(page,'预测物资');await page.getByRole('option',{name:`${F.catalogs.selected.items[0].name} · #${F.published.item_id}`,exact:true}).click();
 await horizon(page,7);await selectSeries(page);await bound(page);expect(s.errors).toEqual([]);
});
test('Super正常执行入口只读ordinary完整件，H14变H7保留SKU并重新校验',async({page})=>{
 const s=await openSupplyInput(page,harness,{role:'super_admin',initialReferences:{supply_series_id:F.published.series_id,horizon_days:14}});await bound(page);await horizon(page,7);await bound(page);
 await expect(page.getByLabel('已绑定物资预测序列',{exact:true})).toContainText('明确预测 7 天');expect(s.reads.every(r=>!r.path.includes('/admin/')&&r.query.audit_only!=='true')).toBe(true);expect(s.errors).toEqual([]);
});
test('初始仅原引用时从真实完整件确定SKU，保留明确14期限而非默认首项',async({page})=>{const s=await openSupplyInput(page,harness,{business:false,initialReferences:{supply_series_id:F.published.series_id,horizon_days:14}});await bound(page);await expect(page.getByLabel('已绑定物资预测序列',{exact:true})).toContainText('明确预测 14 天');expect(s.errors).toEqual([]);});
test('实际336根完整已发布序列及同case目录经Input全proof后选H14，不把partial件冒充完整',async({page})=>{test.setTimeout(90000);const s=await openSupplyInput(page,harness,{fixture:complete,initialReferences:{supply_series_id:complete.published.series_id,horizon_days:14}});await bound(page);expect(await page.evaluate(()=>{const r=window.__supplySeriesProbe.panel.$.setupState.chosen;return[r.snapshot.collection.source_records.length,r.public_source.observations.length,r.snapshot.request.member_reviews.length];})).toEqual([336,336,337]);expect(s.errors).toEqual([]);});
test('清除选择保留明确14期限与SKU，再选择仍发14',async({page})=>{const s=await openSupplyInput(page,harness,{initialReferences:{supply_series_id:F.published.series_id,horizon_days:14}});await bound(page);await page.getByRole('button',{name:'清除物资预测序列',exact:true}).click();await cleared(page);await selectSeries(page);await bound(page);expect(await page.evaluate(()=>window.__supplySeriesProbe.events.filter(e=>e.type==='selection'&&e.value).at(-1).value.horizon_days)).toBe(14);expect(s.errors).toEqual([]);});
for(const status of [403,409])test('当前重新核对目录'+status+'清除选择和整个SKU范围',async({page})=>{
 const s=await openSupplyInput(page,harness,{initialReferences:{supply_series_id:F.published.series_id,horizon_days:14}});await bound(page);s.failure=p=>p.endsWith('/options')?status:null;await page.getByRole('button',{name:'重新核对物资范围',exact:true}).click();await cleared(page);await expect(page.locator('p[role=alert]')).toContainText(String(status));expect(await page.evaluate(()=>window.__supplySeriesProbe.panel.$.setupState.selectedSku)).toBeNull();expect(s.errors).toEqual([]);
});
for(const change of ['token','role','active','deactivate','itemId','itemKind'])test('已核对原件跨'+change+'立即清除且旧绑定不能残留',async({page})=>{
 const s=await openSupplyInput(page,harness,{initialReferences:{supply_series_id:F.published.series_id,horizon_days:14}});await bound(page);s.hold=p=>p.endsWith('/options')?'new':null;
 await page.evaluate(change=>{const p=window.__supplySeriesProbe;if(change==='token')p.store.commit('user/token','new-input-session');else if(change==='role')p.store.commit('user/permissions',['nurse']);else if(change==='active')p.scope.active=false;else if(change==='deactivate')p.scope.mounted=false;else if(change==='itemId')p.scope.itemId++;else p.scope.itemKind='consumable';},change);await cleared(page);for(const release of Object.values(s.releases))release();expect(s.errors).toEqual([]);
});
for(const refs of [{supply_series_id:F.published.series_id,horizon_days:'14'},{supply_series_id:F.published.series_id,horizon_days:14,question:'extra'},{supply_series_id:F.published.series_id},{supply_series_id:F.published.series_id,horizon_days:7.5}])test('非法初始两引用整体拒绝 '+JSON.stringify(refs),async({page})=>{const s=await openSupplyInput(page,harness,{initialReferences:refs});await cleared(page);await expect(page.locator('p[role=alert]')).toContainText('原引用须完整');expect(s.reads).toEqual([]);expect(s.errors).toEqual([]);});
for(const change of ['token','role','active','itemId','horizon'])test('真实Input完整SHA Crypto待完成时'+change+'变化，await原方法完成仍不恢复旧选择',async({page})=>{
 const s=await openSupplyInput(page,harness);await expect(page.getByRole('row').filter({hasText:F.published.series_id})).toBeVisible();await horizon(page,14);
 await page.evaluate(id=>{const original=crypto.subtle.digest.bind(crypto.subtle);window.__supplyCrypto={entered:false};crypto.subtle.digest=async(...args)=>{const g=window.__supplyCrypto;if(!g.entered){g.entered=true;await new Promise(r=>g.release=r);}return original(...args);};window.__supplyInputPending=window.__supplySeriesProbe.panel.$.setupState.selectSeries({supply_series_id:id});},F.published.series_id);
 await expect.poll(()=>page.evaluate(()=>window.__supplyCrypto.entered)).toBe(true);
 if(change==='horizon')await horizon(page,7);else await page.evaluate(change=>{const p=window.__supplySeriesProbe;if(change==='token')p.store.commit('user/token','new-crypto-input-session');else if(change==='role')p.store.commit('user/permissions',['nurse']);else if(change==='active')p.scope.active=false;else p.scope.itemId++;},change);
 await page.evaluate(async()=>{window.__supplyCrypto.release();await window.__supplyInputPending;});await cleared(page);expect(s.errors).toEqual([]);
});
for(const status of [403,409])test('旧Input请求'+status+'迟到，await原方法不得清除新会话已选完整件',async({page})=>{
 const s=await openSupplyInput(page,harness);await expect(page.getByRole('row').filter({hasText:F.published.series_id})).toBeVisible();await horizon(page,14);s.hold=p=>p.endsWith(F.published.series_id)?'old':null;s.failure=p=>p.endsWith(F.published.series_id)?status:null;
 await page.evaluate(id=>{window.__supplyInputPending=window.__supplySeriesProbe.panel.$.setupState.selectSeries({supply_series_id:id});},F.published.series_id);await expect.poll(()=>!!s.releases.old).toBe(true);
 s.hold=null;s.failure=null;await page.evaluate(()=>window.__supplySeriesProbe.store.commit('user/token','new-late-input-session'));await selectSeries(page);await bound(page);
 s.releases.old();await page.evaluate(()=>window.__supplyInputPending);await bound(page);expect(s.errors).toEqual([]);
});
