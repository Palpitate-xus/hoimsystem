const { test, expect } = require('@playwright/test');
const { startResearchManagementHarness } = require('./fixtures/research-cohort-management-harness.cjs');
const { selectManagementTab, expectManagementEntry } = require('./fixtures/ai-management-navigation.cjs');
let harness;
test.beforeAll(async () => { harness = await startResearchManagementHarness(); });
test.afterAll(async () => { await harness?.close(); });
async function open(page) {
  const state = { calls: [], errors: [] };
  page.on('pageerror', error => state.errors.push(error.message));
  await page.context().route('**/*', route => new URL(route.request().url()).origin === harness.origin ? route.continue() : route.abort());
  await page.route('**/api/**', async route => {
    const request = route.request(), pathname = new URL(request.url()).pathname;
    state.calls.push({ path: pathname, method: request.method() });
    const data = pathname === '/api/ai/admin/features' ? [{ number: 78, key: 'infection_cluster', name: '院内感染聚集分析', category: 'knowledge', priority: 'P2', engine: 'local', scope: 'hospital', default_roles: ['super_admin'], allowed_roles: ['super_admin'], enabled: false, validation_status: 'unreviewed', prompt_version: 0, revision: 0, inputs: [], deliverables: [] }] : [];
    await route.fulfill({ json: { code: 200, msg: 'Synthetic navigation fixture', data } });
  });
  await page.goto(harness.origin);
  await expect(page.getByRole('heading', { name: 'AI 管理中心', exact: true })).toBeVisible();
  return state;
}
test('four groups and one searchable directory expose all 41 entries without starting a Source request', async ({ page }) => {
  const state = await open(page);
  const groups = page.getByRole('radiogroup', { name: '管理分组', exact: true });
  await expect(groups.getByRole('radio')).toHaveCount(4);
  const search = page.getByRole('combobox', { name: '查找管理入口', exact: true });
  await search.press('ArrowDown');
  const list = page.locator('[id="' + await search.getAttribute('aria-controls') + '"]');
  await expect(list.getByRole('option')).toHaveCount(41);
  for (const label of ['说明书原文与独立签署治理', '科研变量字典与完整批次治理', '全局技术任务', '调用统计', '患者访问授权']) await expect(list.getByRole('option', { name: label, exact: true })).toBeVisible();
  await search.press('Escape');
  expect(state.calls.map(call => call.path).sort()).toEqual(['/api/ai/admin/audit', '/api/ai/admin/features', '/api/ai/admin/grants', '/api/ai/admin/knowledge', '/api/ai/admin/providers']);
  expect(state.errors).toEqual([]);
});
test('changing group selects its content and remembers the last model configuration entry', async ({ page }) => {
  const state = await open(page);
  await selectManagementTab(page, '模型服务');
  await page.getByRole('radio', { name: '知识与数据', exact: true }).locator('..').click();
  await expect(page.locator('.management-entry-select')).toContainText('知识审核');
  await page.getByRole('radio', { name: '权限与审计', exact: true }).locator('..').click();
  await expect(page.getByRole('button', { name: '新增限时授权', exact: true })).toBeVisible();
  await page.getByRole('radio', { name: '功能与模型', exact: true }).locator('..').click();
  await expect(page.getByRole('button', { name: '新增模型服务', exact: true })).toBeVisible();
  await expect(page.locator('.management-entry-select')).toContainText('模型服务');
  expect(state.calls.every(call => call.method === 'GET')).toBe(true); expect(state.errors).toEqual([]);
});
test('searching a dedicated Source entry synchronizes its group and keeps clinical reads explicit', async ({ page }) => {
  const state = await open(page);
  await selectManagementTab(page, '病例去标识来源与人工复核治理');
  await expect(page.getByRole('radio', { name: '知识与数据', exact: true })).toBeChecked();
  await expect(page.getByLabel('病例去标识项目与患者来源入口')).toBeVisible();
  expect(state.calls.some(call => call.path.includes('/research-cohort/') || call.path.includes('/deidentification/'))).toBe(false); expect(state.errors).toEqual([]);
});
test('native configuration and Prompt shortcuts synchronize navigation without a generic model dialog', async ({ page }) => {
  const state = await open(page), row = page.getByRole('row').filter({ hasText: '院内感染聚集分析' });
  await row.getByRole('button', { name: '配置', exact: true }).click();
  await expect(page.getByRole('radio', { name: '知识与数据', exact: true })).toBeChecked();
  await expect(page.locator('.management-entry-select')).toContainText('有限病例来源与本地统计治理');
  await selectManagementTab(page, '能力与启用');
  await row.getByRole('button', { name: 'Prompt', exact: true }).click();
  await expect(page.getByRole('radio', { name: '知识与数据', exact: true })).toBeChecked(); await expect(page.getByRole('dialog')).toHaveCount(0);
  expect(state.calls.some(call => call.method !== 'GET' || call.path.includes('/prompts/'))).toBe(false); expect(state.errors).toEqual([]);
});
test('losing super administrator authority removes protected directory choices and resets current content', async ({ page }) => {
  const state = await open(page);
  await selectManagementTab(page, '病例去标识来源与人工复核治理');
  await page.evaluate(() => window.__researchManagementProbe.store.commit('user/permissions', ['admin']));
  await expect(page.locator('.management-entry-select')).toContainText('能力与启用');
  for (const label of ['病例去标识来源与人工复核治理', '说明书原文与独立签署治理', '科研变量字典与完整批次治理']) await expectManagementEntry(page, label, false);
  await expect(page.getByLabel('病例去标识项目与患者来源入口')).toHaveCount(0);
  expect(state.calls.some(call => call.path.includes('/research-cohort/') || call.path.includes('/deidentification/'))).toBe(false); expect(state.errors).toEqual([]);
});
