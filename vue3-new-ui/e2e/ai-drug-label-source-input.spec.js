const {test,expect}=require('@playwright/test');
const {startDrugLabelHarness}=require('./fixtures/drug-label-source-harness.cjs');
const {openDrugLabel,choose,inspect,holdCrypto,fixture:f,sku}=require('./fixtures/drug-label-source-ui.cjs');
let harness;test.beforeAll(async()=>{harness=await startDrugLabelHarness({input:true});});test.afterAll(async()=>harness?.close());
const id=f.states.published.draft_super.snapshot.source_binding_id,refs={drug_label_source_binding_id:id};
async function ready(page){await page.getByRole('button',{name:'重新核对明确来源',exact:true}).click();await expect(page.getByRole('status').filter({hasText:'已明确选择目录'})).toBeVisible();}
async function unavailable(page){await expect.poll(()=>page.evaluate(()=>window.__drugLabelProbe.inputState?.selected)).toBeNull();await expect.poll(()=>page.evaluate(()=>window.__drugLabelProbe.events.filter(v=>v.kind==='availability').at(-1)?.value)).toBe(false);await expect(page.getByLabel('完整说明书原文',{exact:true})).toHaveCount(0);}
test('explicit reference requires a new read and stores only minimal verified anchors',async({page})=>{
 const state=await openDrugLabel(page,harness,{phase:'reviewed',scope:{initialReferences:refs}});await expect(page.getByText('请从目录选择说明书来源。')).toBeVisible();expect(state.calls.some(v=>v.path.endsWith('/'+id))).toBe(false);await ready(page);const selected=await page.evaluate(()=>window.__drugLabelProbe.inputState.selected);expect(selected.source_binding_id).toBe(id);expect(Object.keys(selected).sort()).toEqual(['source_binding_id','source_id','content_hash','governance_hash','identity_hash','identity','original','professional'].sort());expect(JSON.stringify(selected)).not.toContain(f.original_parent.snapshot.text);expect(JSON.stringify(selected)).not.toContain(f.states.published.signature_request.basis_note);expect(await page.evaluate(()=>window.__drugLabelProbe.events.filter(v=>v.kind==='selection').at(-1).value)).toEqual(refs);expect(state.calls.some(v=>v.method!=='GET')).toBe(false);expect(state.errors).toEqual([]);
});
test('manual actual catalog full read and select rechecks Source without retaining private text',async({page})=>{
 const state=await openDrugLabel(page,harness,{phase:'reviewed',scope:{pharmaceuticalId:sku}});await page.getByRole('button',{name:'打开说明书来源目录'}).click();await inspect(page);await page.getByRole('button',{name:'显式展开完整说明书'}).click();await expect(page.getByLabel('完整说明书原文',{exact:true})).toBeVisible();await page.getByRole('button',{name:'明确选择本件来源'}).click();await expect(page.getByRole('status').filter({hasText:'已明确选择目录'})).toBeVisible();await expect(page.getByLabel('本次说明书来源目录',{exact:true})).toHaveCount(0);await expect(page.getByLabel('完整说明书原文',{exact:true})).toHaveCount(0);expect(state.calls.filter(v=>v.path.endsWith('/'+id))).toHaveLength(2);expect(state.errors).toEqual([]);
});
for(const value of [null,{}])test(`no initial reference ${JSON.stringify(value)} never selects first source`,async({page})=>{
 const state=await openDrugLabel(page,harness,{phase:'reviewed',scope:{initialReferences:value}});await page.getByRole('button',{name:'打开说明书来源目录'}).click();await expect(page.getByText('尚未选择药品；不会自动选取第一项。')).toBeVisible();await unavailable(page);expect(state.calls.some(v=>v.path.endsWith('/'+id))).toBe(false);
});
for(const value of [{drug_label_source_binding_id:null},{drug_label_source_binding_id:id,document_original_id:id},{drug_label_source_binding_id:1},{drug_label_source_binding_id:id.toUpperCase()}])test(`invalid exact reference ${JSON.stringify(value)} stays closed`,async({page})=>{
 const state=await openDrugLabel(page,harness,{phase:'reviewed',scope:{initialReferences:value}});await expect(page.getByRole('alert').filter({hasText:'来源引用或实际目录药品范围无效'})).toBeVisible();await unavailable(page);expect(state.calls).toHaveLength(0);
});
test('explicit real SKU mismatch rejects a valid source from another SKU',async({page})=>{
 await openDrugLabel(page,harness,{phase:'reviewed',scope:{initialReferences:refs,pharmaceuticalId:1}});await page.getByRole('button',{name:'重新核对明确来源'}).click();await expect(page.getByRole('alert').filter({hasText:'完整来源、当前签署或药品范围无法核对'})).toBeVisible();await unavailable(page);
});
for(const change of ['token','role','username','sku','same-sku-binding','reference','active','keepalive','unmount'])test(`${change} invalidates minimal selection and does not silently restore it`,async({page})=>{
 const state=await openDrugLabel(page,harness,{phase:'reviewed',scope:{initialReferences:refs,...(change==='same-sku-binding'?{}:{pharmaceuticalId:sku})}});await ready(page);const calls=state.calls.length;await page.evaluate(({change,id,sku})=>{const p=window.__drugLabelProbe;if(change==='token')p.store.commit('user/token','new-session');if(change==='role')p.store.commit('user/permissions',['doctor']);if(change==='username')p.store.commit('user/username','different-account');if(change==='sku')p.scope.pharmaceuticalId=1;if(change==='same-sku-binding')p.scope.pharmaceuticalId=sku;if(change==='reference')p.scope.initialReferences={drug_label_source_binding_id:null};if(change==='active')p.scope.active=false;if(change==='keepalive')p.scope.mounted=false;if(change==='unmount')p.scope.destroyed=true;},{change,id,sku});await unavailable(page);if(change==='active')await page.evaluate(()=>window.__drugLabelProbe.scope.active=true);if(change==='keepalive')await page.evaluate(()=>window.__drugLabelProbe.scope.mounted=true);await unavailable(page);expect(state.calls.length).toBe(calls);
});
test('closing Source directory invalidates an existing input selection',async({page})=>{
 await openDrugLabel(page,harness,{phase:'reviewed',scope:{initialReferences:refs,pharmaceuticalId:sku}});await ready(page);await page.getByRole('button',{name:'打开说明书来源目录'}).click();await unavailable(page);await page.getByRole('button',{name:'关闭本次来源目录'}).click();await expect(page.getByLabel('本次说明书来源目录',{exact:true})).toHaveCount(0);await unavailable(page);
});
for(const phase of ['draft','revoked'])test(`${phase} normal source never becomes a task reference`,async({page})=>{
 await openDrugLabel(page,harness,{phase,scope:{initialReferences:refs,pharmaceuticalId:sku}});await page.getByRole('button',{name:'重新核对明确来源'}).click();await expect(page.getByRole('alert').filter({hasText:phase==='revoked'?'来源或签署已改变':'完整来源、当前签署或药品范围无法核对'})).toBeVisible();await unavailable(page);
});
test('late full Source fetch cannot establish a selection after close',async({page})=>{
 const state=await openDrugLabel(page,harness,{phase:'reviewed',scope:{initialReferences:refs,pharmaceuticalId:sku}});state.hold=call=>call.path.endsWith('/'+id);await page.getByRole('button',{name:'重新核对明确来源'}).click();await expect.poll(()=>state.held.length).toBe(1);await page.evaluate(()=>window.__drugLabelProbe.input.clear({close:true}));state.release();await unavailable(page);
});
test('held proof crypto cannot establish a selection after new initial scope',async({page})=>{
 await openDrugLabel(page,harness,{phase:'reviewed',scope:{initialReferences:refs,pharmaceuticalId:sku}});await holdCrypto(page);await page.getByRole('button',{name:'重新核对明确来源'}).click();await page.waitForFunction(()=>window.__drugCrypto.length>0);await page.evaluate(()=>{window.__drugLabelProbe.scope.pharmaceuticalId=1;window.__drugReleaseCrypto();});await unavailable(page);
});
