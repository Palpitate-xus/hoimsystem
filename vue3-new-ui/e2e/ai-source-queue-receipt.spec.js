// Isolated mock API tests over real source components. These are not model HTTP
// or hospital-server tests. The short DTO comes from the actual offline runtime
// describe_run(False) export; complete source/proof fixtures are existing ORM DTOs.
const { test, expect } = require('@playwright/test');
const { startRosterHarness } = require('./fixtures/roster-source-harness.cjs');
const { setupRoster, choose, pipeline } = require('./fixtures/roster-ui.cjs');
const queued = require('./fixtures/source-queue-receipt.json');
const receiptStates = require('./fixtures/source-queue-receipt-states.json');
const other = require('./fixtures/roster-synthetic/feasible-meet.json');

let harness;
test.beforeAll(async () => { harness = await startRosterHarness(); });
test.afterAll(async () => { await harness?.close(); });
const runPath = `/api/ai/runs/${queued.run_id}`;
const clone = value => JSON.parse(JSON.stringify(value));

async function prepare(page, config = {}) {
  const receipt = config.receipt || queued;
  const { fullMutate, ...options } = config;
  const state = await setupRoster(page, harness, {
    mode: 'assistant',
    ...options,
    mutate(data, path, method) {
      if (path === '/api/ai/runs' && method === 'POST') return clone(receipt);
      if (path === runPath && method === 'GET' && fullMutate) return fullMutate(clone(data));
      return data;
    },
  });
  await choose(page, '受审排班原科室', '内科 · #1');
  await page.getByRole('button', { name: '选择受审排班计划', exact: true }).click();
  await expect(page.getByRole('button', { name: '生成辅助建议', exact: true })).toBeEnabled();
  return state;
}

async function submit(page) {
  await page.getByRole('button', { name: '生成辅助建议', exact: true }).click();
}

async function seedPrivateView(page) {
  await page.getByText('最近任务', { exact: true }).click();
  await page.getByRole('button', { name: '查看', exact: true }).click();
  await expect(page.getByLabel('AI任务结果', { exact: true })).toContainText('资料存在未知项');
  await page.getByText('最近任务', { exact: true }).click();
  await page.getByRole('button', { name: '查看本次运营资料', exact: true }).click();
  const preview = page.getByRole('dialog', { name: '本次提供给 AI 的运营资料', exact: true });
  await expect(preview).toBeVisible();
  await preview.locator('.el-dialog__headerbtn').click();
  await expect(preview).toBeHidden();
  await page.getByLabel('AI任务结果', { exact: true }).getByRole('button', { name: '核对完整受审排班原件', exact: true }).click();
  const evidence = page.getByRole('dialog', { name: '核查引用依据', exact: true });
  await expect(evidence).toContainText('roster_plan_private_v1');
  await evidence.locator('.el-dialog__headerbtn').click();
  await page.evaluate(() => { window.__rosterProbe.heldAssistant = window.__rosterProbe.assistant; });
}

async function assertCleared(page, { history = false } = {}) {
  await expect(page.getByLabel('AI任务结果', { exact: true })).toHaveCount(0);
  await expect(page.getByRole('dialog', { name: '核查引用依据', exact: true })).toHaveCount(0);
  await expect.poll(() => page.evaluate(() => {
    const probe = window.__rosterProbe;
    const state = (probe.heldAssistant || probe.assistant).$.setupState;
    return { run: state.run, context: state.contextData, evidence: state.evidence, dialog: state.evidenceDialog };
  })).toEqual({ run: null, context: null, evidence: null, dialog: false });
  if (history) expect(await page.evaluate(() => (window.__rosterProbe.heldAssistant || window.__rosterProbe.assistant).$.setupState.history)).toEqual([]);
}

test('真实短队列DTO不含原件，POST后只GET原runId完整核对再显示', async ({ page }) => {
  expect(queued.status).toBe('queued');
  expect(queued).not.toHaveProperty('result');
  expect(queued).not.toHaveProperty('roster_findings');
  expect(queued).not.toHaveProperty('evidence');
  const state = await prepare(page, { hold: (method, path) => method === 'GET' && path === runPath ? 'detail' : null });
  await submit(page);
  await expect.poll(() => !!state.releases.detail).toBe(true);
  await expect(page.getByLabel('AI任务结果', { exact: true })).toHaveCount(0);
  state.releases.detail();
  await expect(page.getByLabel('AI任务结果', { exact: true })).toContainText('资料存在未知项');
  expect(state.reads.filter(row => row.path.startsWith('/api/ai/runs/')).map(row => row.path)).toEqual([runPath]);
  expect(state.writes.find(row => row.path === '/api/ai/runs').body.input.roster_plan_id).toBe(pipeline.plan_detail.plan_id);
  await page.getByRole('button', { name: '核对完整受审排班原件', exact: true }).click();
  await expect(page.getByRole('dialog', { name: '核查引用依据', exact: true })).toContainText(pipeline.plan_detail.content_hash);
  expect(state.errors).toEqual([]);
});

