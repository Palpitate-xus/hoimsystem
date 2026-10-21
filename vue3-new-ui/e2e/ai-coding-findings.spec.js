const {test,expect}=require('@playwright/test');
const actual=require('./fixtures/coding-results-actual.json');
const {startCodingResultsHarness}=require('./fixtures/coding-results-harness.cjs');
let harness;
test.beforeAll(async()=>{harness=await startCodingResultsHarness({mode:'findings'});});
test.afterAll(async()=>{await harness?.close();});
async function open(page,kind='detail'){
 await page.goto(harness.origin);await expect.poll(()=>page.evaluate(()=>!!window.__codingResultProbe)).toBe(true);
 await page.evaluate(({a,kind})=>{const p=window.__codingResultProbe;if(kind==='preview')p.scope.context=a.preview.data.context;else{p.scope.run=a[kind].data;if(kind==='audit'){p.store.commit('user/permissions',['super_admin']);p.scope.auditOnly=true;}}},{a:actual,kind});
}
const table=page=>page.locator('[aria-label="完整编码绑定与模型逐项意见"]');

test('actual complete accepted draft shows unreviewed claim and exact BOM emoji CRLF codepoint highlight',async({page})=>{
 await open(page);await expect(table(page)).toBeVisible();
 await page.getByRole('button',{name:'查看本项',exact:true}).click();
 await expect(page.getByLabel('当前编码逐项核实')).toContainText('模型称有冲突（待核实）');
 await page.getByRole('button',{name:'定位原文投影',exact:true}).click();
 const quote=actual.detail.data.result.coding_analysis.claims[0].citations[0].quote;
 await expect(page.getByLabel('可定位的模型可见文书投影').locator('mark')).toHaveText(quote);
 expect(quote).toContain('🧪');expect(quote).toContain('\r\n');expect(quote.startsWith('\ufeff')).toBe(true);
 await page.getByRole('button',{name:'查看完整来源依据',exact:true}).click();
 const events=await page.evaluate(()=>window.__codingResultProbe.events.filter(e=>e.type==='inspect'));
 expect(events).toHaveLength(1);expect(events[0].value).toEqual(actual.detail.data.evidence[0]);
});
for(const kind of ['preview','running'])test('actual '+kind+' retains original structure without accepted model claims',async({page})=>{
 await open(page,kind);await expect(table(page)).toBeVisible();await expect(page.getByText('没有已接受的模型草稿，以下仅显示原记录结构。',{exact:false})).toBeVisible();
 await expect(page.getByText('模型称有冲突（待核实）',{exact:true})).toHaveCount(0);
 await page.getByRole('button',{name:'展开完整院内原件',exact:true}).click();await expect(page.getByLabel('完整院内编码原件')).toContainText('identity_secret');
});
test('actual revoked Super frozen audit remains readable with explicit human-review scope',async({page})=>{
 await open(page,'audit');await expect(table(page)).toBeVisible();await expect(page.getByText('所有模型意见均待人工复核；文字位置一致不证明医学解释或编码适用性',{exact:true})).toBeVisible();
 await page.getByRole('button',{name:'展开完整院内原件',exact:true}).click();await expect(page.getByLabel('完整院内编码原件')).toBeVisible();
});
test('wrong literal quote blocks the entire draft and private original',async({page})=>{
 await open(page);await expect(table(page)).toBeVisible();await page.evaluate(()=>{window.__codingResultProbe.scope.run.result.coding_analysis.claims[0].citations[0].quote+='伪造';});
 await expect(page.getByRole('alert')).toContainText('暂不展示');await expect(table(page)).toHaveCount(0);await expect(page.getByLabel('完整院内编码原件')).toHaveCount(0);
});
for(const change of ['token','username','permissions'])test('same-scope '+change+' change clears retained private evidence immediately',async({page})=>{
 await open(page);await expect(table(page)).toBeVisible();await page.getByRole('button',{name:'展开完整院内原件',exact:true}).click();await expect(page.getByLabel('完整院内编码原件')).toBeVisible();
 await page.evaluate(change=>{const p=window.__codingResultProbe;p.store.commit('user/'+change,change==='permissions'?['admin']:'changed-synthetic-identity');},change);
 await expect(table(page)).toHaveCount(0);await expect(page.getByLabel('完整院内编码原件')).toHaveCount(0);
});
for(const change of ['active','keepalive'])test(change+' transition needs a fresh full packet before showing the same task again',async({page})=>{
 await open(page);await expect(table(page)).toBeVisible();await page.evaluate(change=>{const p=window.__codingResultProbe;if(change==='active')p.scope.active=false;else p.scope.mounted=false;},change);await expect(table(page)).toHaveCount(0);
 await page.evaluate(change=>{const p=window.__codingResultProbe;if(change==='active')p.scope.active=true;else p.scope.mounted=true;},change);await expect(table(page)).toHaveCount(0);
 await page.evaluate(a=>{window.__codingResultProbe.scope.run=structuredClone(a.detail.data);},actual);await expect(table(page)).toBeVisible();
});
test('patient and receipt scope mismatch never shows another complete original',async({page})=>{
 await open(page);await expect(table(page)).toBeVisible();await page.evaluate(a=>{const p=window.__codingResultProbe;p.scope.patientId=a.detail.data.patient_id+1;},actual);await expect(table(page)).toHaveCount(0);await expect(page.getByRole('alert')).toContainText('暂不展示');
 await page.evaluate(a=>{const p=window.__codingResultProbe;p.scope.patientId=null;p.scope.receipt={...a.queued.data,encounter_ref:'00000000-0000-0000-0000-000000000000'};},actual);await expect(table(page)).toHaveCount(0);await expect(page.getByRole('alert')).toContainText('任务回执');
});
test('auditOnly requires a current Super role and never reuses a normal doctor packet',async({page})=>{
 await open(page);await expect(table(page)).toBeVisible();await page.evaluate(()=>{window.__codingResultProbe.scope.auditOnly=true;});await expect(table(page)).toHaveCount(0);expect(harness.unhandled).toEqual([]);
});
