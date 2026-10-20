const { test, expect } = require('@playwright/test');
const { startSurgeryNativeHarness } = require('./fixtures/surgery-native-harness.cjs');
const { setupSurgeryNative, ready, generate, history, evidence, cleared, inspectTrace, traceCleared, packets, references, boundInput } = require('./fixtures/surgery-native-ui.cjs');

let harness;
test.beforeAll(async () => { harness = await startSurgeryNativeHarness({ resultsOnly: process.env.HOIM_SURGERY_NATIVE_RESULTS_ONLY === '1' }); });
test.afterAll(async () => { await harness?.close(); });
test.afterEach(async ({ page }, info) => {
  if (info.status === info.expectedStatus) return;
  const state = page.__surgeryNativeState;
  for (const release of Object.values(state?.releases || {})) release();
  const ui = await page.evaluate(() => { const p = window.__surgeryNativeProbe, s = p?.assistant?.$?.setupState; return { text: document.body.innerText.slice(0, 7000), selected: s?.surgerySelection, ready: s?.surgeryReady, modeReady: s?.surgeryModeReady, department: s?.serviceDepartment, pool: s?.serviceSurgeryPool }; }).catch(() => null);
  const diagnostic = { errors: state?.errors, reads: state?.reads, writes: state?.writes, ui };
  await info.attach('isolated-synthetic-diagnostic', { body: JSON.stringify(diagnostic, null, 2), contentType: 'application/json' });
  console.log('ISOLATED_SYNTHETIC_DIAGNOSTIC', JSON.stringify(diagnostic));
});

for (const objective of ['required', 'optional']) test(`真实母页${objective}目标保留原声明，actual queued短回执GET同ID完整任务`, async ({ page }) => {
  const s = await setupSurgeryNative(page, harness, { objective });
  const p = s.packet, source = p.run_detail.surgery_findings.surgery_source, local = p.run_detail.surgery_findings.surgery_scenario.local_resolution;
  await ready(page);
  await page.getByRole('textbox', { name: '补充资料或问题', exact: true }).fill('仅院内保留的合成核实问题，不改变有限开始时刻或病例队列。');
  await page.getByRole('button', { name: '查看本次运营资料', exact: true }).click();
  const preview = page.getByRole('dialog', { name: '本次提供给 AI 的运营资料', exact: true });
  const outbound = preview.getByLabel('手术排程匿名公开输入', { exact: true });
  expect(JSON.parse(await outbound.textContent())).toEqual({ context: { surgery_source: source } });
  await expect(outbound).not.toContainText('identity_secret'); await expect(outbound).not.toContainText('仅院内保留'); await expect(outbound).not.toContainText('"patient_id":');
  await preview.locator('.el-dialog__headerbtn').click();
  await generate(page);
  const findings = page.getByRole('region', { name: '完整手术排程候选核对', exact: true });
  await expect(findings).toContainText(objective === 'required' ? '满足全部必排声明后最小化明确惩罚' : '先最大化可选病例排入数量，再最小化明确惩罚');
  await expect(findings).toContainText('惩罚 0'); await expect(findings).toContainText('不自动预约');
  const assignments = page.getByLabel('手术候选逐病例排程', { exact: true });
  await expect(assignments).toContainText(local.cases[0].application_id);
  await expect(assignments).toContainText(local.resources.find(r => r.resource_kind === 'room').label);
  await expect(assignments).toContainText(p.run_detail.result.surgery_analysis.solution.assignments[0].start_at);
  expect(s.writes.find(r => r.path === '/api/ai/runs').body.input).toEqual({ ...references(p), question: '仅院内保留的合成核实问题，不改变有限开始时刻或病例队列。' });
  expect(s.reads.some(r => r.path === '/api/ai/runs/' + p.receipt.run_id)).toBe(true);
  expect(s.reads.some(r => r.path === '/api/ai/service-options')).toBe(false);
  expect(s.errors).toEqual([]);
});

