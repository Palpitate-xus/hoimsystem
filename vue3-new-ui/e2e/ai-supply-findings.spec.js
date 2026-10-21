const {test,expect}=require('@playwright/test');
const {startSupplyHarness}=require('./fixtures/supply-result-harness.cjs');
const {packet}=require('./fixtures/supply-pipeline-fixture.cjs');
let harness;
test.beforeAll(async()=>{harness=await startSupplyHarness({results:true});});
test.afterAll(async()=>{await harness?.close();});
async function open(page){const errors=[];page.on('pageerror',e=>errors.push(e.message));await page.route('**/api/**',route=>route.abort());await page.goto(harness.origin);await page.waitForFunction(()=>!!window.__supplyProbe?.results);return errors;}
for(const horizon of [7,14])test('actual full source, run and queued receipt reconstruct for H'+horizon,async({page})=>{
 const errors=await open(page),preview=packet(horizon,'preview').data,run=packet(horizon,'detail').data,receipt=packet(horizon,'queued').data;
 expect(await page.evaluate(async({preview,run,receipt})=>{const r=window.__supplyProbe.results;return{context:await r.verifySupplyContext(preview.context),run:await r.verifySupplyRun(run),receipt:r.verifySupplyReceipt(receipt,run)};},{preview,run,receipt})).toEqual({context:true,run:true,receipt:true});
 expect(errors).toEqual([]);
});
test('actual Superadmin frozen audit has independently verified private and public evidence',async({page})=>{
 const errors=await open(page),run=packet(14,'audit').data;
 expect(await page.evaluate(async run=>window.__supplyProbe.results.verifySupplyRun(run,{}, {auditOnly:true}),run)).toBe(true);expect(errors).toEqual([]);
});
async function mount(page,{horizon=14,state='detail',hold=false,role='admin'}={}){const errors=await open(page),run=packet(horizon,state).data,receipt=packet(horizon,'queued').data,b=run.supply_findings.supply_binding;await page.evaluate(({run,receipt,b,hold,role})=>{const p=window.__supplyProbe;if(hold){const original=crypto.subtle.digest.bind(crypto.subtle);let first=true;crypto.subtle.digest=async(...args)=>{if(first){first=false;await new Promise(resolve=>window.__releaseSupplyDigest=resolve);}return original(...args);};}p.store.commit('user/permissions',[role]);Object.assign(p.scope,{mode:'findings',run,receipt,expectedItemKind:b.item_kind,expectedItemId:b.item_id,expectedSeriesId:b.series_id,horizonDays:b.horizon_days,references:{supply_series_id:b.series_id,horizon_days:b.horizon_days}});},{run,receipt,b,hold,role});return{errors,run,receipt};}
const region=page=>page.locator('section[aria-label="完整物资数量预测核对"]');
test('actual H14 result displays exact six methods, 28 folds and controlled private disclosure',async({page})=>{
 const {errors,run}=await mount(page);await expect(region(page).getByText('三种已记录数量分别预测；不自动选最优，不推断潜在需求或生成采购指令。')).toBeVisible({timeout:20000});
 await expect(region(page).locator('[aria-label="六种固定物资预测方法"]').first()).toBeVisible();
 await expect(region(page).getByText(/392 个重叠原点—步长误差，涉及 41 个不同目标日期/)).toBeVisible();
 await expect(region(page).getByText(/这两个计数不覆盖没有原件的日期/).first()).toBeVisible();
 await expect(page.getByRole('button',{name:'查看原点与误差 SBA',exact:true}).first()).toBeVisible();await page.getByRole('button',{name:'查看原点与误差 SBA',exact:true}).first().click();
 await expect(region(page).locator('[aria-label="物资28滚动原点评价"]')).toBeVisible();
 await expect(page.getByLabel('完整院内物资原件')).toHaveCount(0);
 await page.getByText('查看完整院内原件与公开计算证明',{exact:true}).click();await page.getByRole('button',{name:'展开完整院内原件',exact:true}).click();
 await expect(page.getByLabel('完整院内物资原件')).toContainText(run.supply_findings.supply_series.snapshot.identity_secret);
 await page.getByRole('button',{name:'展开公开物资原量',exact:true}).click();await expect(page.getByLabel('公开物资原量')).not.toContainText(run.supply_findings.supply_series.snapshot.identity_secret);
 expect(errors).toEqual([]);
});
test('actual running full DTO shows verified source and no fabricated prediction',async({page})=>{
 const {errors}=await mount(page,{state:'running'});await expect(region(page).getByText('已核对本次完整来源；尚无成功计算结果，不显示预测量。')).toBeVisible({timeout:15000});await expect(region(page).locator('[aria-label="六种固定物资预测方法"]')).toHaveCount(0);expect(errors).toEqual([]);
});
for(const change of ['token','role','item','series','horizon','invalid_item','references','active','deactivate'])test('held complete verification cannot restore after '+change,async({page})=>{
 const {errors}=await mount(page,{hold:true});await page.waitForFunction(()=>typeof window.__releaseSupplyDigest==='function');
 await page.evaluate(change=>{const p=window.__supplyProbe;if(change==='token')p.store.commit('user/token','another-supply-session');else if(change==='role')p.store.commit('user/permissions',['director']);else if(change==='item')p.scope.expectedItemId++;else if(change==='series')p.scope.expectedSeriesId='00000000-0000-4000-8000-000000000001';else if(change==='horizon')p.scope.horizonDays=7;else if(change==='invalid_item')p.scope.expectedItemId=0;else if(change==='references')p.scope.references={supply_series_id:p.scope.expectedSeriesId,patient_id:1};else if(change==='active')p.scope.active=false;else p.scope.mounted=false;window.__releaseSupplyDigest();},change);
 await page.waitForTimeout(200);await expect(page.locator('[aria-label="六种固定物资预测方法"]')).toHaveCount(0);await expect(page.getByLabel('完整院内物资原件')).toHaveCount(0);expect(errors).toEqual([]);
});
for(const change of ['token','role','deactivate','active'])test('verified old object stays blocked after '+change+' and supports a fresh authorized read',async({page})=>{
 const {errors}=await mount(page);await expect(region(page).locator('[aria-label="六种固定物资预测方法"]').first()).toBeVisible({timeout:20000});
 await page.evaluate(change=>{const p=window.__supplyProbe;if(change==='token')p.store.commit('user/token','renewed-supply-session');else if(change==='role')p.store.commit('user/permissions',['director']);else if(change==='deactivate')p.scope.mounted=false;else p.scope.active=false;},change);
 await expect(page.locator('[aria-label="六种固定物资预测方法"]')).toHaveCount(0);
 if(['deactivate','active'].includes(change))await page.evaluate(change=>{const p=window.__supplyProbe;if(change==='deactivate')p.scope.mounted=true;else p.scope.active=true;},change);
 await page.waitForTimeout(150);await expect(page.locator('[aria-label="六种固定物资预测方法"]')).toHaveCount(0);
 await page.evaluate(()=>{const p=window.__supplyProbe;p.scope.run=structuredClone(JSON.parse(JSON.stringify(p.scope.run)));});await expect(region(page).locator('[aria-label="六种固定物资预测方法"]').first()).toBeVisible({timeout:20000});expect(errors).toEqual([]);
});
for(const change of ['public_quantity','unit_token','private_value','private_basis','horizon','selected_refs','extra_context','receipt_id','receipt_context','receipt_unknown','fixed_explanation','mixed_analysis'])test('complete result rejects binding tamper '+change,async({page})=>{
 await open(page);const run=packet(14,'detail').data,receipt=packet(14,'queued').data;
 expect(await page.evaluate(async({run,receipt,change})=>{const p=window.__supplyProbe,r=p.results,c=run.supply_findings,b=c.supply_binding;if(change==='public_quantity'||change==='unit_token'){if(change==='public_quantity')c.supply_source.observations[0].quantity.value='999';else c.supply_source.observations[0].unit_token='f'.repeat(64);c.supply_series.public_source=c.supply_source;c.supply_series.projection_hash=await p.supportDigest(c.supply_source);b.projection_hash=c.supply_series.projection_hash;return r.verifySupplyContext(c);}if(change==='private_value')c.supply_series.snapshot.collection.source_records[0].source.payload.quantity.value='999';else if(change==='private_basis')c.supply_series.snapshot.request.member_reviews[0].basis_note+=' altered';else if(change==='horizon')b.horizon_days=7;else if(change==='selected_refs')return r.verifySupplyContext(c,{references:{supply_series_id:b.series_id,horizon_days:7}});else if(change==='extra_context'){c.raw_patient='private';return r.verifySupplyContext(c);}else if(change==='receipt_id'){receipt.run_id='00000000-0000-4000-8000-000000000001';return r.verifySupplyReceipt(receipt,run);}else if(change==='receipt_context'){receipt.context_digest='f'.repeat(64);return r.verifySupplyReceipt(receipt,run);}else if(change==='receipt_unknown'){receipt.status='ready';return r.verifySupplyReceipt(receipt,run);}else if(change==='fixed_explanation')run.result.sections[1].source_ids=[b.source_id];else run.result.bed_analysis={};return r.verifySupplyRun(run);},{run,receipt,change})).toBe(false);
});
test('evidence resolves only exact original citation and remains an in-hospital packet',async({page})=>{
 await open(page);const run=packet(14,'detail').data;
 expect(await page.evaluate(async run=>{const r=window.__supplyProbe.results,p=run.supply_findings,e=run.evidence[0],resolved=await r.resolveSupplyEvidence(e,p);const wrong=await r.resolveSupplyEvidence({...e,source_id:'another-source'},p);return{resolved:!!resolved&&resolved.content.includes(p.supply_series.snapshot.identity_secret),wrong};},run)).toEqual({resolved:true,wrong:null});
});
test('unsupported original runtime explicitly refuses a current prediction display',async({page})=>{
 await open(page);const run=packet(14,'detail').data;run.result.supply_analysis.local_runtime.core_sha256.supply_server='f'.repeat(64);
 await page.evaluate(run=>Object.assign(window.__supplyProbe.scope,{mode:'findings',run}),run);await expect(region(page).getByText(/原运行版本当前无法重算/)).toBeVisible();await expect(page.locator('[aria-label="六种固定物资预测方法"]')).toHaveCount(0);
});
test('actual incomplete-source accepted task displays unknown targets without zero forecasts',async({page})=>{
 const fs=require('node:fs'),path=require('node:path'),actual=JSON.parse(fs.readFileSync(path.join(__dirname,'fixtures/supply-native/pipeline-unknown.json'),'utf8'));
 await open(page);await page.evaluate(run=>Object.assign(window.__supplyProbe.scope,{mode:'findings',run}),actual.detail.data);
 await expect(region(page).getByText(/资料未知，未生成该目标预测/).first()).toBeVisible({timeout:15000});
 await expect(region(page).getByText('没有该方法的数值预测；正值不足属于明确软件可用性门槛，不把未知正值大小补成零。')).toBeVisible();
 await expect(region(page).locator('[aria-label="物资目标逐日缺项"]').first()).toBeVisible();
 await expect(region(page).getByText(/显式 unknown 供应约束标记 0 日/).first()).toBeVisible();
 await expect(region(page).getByText(/不能据零推定全期间已核清供应/).first()).toBeVisible();
 expect(actual.detail.data.result.supply_analysis.targets[0].observed_sum).toBeNull();
});
for(const change of ['missing_metadata','metadata_clock','context_digest','clinical_fingerprint','evidence','tools','frozen_prompt'])test('original task metadata and exact evidence cannot mutually self-justify '+change,async({page})=>{
 await open(page);const run=packet(14,change==='frozen_prompt'?'audit':'detail').data;
 expect(await page.evaluate(async({run,change})=>{if(change==='missing_metadata')delete run.context_metadata;else if(change==='metadata_clock')run.context_metadata.snapshot_time='2026-02-30T00:00:00.000000Z';else if(change==='context_digest'){run.context_digest='f'.repeat(64);run.context_metadata.context_digest=run.context_digest;}else if(change==='clinical_fingerprint')run.context_metadata.clinical_context_fingerprint='f'.repeat(64);else if(change==='evidence')run.evidence[0].title='invented proof';else if(change==='tools')run.tool_findings={unapproved:'private'};else run.frozen_request.task_prompt+=' altered';return window.__supplyProbe.results.verifySupplyRun(run,{}, {auditOnly:true});},{run,change})).toBe(false);
});
for(const [role,auditOnly,accepted]of [['super_admin',false,false],['super_admin',true,true],['admin',true,false]])test('revoked original audit is explicit and Super-only '+role+'/'+auditOnly,async({page})=>{
 const actual=require('./fixtures/supply-native/pipeline-statuses.json');await open(page);
 await page.evaluate(({role,auditOnly,run})=>{const p=window.__supplyProbe;p.store.commit('user/permissions',[role]);Object.assign(p.scope,{mode:'findings',run,auditOnly});},{role,auditOnly,run:actual.revoked_audit.data});
 if(accepted)await expect(region(page).getByText(/资料未知，未生成该目标预测/).first()).toBeVisible({timeout:15000});else await expect(region(page).getByRole('alert').filter({hasText:'无法核对'})).toBeVisible({timeout:15000});
});
for(const note of ['\u0085'.repeat(20),'\u001c'.repeat(20),'😀'.repeat(10)])test('mechanical projection rejects invalid review basis '+JSON.stringify(note.slice(0,2)),async({page})=>{
 await open(page);const snapshot=packet(14,'detail').data.supply_findings.supply_series.snapshot;
 expect(await page.evaluate(({snapshot,note})=>{snapshot.request.member_reviews[0].basis_note=note;return window.__supplyProbe.results.projectSupplySnapshot(snapshot,'f'.repeat(64));},{snapshot,note})).toBeNull();
});
test('only fully bound findings emit their original evidence reference',async({page})=>{const{run}=await mount(page);const button=region(page).getByRole('button',{name:'核对本次完整物资原量依据',exact:true});await expect(button).toBeVisible({timeout:20000});await button.click();expect(await page.evaluate(()=>window.__supplyProbe.events.filter(e=>e.type==='inspect'))).toEqual([{type:'inspect',value:run.supply_findings.supply_binding.source_id}]);});
