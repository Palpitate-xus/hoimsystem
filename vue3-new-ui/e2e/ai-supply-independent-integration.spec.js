const { beforeSourceHarness } = require('./fixtures/source-harness-setup.cjs');
const { test, expect } = require('@playwright/test');
const { startSupplyAssistantHarness } = require('./fixtures/supply-assistant-harness.cjs');
const { setupSupplyAssistant } = require('./fixtures/supply-assistant-ui.cjs');

// Real shared trace, real request client and production Babel rule. Responses
// are isolated mocked routes carrying unchanged synthetic ORM/worker packets.
let harness;
beforeSourceHarness(test,async () => { harness = await startSupplyAssistantHarness(); });
test.afterAll(async () => { await harness?.close(); });
test.afterEach(async ({ page }) => {
  for (const release of Object.values(page.__supplyAssistantState?.releases || {})) release();
});

const traceDialog = page => page.getByRole('dialog', { name: 'AI 任务执行溯源', exact: true });
const evidenceDialog = page => page.getByRole('dialog', { name: '任务原始依据', exact: true });
async function open(page) {
  const state = await setupSupplyAssistant(page, harness, { mode: 'trace', role: 'super_admin' });
  await expect(page.getByRole('button', { name: '执行溯源', exact: true }).first()).toBeVisible();
  return state;
}
async function emptyPrivate(page) {
  await expect(evidenceDialog(page)).not.toBeVisible();
  expect(await page.evaluate(() => {
    const s = window.__supplyAssistantProbe.trace.$.setupState;
    return { detailEmpty: s.detail === null, evidenceEmpty: s.evidence === null, visible: s.visible, evidenceVisible: s.evidenceVisible, loading: s.detailLoading };
  })).toEqual({ detailEmpty: true, evidenceEmpty: true, visible: false, evidenceVisible: false, loading: false });
}
async function holdDigest(page) {
  await page.evaluate(() => {
    const original = crypto.subtle.digest.bind(crypto.subtle); let first = true;
    crypto.subtle.digest = async (...args) => {
      if (first) { first = false; await new Promise(resolve => { window.__releaseIndependentSupplyDigest = resolve; }); }
      return original(...args);
    };
  });
}
function inspect(page) {
  return page.evaluate(async () => {
    const s = window.__supplyAssistantProbe.trace.$.setupState;
    await s.inspect(s.rows[0]);
  });
}

test('closed private evidence releases its original, and closing the trace rejects an in-flight SHA expansion', async ({ page }) => {
  const state = await open(page);
  await page.getByRole('button', { name: '执行溯源', exact: true }).first().click();
  const button = traceDialog(page).getByRole('button', { name: '核对本次完整物资原量依据', exact: true });
  await expect(button).toBeVisible({ timeout: 20000 });
  await button.click();
  await expect(evidenceDialog(page)).toContainText('identity_secret');
  await evidenceDialog(page).locator('.el-dialog__headerbtn').click();
  await expect(evidenceDialog(page)).not.toBeVisible();
  await expect.poll(() => page.evaluate(() => window.__supplyAssistantProbe.trace.$.setupState.evidence === null)).toBe(true);
  await holdDigest(page);
  const pending = page.evaluate(async () => {
    const s = window.__supplyAssistantProbe.trace.$.setupState;
    await s.showEvidence(s.detail.evidence[0].source_id);
  });
  await page.waitForFunction(() => typeof window.__releaseIndependentSupplyDigest === 'function');
  await traceDialog(page).locator('.el-dialog__headerbtn').click();
  await expect(traceDialog(page)).not.toBeVisible();
  await page.evaluate(() => window.__releaseIndependentSupplyDigest());
  await pending;
  await emptyPrivate(page);
  expect(state.errors).toEqual([]);
});

test('closing the trace rejects its first full task GET when the response arrives later', async ({ page }) => {
  const state = await open(page); let once = false;
  state.hold = (method, path) => method === 'GET' && path.startsWith('/api/ai/admin/runs/') && !once ? (once = true, 'first-trace') : null;
  const pending = inspect(page);
  await expect.poll(() => !!state.releases['first-trace']).toBe(true);
  await traceDialog(page).locator('.el-dialog__headerbtn').click();
  await expect(traceDialog(page)).not.toBeVisible();
  state.releases['first-trace'](); await pending;
  await emptyPrivate(page);
  expect(state.errors).toEqual([]);
});

test('closing the trace rejects its first complete original verification after the real SHA resumes', async ({ page }) => {
  const state = await open(page);
  await holdDigest(page); const pending = inspect(page);
  await page.waitForFunction(() => typeof window.__releaseIndependentSupplyDigest === 'function');
  await traceDialog(page).locator('.el-dialog__headerbtn').click();
  await expect(traceDialog(page)).not.toBeVisible();
  await page.evaluate(() => window.__releaseIndependentSupplyDigest()); await pending;
  await emptyPrivate(page);
  expect(state.errors).toEqual([]);
});

test('a changed account identity rejects the previous account full trace response', async ({ page }) => {
  const state = await open(page); let once = false;
  state.hold = (method, path) => method === 'GET' && path.startsWith('/api/ai/admin/runs/') && !once ? (once = true, 'old-account') : null;
  const pending = inspect(page);
  await expect.poll(() => !!state.releases['old-account']).toBe(true);
  await page.evaluate(() => window.__supplyAssistantProbe.store.commit('user/username', 'different-synthetic-auditor'));
  state.releases['old-account'](); await pending;
  await emptyPrivate(page);
  expect(state.errors).toEqual([]);
});