test('院内证据按原场景展开完整原件，反馈仍只绑定原任务不自动预约', async ({ page }) => {
  const s = await setupSurgeryNative(page, harness); await history(page); await evidence(page);
  const d = page.getByRole('dialog', { name: '核查引用依据', exact: true }); await expect(d).toContainText(s.packet.scenario_detail.content_hash); await expect(d).toContainText('identity_secret');
  await d.locator('.el-dialog__headerbtn').click();
  await page.getByRole('button', { name: '记录复核反馈', exact: true }).click();
  const f = page.getByRole('dialog', { name: '人工复核反馈', exact: true });
  await f.getByPlaceholder('说明核查结果或修改内容；反馈不会自动写入病历、处方或医嘱', { exact: true }).fill('隔离合成工程人工核对，不代表实际人员资格或运营效果验证。');
  await f.getByRole('button', { name: '保存反馈', exact: true }).click();
  expect(s.writes.at(-1)).toEqual({ path: `/api/ai/runs/${s.packet.run_detail.run_id}/feedback`, body: { outcome: 'accepted', comment: '隔离合成工程人工核对，不代表实际人员资格或运营效果验证。' } });
  expect(s.errors).toEqual([]);
});

test('历史列表精确绑定原科室资源池场景，不混患者住院或旧排程输入', async ({ page }) => {
  const s = await setupSurgeryNative(page, harness); await history(page);
  expect(s.reads.filter(r => r.path === '/api/ai/runs').at(-1).query).toEqual({ feature_key: 'surgery_scheduling', department_id: String(s.packet.scenario_detail.department_id), surgery_pool_id: s.packet.scenario_detail.pool_id, surgery_scenario_id: s.packet.scenario_detail.scenario_id });
});

test('同资源池科室但原病例cohort不同，真实合法场景仍拒选且不开放生成', async ({ page }) => {
  const other = packets.optional.scenario_detail.snapshot.request.cases.map(c => c.application_id);
  const s = await setupSurgeryNative(page, harness, { initialInput: { ...boundInput(packets.required), surgery_application_ids: other } });
  await expect(page.getByRole('region', { name: '受审手术排程入口', exact: true }).getByRole('alert').filter({ hasText: '请选择当前已发布' })).toBeVisible();
  await expect(page.getByRole('button', { name: '生成辅助建议', exact: true })).toBeDisabled();
  expect(await page.evaluate(() => window.__surgeryNativeProbe.assistant.$.setupState.surgerySelection)).toBeNull();
  expect(s.writes.some(r => r.path === '/api/ai/runs')).toBe(false); expect(s.errors).toEqual([]);
});

test('绑定原病例队列的入口禁止配置退回外部手术模式', async ({ page }) => {
  const s = await setupSurgeryNative(page, harness, { inputMode: 'external_surgery', initialInput: { surgery_application_ids: packets.required.scenario_detail.snapshot.request.cases.map(c => c.application_id) } });
  await expect(page.getByRole('alert').filter({ hasText: '此入口绑定原病例队列或完整受审场景' })).toBeVisible();
  await expect(page.getByRole('button', { name: '生成辅助建议', exact: true })).toBeDisabled();
  expect(s.writes.some(r => r.path === '/api/ai/runs')).toBe(false);
});

test('原排队context摘要不等于完整任务时清空，不借相同runID通过', async ({ page }) => {
  const s = await setupSurgeryNative(page, harness, { receipt: { ...packets.required.receipt, context_digest: '0'.repeat(64) } });
  await ready(page); await page.getByRole('button', { name: '生成辅助建议', exact: true }).click();
  await expect(page.getByRole('alert').filter({ hasText: /完整任务与原排队/ })).toBeVisible(); await cleared(page); expect(s.errors).toEqual([]);
});

test('完整结果夹带其他feature时不能显示院内手术原文', async ({ page }) => {
  const mixed = structuredClone(packets.required.run_detail); mixed.feature_key = 'bed_forecast';
  const s = await setupSurgeryNative(page, harness, { run: mixed }); await ready(page); await page.getByText('最近任务', { exact: true }).click(); await page.getByRole('button', { name: '查看', exact: true }).first().click();
  await cleared(page); expect(s.errors).toEqual([]);
});

