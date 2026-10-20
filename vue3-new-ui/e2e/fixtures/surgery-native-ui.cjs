const { expect } = require('@playwright/test');
const fixture = require('./surgery-synthetic/native-pipeline.json');

// Actual pipeline packets remain unchanged. History entries are an explicitly
// lossless metadata extraction, not a claim of a separately executed HTTP list.
const packets = { ...fixture.by_objective, unknown: require('./surgery-synthetic/native-unknown.json'), transitions: require('./surgery-synthetic/native-transitions.json').packet };
const metadata = run => Object.fromEntries(Object.keys(run).filter(k => !['result', 'evidence', 'surgery_findings', 'frozen_request', 'tool_findings', 'operational_findings', 'feedback'].includes(k)).map(k => [k, run[k]]));
const feature = inputMode => ({ key: 'surgery_scheduling', number: 65, name: '手术排程优化', category: 'operations', engine: 'specialist', scope: 'hospital', input_mode: inputMode, enabled: true, requires_operational_validation: true, validation_status: 'validated', revision: 1, provider_id: 1, provider_revision: 1, inputs: ['明确病例队列与受审资源场景'], deliverables: ['候选方案及原始搜索界'], allowed_roles: ['admin', 'director', 'super_admin'] });
const references = packet => ({ surgery_scenario_id: packet.run_detail.surgery_findings.surgery_scenario.scenario_id });
const boundInput = packet => ({ ...references(packet), department_id: packet.run_detail.surgery_findings.surgery_scenario.department_id, surgery_pool_id: packet.run_detail.surgery_findings.surgery_scenario.pool_id, surgery_application_ids: packet.scenario_detail.snapshot.request.cases.map(c => c.application_id).sort() });

