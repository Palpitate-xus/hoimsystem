const { test, expect } = require('@playwright/test');
const { startCodingProductionServer } = require('./fixtures/coding-production-entry.cjs');
const { setupOperationsProduction } = require('./fixtures/operations-support-production-entry.cjs');
test.describe.configure({ mode: 'default' });
let server;
test.beforeAll(async () => { server = await startCodingProductionServer(); });
test.afterAll(async () => { try { expect(server.unhandled).toEqual([]); } finally { await server.close(); } });

async function documentSession(page, { sections = true } = {}) {
  const writes = [];
  await page.addInitScript(() => {
    localStorage.setItem('hoim-token', 'synthetic-writing-review');
    Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText: async text => { window.__reviewCopied = text; } } });
  });
  await page.context().route('**/*', route => new URL(route.request().url()).origin === server.origin ? route.continue() : route.abort());
  await page.route('**/api/**', async route => {
    const request = route.request(), path = new URL(request.url()).pathname;
    let data = [];
    if (path === '/api/userInfo') data = { username: '合成医生', permissions: ['doctor'], avatar: '' };
    if (path === '/api/ai/features') data = [{ key: 'outpatient_note', number: 22, name: '门诊病历草稿', scope: 'patient', engine: 'llm', enabled: true, inputs: ['当前记录'], deliverables: ['文书正文'], allowed_roles: ['doctor'], validation_status: 'validated' }];
    if (path === '/api/ai/patients') data = [{ patient_id: 1, label: '合成病例甲' }, { patient_id: 2, label: '合成病例乙' }];
    if (path === '/api/ai/runs' && request.method() === 'POST') data = { run_id: 'synthetic-document-copy', feature_key: 'outpatient_note', feature_name: '门诊病历草稿', patient_id: 1, status: 'queued' };
    if (path === '/api/ai/runs/synthetic-document-copy') data = {
      run_id: 'synthetic-document-copy', feature_key: 'outpatient_note', feature_name: '门诊病历草稿', patient_id: 1, status: 'succeeded', prompt_version: 0, provider_revision: 1,
      result: { summary: '范围说明，不属于文书正文', warnings: ['核对原始检查记录'], missing_data: ['尚未取得检查结果'], sections: sections ? [
        { title: '主诉', content: '\uFEFF原记录\r\n🧪e\u0301，0，不详', source_ids: [] },
        { title: '现病史', content: '另一个待选择的正文栏目', source_ids: [] },
      ] : [] }, evidence: [],
    };
    if (request.method() !== 'GET' && path !== '/api/userInfo') writes.push({ path, body: request.postDataJSON() });
    await route.fulfill({ status: 200, json: { code: 200, msg: 'synthetic only', data } });
  });
  await page.goto(server.origin + '/#/ai/workbench?feature=outpatient_note&patient_id=1');
  await page.getByRole('button', { name: '生成辅助建议', exact: true }).click();
  await expect(page.getByRole('heading', { name: '文书正文', exact: true })).toBeVisible();
  return writes;
}

test('copying clinical text requires review and copies only explicitly selected sections', async ({ page }) => {
  const writes = await documentSession(page);
  await page.getByRole('button', { name: '复制文书正文', exact: true }).click();
  const dialog = page.getByRole('dialog', { name: '复制文书正文', exact: true });
  const copy = dialog.getByRole('button', { name: '复制选中正文', exact: true });
  await expect(copy).toBeDisabled();
  await expect(dialog).toContainText('尚未取得检查结果');
  await dialog.getByRole('checkbox', { name: '现病史', exact: true }).uncheck();
  await dialog.getByRole('checkbox', { name: '我已核对上述事项和所选正文', exact: true }).check();
  await copy.click();
  await expect.poll(() => page.evaluate(() => window.__reviewCopied)).toBe('主诉\n\uFEFF原记录\r\n🧪e\u0301，0，不详');
  expect(writes.map(row => row.path)).toEqual(['/api/ai/runs']);
});

test('a summary without clinical sections cannot be copied as a completed document', async ({ page }) => {
  await documentSession(page, { sections: false });
  await expect(page.getByRole('button', { name: '复制文书正文', exact: true })).toBeDisabled();
  await expect(page.getByText('尚无可复制的文书正文，请先核对资料缺口。', { exact: true })).toBeVisible();
  expect(await page.evaluate(() => window.__reviewCopied)).toBeUndefined();
});

test('changing the patient clears the open copy scope before any clipboard operation', async ({ page }) => {
  const writes = await documentSession(page);
  await page.getByRole('button', { name: '复制文书正文', exact: true }).click();
  const dialog = page.getByRole('dialog', { name: '复制文书正文', exact: true });
  await expect(dialog).toBeVisible();
  await page.evaluate(() => { location.hash = '/ai/workbench?feature=outpatient_note&patient_id=2'; });
  await expect(dialog).not.toBeVisible();
  expect(await page.evaluate(() => window.__reviewCopied)).toBeUndefined();
  expect(writes.map(row => row.path)).toEqual(['/api/ai/runs']);
});

test('an available dedicated task has no contradictory unavailable-feature empty state', async ({ page }) => {
  const state = await setupOperationsProduction(page, server);
  await page.goto(server.origin + '/#/ai/workbench?feature=operations_support');
  await expect(page.getByRole('region', { name: '明确运维材料集输入', exact: true })).toBeVisible();
  await expect(page.getByText('当前角色暂无可用 AI 能力', { exact: true })).toHaveCount(0);
  expect(state.errors).toEqual([]);
  expect(state.external).toEqual([]);
  expect(state.seen.filter(row => row.method !== 'GET')).toEqual([]);
});