for (const change of ['token', 'role', 'department', 'pool', 'provider', 'config', 'mode', 'cohort', 'initial-department', 'initial-pool', 'deactivate', 'unmount']) test(`已读任务与证据在${change}变化清空，迟到完整任务不能恢复`, async ({ page }) => {
  const s = await setupSurgeryNative(page, harness); await history(page); await evidence(page); await page.getByRole('dialog', { name: '核查引用依据', exact: true }).locator('.el-dialog__headerbtn').click();
  s.hold = (m, p) => m === 'GET' && p.startsWith('/api/ai/runs/') ? 'old-run' : null;
  await page.getByRole('button', { name: '查看', exact: true }).first().click(); await expect.poll(() => !!s.releases['old-run']).toBe(true);
  await page.evaluate(change => { const p = window.__surgeryNativeProbe; p.heldAssistant = p.assistant; const s = p.assistant.$.setupState;
    if (change === 'token') p.store.commit('user/token', 'later-surgery-session'); else if (change === 'role') p.store.commit('user/permissions', ['patient']); else if (change === 'department') s.serviceDepartment = 99; else if (change === 'pool') s.serviceSurgeryPool = '00000000-0000-4000-8000-000000000099'; else if (change === 'provider') s.features[0].provider_revision++; else if (change === 'config') s.features[0].validation_status = 'pending'; else if (change === 'mode') s.features[0].input_mode = 'external_surgery'; else if (change === 'cohort') p.scope.initialInput = { ...p.scope.initialInput, surgery_application_ids: ['invalid-original-application'] }; else if (change === 'initial-department') p.scope.initialInput = { ...p.scope.initialInput, department_id: 99 }; else if (change === 'initial-pool') p.scope.initialInput = { ...p.scope.initialInput, surgery_pool_id: '00000000-0000-4000-8000-000000000099' }; else if (change === 'deactivate') p.scope.mounted = false; else p.scope.destroyed = true;
  }, change);
  s.releases['old-run'](); await expect.poll(() => s.completed.includes('old-run')).toBe(true); await cleared(page, true); expect(s.errors).toEqual([]);
});

for (const phase of ['preview', 'detail', 'history', 'feedback']) for (const status of [403, 409]) test(`当前${phase}${status}清空已读结果证据和私有原件`, async ({ page }) => {
  const s = await setupSurgeryNative(page, harness); await history(page); await evidence(page); await page.getByRole('dialog', { name: '核查引用依据', exact: true }).locator('.el-dialog__headerbtn').click();
  s.failure = (m, p) => phase === 'preview' ? p === '/api/ai/operational-context' ? status : null : phase === 'history' ? m === 'GET' && p === '/api/ai/runs' ? status : null : phase === 'feedback' ? p.endsWith('/feedback') ? status : null : m === 'GET' && p.startsWith('/api/ai/runs/') ? status : null;
  if (phase === 'preview') await page.getByRole('button', { name: '查看本次运营资料', exact: true }).click();
  else if (phase === 'history') await page.evaluate(() => window.__surgeryNativeProbe.assistant.$.setupState.loadHistory(['0']));
  else if (phase === 'feedback') await page.evaluate(() => window.__surgeryNativeProbe.assistant.$.setupState.submitFeedback());
  else await page.getByRole('button', { name: '查看', exact: true }).first().click();
  await cleared(page); expect(s.errors).toEqual([]);
});

for (const change of ['role', 'token', 'filter', 'deactivate']) test(`Super真实冻结溯源在${change}变化清除，晚回执不能带回原患者映射`, async ({ page }) => {
  const s = await setupSurgeryNative(page, harness, { mode: 'trace', role: 'super_admin' }); await inspectTrace(page);
  await page.getByRole('button', { name: '核对本次完整场景证据', exact: true }).click(); await expect(page.getByRole('dialog', { name: '任务原始依据', exact: true })).toContainText('identity_secret');
  await page.getByRole('dialog', { name: '任务原始依据', exact: true }).locator('.el-dialog__headerbtn').click();
  await page.getByRole('dialog', { name: 'AI 任务执行溯源', exact: true }).locator('.el-dialog__headerbtn').click();
  s.hold = (m, p) => m === 'GET' && p.startsWith('/api/ai/admin/runs/') ? 'old-trace' : null;
  await page.getByRole('button', { name: '执行溯源', exact: true }).first().click(); await expect.poll(() => !!s.releases['old-trace']).toBe(true);
  await page.evaluate(change => { const p = window.__surgeryNativeProbe; p.heldTrace = p.trace; if (change === 'role') p.store.commit('user/permissions', ['admin']); else if (change === 'token') p.store.commit('user/token', 'later-audit-session'); else if (change === 'filter') p.trace.$.setupState.filters.feature_key = 'bed_forecast'; else p.scope.mounted = false; }, change);
  s.releases['old-trace'](); await expect.poll(() => s.completed.includes('old-trace')).toBe(true); await traceCleared(page, true); expect(s.errors).toEqual([]);
});