async function setupSurgeryNative(page, harness, config = {}) {
  const state = { mode: 'assistant', objective: 'required', role: 'admin', inputMode: 'surgery', writes: [], reads: [], errors: [], releases: {}, completed: [], runReplyStatuses: [], ...config };
  const packet = packets[state.objective];
  state.packet = packet; page.__surgeryNativeState = state;
  state.history ??= [metadata(packet.run_detail)];
  page.on('pageerror', error => state.errors.push(error.message));
  await page.context().route('**/*', route => new URL(route.request().url()).origin === harness.origin ? route.continue() : route.abort('blockedbyclient'));
  await page.route('**/api/**', async route => {
    const req = route.request(), u = new URL(req.url()), path = u.pathname, method = req.method();
    let data, total;
    if (method === 'GET') {
      state.reads.push({ path, query: Object.fromEntries(u.searchParams) });
      if (path === '/api/ai/features') data = [feature(state.inputMode)];
      else if (path === '/api/ai/surgery-sources/options') data = state.options || packet.source_options;
      else if (path === '/api/ai/surgery-scenarios') data = state.directory || packet.scenario_directory;
      else if (path.startsWith('/api/ai/surgery-scenarios/')) data = state.scenario || Object.values(packets).find(p => path.endsWith(p.scenario_detail.scenario_id))?.scenario_detail;
      else if (path === '/api/ai/service-options') data = { departments: [], default_window: ['2026-10-01', '2026-10-20'], default_planning_window: ['2026-10-21', '2026-10-21'], allow_hospital_scope: false, scope_note: '仅隔离旧模式选项，不含业务原件。' };
      else if (path === '/api/ai/runs') data = state.history;
      else if (path === '/api/ai/admin/runs') { data = state.history; total = data.length; }
      else if (path.startsWith('/api/ai/admin/runs/')) data = state.trace || Object.values(packets).find(p => path.endsWith(p.super_trace.run_id))?.super_trace;
      else if (path.startsWith('/api/ai/runs/')) { data = state.runSequence?.length ? state.runSequence.shift() : state.run || Object.values(packets).find(p => path.endsWith(p.run_detail.run_id))?.run_detail; if (data) state.runReplyStatuses.push(data.status); }
    } else {
      const body = req.postDataJSON(); state.writes.push({ path, body });
      if (path === '/api/ai/operational-context') data = state.inspection || packet.inspection;
      else if (path === '/api/ai/runs') data = state.receipt || packet.receipt;
      else if (path.endsWith('/feedback')) data = { recorded: true };
    }
    if (data === undefined) { state.errors.push(`Unhandled isolated ${method} ${path}`); await route.fulfill({ status: 500, json: { code: 500, msg: 'Synthetic route missing' } }); return; }
    const failure = state.failure?.(method, path, req), held = state.hold?.(method, path, req);
    const frozen = structuredClone(data), outgoing = state.mutate ? state.mutate(frozen, path, method) ?? frozen : frozen;
    if (held) await new Promise(resolve => state.releases[held] = resolve);
    try { await route.fulfill(failure ? { status: failure, json: { code: failure, msg: 'Synthetic current authorization unavailable' } } : { json: { code: 200, data: outgoing, ...(total === undefined ? {} : { total }) } }); }
    finally { if (held) state.completed.push(held); }
  });
  await page.goto(harness.origin); await page.waitForFunction(() => !!window.__surgeryNativeProbe);
  const row = packet.scenario_detail;
  await page.evaluate(({ role, mode, initialInput, departmentId, poolId, applicationIds, refs, run, context, features }) => {
    const p = window.__surgeryNativeProbe; p.store.commit('user/permissions', [role]);
    Object.assign(p.scope, { mode, initialInput, departmentId, poolId, applicationIds, references: refs, run, context, features, ready: true });
  }, { role: state.role, mode: state.mode, initialInput: state.initialInput ?? (state.mode === 'assistant' ? boundInput(packet) : {}), departmentId: state.departmentId ?? (state.mode === 'findings' || state.mode === 'input' ? row.department_id : null), poolId: state.poolId ?? (state.mode === 'findings' || state.mode === 'input' ? row.pool_id : null), applicationIds: state.applicationIds ?? null, refs: state.references ?? (state.mode === 'input' || state.mode === 'findings' ? references(packet) : null), run: state.mode === 'findings' ? state.run ?? packet.run_detail : null, context: state.context ?? null, features: [feature(state.inputMode)] });
  return state;
}
async function ready(page) { await expect(page.getByRole('button', { name: '生成辅助建议', exact: true })).toBeEnabled(); }
async function generate(page) { await ready(page); await page.getByRole('button', { name: '生成辅助建议', exact: true }).click(); await expect(page.getByLabel('AI任务结果', { exact: true })).toBeVisible(); await expect(page.getByRole('region', { name: '完整手术排程候选核对', exact: true })).toContainText('在明确声明范围内已证最优'); }
async function history(page) { await ready(page); const header = page.getByText('最近任务', { exact: true }).locator('xpath=ancestor-or-self::*[@aria-expanded][1]'); if (await header.getAttribute('aria-expanded') !== 'true') await page.getByText('最近任务', { exact: true }).click(); await page.evaluate(() => window.__surgeryNativeProbe.assistant.$.setupState.loadHistory(['0'])); await page.getByRole('button', { name: '查看', exact: true }).first().click(); await expect(page.getByLabel('AI任务结果', { exact: true })).toBeVisible(); }
async function evidence(page) { await page.getByRole('button', { name: '核对本次完整场景证据', exact: true }).click(); await expect(page.getByRole('dialog', { name: '核查引用依据', exact: true })).toContainText('surgery_scenario_private_v1'); }
async function cleared(page, held = false) {
  await expect(page.getByLabel('AI任务结果', { exact: true })).toHaveCount(0);
  await expect(page.getByRole('dialog', { name: '核查引用依据', exact: true })).toHaveCount(0);
  expect(await page.evaluate(held => { const p = window.__surgeryNativeProbe, s = (held ? p.heldAssistant : p.assistant).$.setupState; return { run: s.run, context: s.contextData, evidence: s.evidence, dialog: s.evidenceDialog }; }, held)).toEqual({ run: null, context: null, evidence: null, dialog: false });
}
async function inspectTrace(page) { await page.getByRole('button', { name: '执行溯源', exact: true }).first().click(); await expect(page.getByRole('dialog', { name: 'AI 任务执行溯源', exact: true }).getByRole('region', { name: '完整手术排程候选核对', exact: true })).toContainText('在明确声明范围内已证最优'); }
async function traceCleared(page, held = false) { expect(await page.evaluate(held => { const p = window.__surgeryNativeProbe, s = (held ? p.heldTrace : p.trace).$.setupState; return { detail: s.detail, evidence: s.evidence, visible: s.visible, evidenceVisible: s.evidenceVisible }; }, held)).toEqual({ detail: null, evidence: null, visible: false, evidenceVisible: false }); }
module.exports = { setupSurgeryNative, ready, generate, history, evidence, cleared, inspectTrace, traceCleared, metadata, feature, packets, fixture, references, boundInput };
