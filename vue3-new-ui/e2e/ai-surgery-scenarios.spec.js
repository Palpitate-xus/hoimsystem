const { test, expect } = require('@playwright/test');
const { startSurgeryHarness } = require('./fixtures/surgery-source-harness.cjs');
const { F, setupScenario, openCapture, capture, completeForm, cleared } = require('./fixtures/surgery-scenario-ui.cjs');
let harness;
test.beforeAll(async () => { harness = await startSurgeryHarness(); });
test.afterAll(async () => { await harness?.close(); });
test.afterEach(async ({ page }, info) => {
  const s = page.__surgeryScenarioState;
  for (const release of Object.values(s?.releases || {})) release();
  if (info.status === info.expectedStatus) return;
  const value = await page.evaluate(() => { const s = window.__surgeryProbe.component?.$?.setupState; return { text: document.body.innerText.slice(-8000), form: s?.form, period: s?.period, previewDigest: s?.preview?.collection_digest, loading: s?.loading, creating: s?.creating }; }).catch(() => null);
  console.log('ISOLATED_SCENARIO_DIAGNOSTIC', JSON.stringify({ errors: s?.errors, writes: s?.writes, ui: value }));
});

test('从真实同case HTTP捕获开始，逐原件资源候选和所有声明通过实际DOM填写后完整create', async ({ page }) => {
  test.setTimeout(120000);
  const s = await setupScenario(page, harness);
  const dialog = await capture(page);
  const save = dialog.getByRole('button', { name: '保存整件草稿，等待独立审核', exact: true });
  await expect(save).toBeDisabled();
  await completeForm(page, dialog);
  await expect(save).toBeEnabled(); await save.click();
  await expect(page.getByRole('article', { name: '受审完整手术场景原件', exact: true })).toContainText(F.http_states.draft_ordinary.content_hash);
  expect(s.writes).toEqual([{ path: '/api/ai/surgery-sources/preview', body: F.ui_extras.capture_request }, { path: '/api/ai/surgery-scenarios', body: F.scenario_create_request }]);
  expect(s.errors).toEqual([]);
});