for (const phase of ['list', 'trace']) for (const status of [403, 409]) test(`管理员当前${phase}${status}完整清除原溯源且不抛未处理回执`, async ({ page }) => {
  const s = await setupSurgeryNative(page, harness, { mode: 'trace', role: 'super_admin' }); await inspectTrace(page);
  await page.getByRole('dialog', { name: 'AI 任务执行溯源', exact: true }).locator('.el-dialog__headerbtn').click();
  s.failure = (m, p) => phase === 'list' ? p === '/api/ai/admin/runs' ? status : null : p.startsWith('/api/ai/admin/runs/') ? status : null;
  if (phase === 'list') await page.getByRole('button', { name: '刷新任务', exact: true }).click(); else await page.getByRole('button', { name: '执行溯源', exact: true }).first().click();
  await traceCleared(page); expect(s.errors).toEqual([]);
});

for (const status of ['running_after_actual_sql_claim', 'succeeded_from_actual_sql_row']) test(`实际SQL状态${status}短回执仍读取同ID完整件，不假设worker未领取`, async ({ page }) => {
  const s = await setupSurgeryNative(page, harness, { receipt: packets.required.short_receipts[status] });
  await generate(page); expect(s.reads.some(r => r.path === '/api/ai/runs/' + s.packet.run_detail.run_id)).toBe(true); expect(s.errors).toEqual([]);
});

test('真实unknown声明仍治理可用，Findings保持资料不足和未知目标而不宣称最优', async ({ page }) => {
  const s = await setupSurgeryNative(page, harness, { objective: 'unknown' }); await ready(page);
  await page.getByRole('button', { name: '生成辅助建议', exact: true }).click(); await expect(page.getByLabel('AI任务结果', { exact: true })).toBeVisible();
  const region = page.getByRole('region', { name: '完整手术排程候选核对', exact: true });
  await expect(region).toContainText('资料不足，不能给出完整排程结论'); await expect(region).toContainText('本次明确声明范围仍有缺口'); await expect(region).toContainText('已知可行目标 未取得'); await expect(region).not.toContainText('在明确声明范围内已证最优');
  expect(s.packet.scenario_detail.eligible).toBe(true); expect(s.packet.run_detail.result.surgery_analysis.solve_status).toBe('input_unknown'); expect(s.errors).toEqual([]);
});

test('精确惩罚字符串被JS数字替代即拒绝，不把类型变更当零成本合法证明', async ({ page }) => {
  const run = structuredClone(packets.required.run_detail); run.result.surgery_analysis.solution.exact_penalty_points = 0;
  const s = await setupSurgeryNative(page, harness, { mode: 'findings', run });
  const region = page.getByRole('region', { name: '完整手术排程候选核对', exact: true });
  await expect(region.getByRole('alert')).toContainText('手术场景、身份映射或完整结果绑定无法核对');
  await expect(region.getByLabel('手术候选逐病例排程', { exact: true })).toHaveCount(0); expect(s.errors).toEqual([]);
});