for (const status of ['running', 'succeeded']) test(`真实describe(False)短${status}状态仍GET完整核对，允许worker已推进状态`, async ({ page }) => {
  expect(receiptStates[status].status).toBe(status);
  expect(receiptStates[status]).not.toHaveProperty('result');
  expect(receiptStates[status]).not.toHaveProperty('roster_findings');
  const state = await prepare(page, { receipt: receiptStates[status] });
  await submit(page);
  await expect(page.getByLabel('AI任务结果', { exact: true })).toContainText('资料存在未知项');
  expect(state.reads.filter(row => row.path.startsWith('/api/ai/runs/')).map(row => row.path)).toEqual([runPath]);
  expect(state.errors).toEqual([]);
});

for (const [field, value] of [
  ['run_id', '../other-run'], ['feature_key', 'bed_forecast'], ['status', 'unknown_status'],
  ['patient_id', 0], ['encounter_ref', ''], ['requires_human_review', false], ['context_digest', 'bad-hash'],
]) test(`短队列回执${field}非法时不读取或恢复私有原件`, async ({ page }) => {
  const state = await prepare(page, { receipt: { ...queued, [field]: value } });
  await submit(page);
  await expect(page.getByText('排队回执的任务、范围或状态不一致，暂不展示。', { exact: true })).toBeVisible();
  await assertCleared(page);
  expect(state.reads.filter(row => row.path.startsWith('/api/ai/runs/'))).toEqual([]);
  expect(state.errors).toEqual([]);
});

for (const [name, mutate] of [
  ['another_run_id', value => ({ ...value, run_id: '11111111-1111-4111-8111-111111111111' })],
  ['different_context_sha', value => ({ ...value, context_digest: '0'.repeat(64) })],
  ['patient_zero', value => ({ ...value, patient_id: 0 })],
  ['empty_admission', value => ({ ...value, encounter_ref: '' })],
]) test(`完整GET ${name}与原短回执不同必须拒绝`, async ({ page }) => {
  const state = await prepare(page, { fullMutate: mutate });
  await submit(page);
  await expect.poll(() => state.reads.filter(row => row.path === runPath).length).toBe(1);
  await expect(page.getByRole('button', { name: '生成辅助建议', exact: true })).toBeEnabled();
  await assertCleared(page);
  expect(state.errors).toEqual([]);
});

for (const status of [403, 409]) test(`短回执后的GET ${status}清除旧原件与院内依据`, async ({ page }) => {
  const state = await prepare(page);
  await seedPrivateView(page);
  state.failure = (method, path) => method === 'GET' && path === runPath ? status : null;
  await submit(page);
  await assertCleared(page);
  expect(state.errors).toEqual([]);
});

for (const phase of ['receipt', 'detail']) {
  for (const change of ['token', 'role', 'department', 'source', 'deactivate', 'scope']) {
    test(`等待${phase}期间${change}变化，迟到回执或详情不得恢复旧私件`, async ({ page }) => {
      const state = await prepare(page);
      await seedPrivateView(page);
      state.hold = (method, path) => phase === 'receipt'
        ? method === 'POST' && path === '/api/ai/runs' ? 'held' : null
        : method === 'GET' && path === runPath ? 'held' : null;
      await submit(page);
      await expect.poll(() => !!state.releases.held).toBe(true);
      await page.evaluate(change => {
        const probe = window.__rosterProbe;
        const state = probe.assistant.$.setupState;
        if (change === 'token') probe.store.commit('user/token', 'independent-next-session');
        if (change === 'role') probe.store.commit('user/permissions', ['patient']);
        if (change === 'department') state.serviceDepartment = 99;
        if (change === 'source') probe.scope.initialInput = { roster_plan_id: '11111111-1111-4111-8111-111111111111' };
        if (change === 'deactivate') probe.scope.mounted = false;
        if (change === 'scope') state.features[0].input_mode = 'external_optimizer';
      }, change);
      await assertCleared(page, { history: true });
      state.releases.held();
      await expect.poll(() => state.completed).toContain('held');
      await expect.poll(() => page.evaluate(() => window.__rosterProbe.heldAssistant.$.setupState.submitting)).toBe(false);
      await assertCleared(page, { history: true });
      if (change === 'deactivate') expect(await page.evaluate(() => window.__rosterProbe.heldAssistant.$.isDeactivated)).toBe(true);
      expect(state.errors).toEqual([]);
    });
  }
}

test('同runId及同短摘要仍须按当前所选原计划核完整private与公开投影', async ({ page }) => {
  const state = await prepare(page, { fullMutate: () => ({ ...clone(other.run_detail), run_id: queued.run_id, context_digest: queued.context_digest }) });
  await submit(page);
  await expect.poll(() => state.reads.filter(row => row.path === runPath).length).toBe(1);
  await expect(page.getByRole('button', { name: '生成辅助建议', exact: true })).toBeEnabled();
  await assertCleared(page);
  expect(state.errors).toEqual([]);
});
