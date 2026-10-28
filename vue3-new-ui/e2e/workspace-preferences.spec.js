const { test, expect } = require('@playwright/test');
const { startCodingProductionServer } = require('./fixtures/coding-production-entry.cjs');

let server;
test.beforeAll(async () => { server = await startCodingProductionServer(); });
test.afterAll(async () => { await server.close(); });

async function session(page, role = 'doctor', avatar = '') {
  const state = { username: '合成用户', permissions: role === 'super_admin' ? ['super_admin', 'admin'] : [role], avatar };
  await page.addInitScript(() => localStorage.setItem('hoim-token', 'synthetic-preferences-session'));
  await page.route('**/api/**', async route => {
    const path = new URL(route.request().url()).pathname;
    if (path === '/api/events/stream') return route.fulfill({ status: 204, body: '' });
    let data = [];
    if (path === '/api/userInfo') data = state;
    if (path === '/api/ai/features') data = [
      { key: 'outpatient_note', name: '门诊病历草稿', category: 'records', engine: 'llm', scope: 'patient', enabled: true, validation_status: 'validated', allowed_roles: [role], inputs: [], deliverables: [] },
      { key: 'operations_qa', name: '医院数据问答', category: 'operations', engine: 'llm', scope: 'global', enabled: true, validation_status: 'validated', allowed_roles: [role], inputs: [], deliverables: [] },
    ];
    return route.fulfill({ json: { code: 200, msg: 'synthetic only', data } });
  });
  return state;
}

test('favorites persist per account and stay separate across role changes', async ({ page }) => {
  const identity = await session(page);
  const path = server.origin + '/#/ai/workbench?feature=outpatient_note';
  await page.goto(path);
  const favorite = page.getByRole('button', { name: '收藏任务', exact: true });
  await favorite.click();
  const common = page.getByRole('region', { name: '常用 AI 任务', exact: true });
  await expect(common.getByRole('button', { name: '门诊病历草稿', exact: true })).toBeVisible();
  await page.reload();
  await expect(page.getByRole('button', { name: '取消收藏', exact: true })).toHaveAttribute('aria-pressed', 'true');
  identity.username = '另一个合成账号';
  await page.reload();
  await expect(common).toHaveCount(0);
  await expect(favorite).toBeVisible();
  identity.username = '合成用户';
  identity.permissions = ['patient'];
  await page.reload();
  await expect(common).toHaveCount(0);
  identity.permissions = ['doctor'];
  await page.reload();
  await expect(common).toBeVisible();
  await page.getByRole('button', { name: '取消收藏', exact: true }).click();
  await expect(common).toHaveCount(0);
});

test('the task picker groups tasks and stored corruption does not break the workspace', async ({ page }) => {
  await session(page);
  await page.addInitScript(() => localStorage.setItem('hoim-ai-favorites:v1:' + encodeURIComponent(JSON.stringify(['合成用户', ['doctor']])), '{broken'));
  await page.goto(server.origin + '/#/ai/workbench?feature=outpatient_note');
  await page.locator('.feature-picker .el-select').click();
  await expect(page.getByText('病历与文书', { exact: true })).toBeVisible();
  await expect(page.getByText('运营管理', { exact: true })).toBeVisible();
  await page.getByRole('option', { name: /医院数据问答/ }).click();
  await page.getByRole('button', { name: '收藏任务', exact: true }).click();
  await expect(page.getByRole('region', { name: '常用 AI 任务', exact: true }).getByRole('button', { name: '医院数据问答', exact: true })).toBeVisible();
});

const roles = { super_admin: '超级管理员', admin: '管理员', director: '科室主任', doctor: '医生', nurse: '护士', pharmacist: '药师', cashier: '收费员', guide: '导诊员', lab_technician: '检验技师', registrar: '挂号员', patient: '患者' };
for (const [role, label] of Object.entries(roles)) test('the avatar identifies ' + role + ' and exposes only its settings entry', async ({ page }) => {
  await session(page, role);
  await page.goto(server.origin + '/#/personalCenter/personalCenter');
  const avatar = page.locator('.avatar-container:visible').first();
  await expect(avatar.locator('.user-role')).toHaveText(label);
  await expect(avatar.getByRole('img', { name: '用户头像' })).toHaveText('合');
  await avatar.click();
  const settings = page.getByRole('menuitem', { name: '系统设置', exact: true });
  if (['super_admin', 'admin'].includes(role)) {
    await expect(settings).toBeVisible();
    await settings.click();
    await expect(page).toHaveURL(/#\/system\/config/);
  } else await expect(settings).toHaveCount(0);
  await expect(page.getByText('admin@example.com', { exact: true })).toHaveCount(0);
});

test('an unavailable avatar falls back to a local initial', async ({ page }) => {
  await session(page, 'doctor', server.origin + '/broken-avatar.png');
  await page.route('**/broken-avatar.png', route => route.fulfill({ status: 404, body: '' }));
  await page.goto(server.origin + '/#/ai/workbench?feature=outpatient_note');
  await expect(page.locator('.avatar-container:visible').first().getByRole('img', { name: '用户头像' })).toHaveText('合');
});

for (const [code, title] of [['401', '当前账号没有访问权限'], ['404', '页面不存在']]) test('status ' + code + ' keeps readable navigation on a small screen', async ({ page }) => {
  await session(page);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto(server.origin + '/#/' + code);
  await expect(page.getByRole('heading', { name: title, exact: true })).toBeVisible();
  await expect(page.getByRole('link', { name: '返回首页', exact: true })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});