for (const phase of ['history', 'feedback']) test(`旧session${phase}403迟到不能清除新session已核场景和依据`, async ({ page }) => {
  const s = await setupSurgeryNative(page, harness); await history(page);
  s.hold = (m, p) => phase === 'history' ? m === 'GET' && p === '/api/ai/runs' ? 'old' : null : p.endsWith('/feedback') ? 'old' : null;
  s.failure = (m, p) => phase === 'history' ? m === 'GET' && p === '/api/ai/runs' ? 403 : null : p.endsWith('/feedback') ? 403 : null;
  await page.evaluate(phase => { const s = window.__surgeryNativeProbe.assistant.$.setupState; void (phase === 'history' ? s.loadHistory(['0']) : s.submitFeedback()); }, phase);
  await expect.poll(() => !!s.releases.old).toBe(true); s.hold = s.failure = null;
  await page.evaluate(() => window.__surgeryNativeProbe.store.commit('user/token', 'new-authorized-surgery-session'));
  await cleared(page); await history(page); await evidence(page);
  s.releases.old(); await expect.poll(() => s.completed.includes('old')).toBe(true);
  await expect(page.getByRole('dialog', { name: '核查引用依据', exact: true })).toContainText(s.packet.scenario_detail.content_hash);
  await expect(page.getByLabel('AI任务结果', { exact: true })).toBeVisible(); expect(s.errors).toEqual([]);
});

test('完整且合法的另一原任务不能替代所请求run_id', async ({ page }) => {
  const s = await setupSurgeryNative(page, harness, { run: packets.optional.run_detail }); await ready(page);
  await page.getByText('最近任务', { exact: true }).click(); await page.getByRole('button', { name: '查看', exact: true }).first().click();
  await cleared(page); expect(s.errors).toEqual([]);
});


test('仅给原场景引用且未限定病例cohort，真实null语义仍可核对与执行', async ({ page }) => {
  const p = packets.required;
  const s = await setupSurgeryNative(page, harness, { initialInput: { ...references(p), department_id: p.scenario_detail.department_id } });
  await generate(page); expect(s.errors).toEqual([]);
});

for (const invalid of [[], 'not-an-array', ['not-a-uuid'], [packets.required.scenario_detail.snapshot.request.cases[0].application_id, packets.required.scenario_detail.snapshot.request.cases[0].application_id]]) test(`非法明确cohort ${JSON.stringify(invalid)}不能借合法原场景读历史或预览`, async ({ page }) => {
  const s = await setupSurgeryNative(page, harness, { initialInput: { ...boundInput(packets.required), surgery_application_ids: invalid } });
  await page.waitForFunction(() => window.__surgeryNativeProbe.assistant?.$?.setupState.features.length === 1);
  await expect(page.getByRole('button', { name: '生成辅助建议', exact: true })).toBeDisabled();
  await page.evaluate(async id => { const s = window.__surgeryNativeProbe.assistant.$.setupState; await s.loadHistory(['0']); await s.openRun(id); await s.inspectOperationalContext(); }, packets.required.run_detail.run_id);
  await cleared(page);
  expect(s.reads.some(r => r.path === '/api/ai/runs' || r.path.startsWith('/api/ai/runs/'))).toBe(false);
  expect(s.writes.some(r => ['/api/ai/runs', '/api/ai/operational-context'].includes(r.path))).toBe(false); expect(s.errors).toEqual([]);
});


test('从明确原病例cohort手动选择资源池与实际场景，双读核对后才开放生成', async ({ page }) => {
  const p = packets.required, row = p.scenario_detail;
  const s = await setupSurgeryNative(page, harness, { initialInput: { department_id: row.department_id, surgery_application_ids: row.snapshot.request.cases.map(c => c.application_id) } });
  await expect(page.getByRole('button', { name: '生成辅助建议', exact: true })).toBeDisabled();
  await page.getByRole('combobox', { name: '明确手术排程资源池', exact: true }).press('ArrowDown');
  await page.getByRole('option', { name: p.source_options.pools.find(x => x.pool_id === row.pool_id).name + ' · 科室 #' + row.department_id, exact: true }).click();
  await page.getByRole('button', { name: '核对完整场景', exact: true }).click();
  const original = page.getByRole('article', { name: '受审完整手术场景原件', exact: true });
  await expect(original).toContainText(row.content_hash);
  await original.getByRole('button', { name: '选择本条受审场景', exact: true }).click();
  await generate(page);
  expect(s.writes.find(r => r.path === '/api/ai/runs').body.input.surgery_scenario_id).toBe(row.scenario_id);
  expect(s.reads.filter(r => r.path.endsWith('/' + row.scenario_id)).length).toBeGreaterThanOrEqual(2); expect(s.errors).toEqual([]);
});

test('actual完整queued→实际SQLclaimed running→native succeeded真实同ID轮询，空result不伪作失败', async ({ page }) => {
  const states = require('./fixtures/surgery-synthetic/native-transitions.json').full_by_status;
  const s = await setupSurgeryNative(page, harness, { objective: 'transitions', runSequence: [states.queued, states.running, states.succeeded] });
  s.hold = (m, p) => m === 'GET' && p === '/api/ai/runs/' + states.queued.run_id && ['running', 'succeeded'].includes(s.runReplyStatuses.at(-1)) ? 'full-' + s.runReplyStatuses.at(-1) : null;
  await ready(page); await page.getByRole('button', { name: '生成辅助建议', exact: true }).click();
  const result = page.getByLabel('AI任务结果', { exact: true }); await expect(result).toContainText('已排队');
  await expect(result).toContainText('尚未显示固定优化计算结果'); await expect(result).not.toContainText('在明确声明范围内已证最优');
  await expect.poll(() => !!s.releases['full-running']).toBe(true); s.releases['full-running']();
  await expect.poll(() => page.evaluate(() => window.__surgeryNativeProbe.assistant.$.setupState.run?.status)).toBe('running');
  await expect(result).toContainText('生成中'); await expect(result).not.toContainText('在明确声明范围内已证最优');
  await expect.poll(() => !!s.releases['full-succeeded']).toBe(true); s.releases['full-succeeded']();
  await expect(result.getByRole('region', { name: '完整手术排程候选核对', exact: true })).toContainText('在明确声明范围内已证最优');
  expect(s.runReplyStatuses).toEqual(['queued', 'running', 'succeeded']); expect(s.errors).toEqual([]);
});


for (const status of ['failed', 'cancelled']) test(`真实独立${status}任务完整GET保留原状态与来源，空result不伪作成功最优`, async ({ page }) => {
  const states = require('./fixtures/surgery-synthetic/native-transitions.json').full_by_status, original = states[status];
  const s = await setupSurgeryNative(page, harness, { objective: 'transitions', run: original, history: [require('./fixtures/surgery-native-ui.cjs').metadata(original)] });
  await history(page);
  const result = page.getByLabel('AI任务结果', { exact: true });
  await expect.poll(() => page.evaluate(() => window.__surgeryNativeProbe.assistant.$.setupState.run?.status)).toBe(status);
  await expect(result.locator('.result-header')).toContainText(status === 'failed' ? '失败' : '已取消');
  await expect(result).toContainText('尚未显示固定优化计算结果'); await expect(result).not.toContainText('在明确声明范围内已证最优');
  await expect(page.getByRole('button', { name: '记录复核反馈', exact: true })).toHaveCount(0); expect(s.errors).toEqual([]);
});

for (const variant of ['over_cap', 'single_plural_conflict']) test(`原病例明确输入${variant}拒绝生成历史和预览，不能静默截断或忽略single`, async ({ page }) => {
  const input = boundInput(packets.required);
  if (variant === 'over_cap') input.surgery_application_ids = Array.from({ length: 257 }, (_, i) => '00000000-0000-4000-8000-' + String(i + 1).padStart(12, '0'));
  else input.surgery_application_id = packets.optional.scenario_detail.snapshot.request.cases[0].application_id;
  const s = await setupSurgeryNative(page, harness, { initialInput: input });
  await page.waitForFunction(() => window.__surgeryNativeProbe.assistant?.$?.setupState.features.length === 1);
  await page.evaluate(async id => { const s = window.__surgeryNativeProbe.assistant.$.setupState; await s.loadHistory(['0']); await s.openRun(id); await s.inspectOperationalContext(); }, packets.required.run_detail.run_id);
  await expect(page.getByRole('button', { name: '生成辅助建议', exact: true })).toBeDisabled(); await cleared(page);
  expect(s.reads.some(r => r.path === '/api/ai/runs' || r.path.startsWith('/api/ai/runs/'))).toBe(false);
  expect(s.writes.some(r => ['/api/ai/runs', '/api/ai/operational-context'].includes(r.path))).toBe(false); expect(s.errors).toEqual([]);
});
