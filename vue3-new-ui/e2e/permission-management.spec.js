const { test, expect } = require('@playwright/test');
const { beforeSourceHarness } = require('./fixtures/source-harness-setup.cjs');
const { startPermissionManagementHarness } = require('./fixtures/permission-management-harness.cjs');
let harness;
beforeSourceHarness(test, async () => { harness = await startPermissionManagementHarness(); });
test.afterAll(async () => { await harness?.close(); });
const roleNames = { super_admin: '超级管理员', admin: '管理员', doctor: '医生', director: '科室主任', nurse: '护士', pharmacist: '药师', cashier: '收费员', guide: '导诊员', lab_technician: '检验技师', registrar: '挂号员', patient: '患者' };
const roles = Object.entries(roleNames).map(([key, label]) => ({ key, label, manageable: !['super_admin', 'admin'].includes(key), scope_options: [{ value: 'existing', label: '现有业务范围' }, { value: 'assigned', label: '本人负责患者' }] }));
const permissions = Array.from({ length: 95 }, (_, i) => ({ code: `clinical:${i}`, label: `病历接口 ${i}`, module: 'clinical', module_label: '临床病历', method: i % 2 ? 'POST' : 'GET', path: `/clinical/action${i}`, default_roles: ['doctor'], action: i % 2 ? 'write' : 'read' }));
const users = [{ user_id: 1, username: 'synthetic-super', user_role: 'super_admin' }, { user_id: 2, username: 'synthetic-doctor', user_role: 'doctor' }, { user_id: 3, username: 'synthetic-other-super', user_role: 'super_admin' }];
async function open(page, { initialRoles = ['super_admin'], conflict = false } = {}) {
  const state = { calls: [], writes: [], accountWrites: [], errors: [], policies: 0 };
  page.on('pageerror', error => state.errors.push(error.message));
  await page.addInitScript(value => { window.__permissionInitial = { roles: value }; }, initialRoles);
  await page.context().route('**/*', route => new URL(route.request().url()).origin === harness.origin ? route.continue() : route.abort());
  await page.route('**/api/**', async route => {
    const request = route.request(), pathname = new URL(request.url()).pathname;
    state.calls.push({ path: pathname, method: request.method() });
    let data = [];
    if (pathname === '/api/access/catalog') data = { roles, permissions, actor: { user_id: 1, role: initialRoles[0] }, catalog_revision: 'synthetic' };
    else if (pathname === '/api/user/getList') data = users;
    else if (pathname === '/api/user/updateRole') state.accountWrites.push(request.postDataJSON());
    else if (pathname === '/api/access/audit') data = { list: [{ id: 1, actor: 'synthetic-super', subject: 'role:doctor', action: 'policy_update', created_at: '2026-10-29T12:00:00Z', detail: { version: 2 } }], total: 1 };
    else if (pathname.startsWith('/api/access/policies/')) {
      const [, kind, key] = pathname.split('/').slice(-3);
      if (request.method() === 'PUT') { state.writes.push(request.postDataJSON()); if (conflict) return route.fulfill({ status: 409, json: { code: 409, detail: 'synthetic concurrent edit' } }); data = {}; }
      else { state.policies++; data = { kind, key, label: kind === 'user' ? 'synthetic-doctor' : roleNames[key], role: 'doctor', version: state.policies, allowed_permissions: null, available_permissions: kind === 'user' ? ['clinical:0', 'clinical:1'] : permissions.map(item => item.code), effective_permissions: ['clinical:0'], data_scope: 'existing', effective_data_scope: 'assigned', disabled: false, editable: key !== 'super_admin' }; }
    }
    await route.fulfill({ json: { code: 200, data } });
  });
  await page.goto(harness.origin);
  if (initialRoles.some(role => ['admin', 'super_admin'].includes(role))) await expect(page.getByRole('tab', { name: '用户权限', exact: true })).toBeVisible();
  else await expect(page.getByText('当前账号没有权限管理权限', { exact: true })).toBeVisible();
  return state;
}
async function doctorRole(page) { await page.getByRole('tab', { name: '角色权限', exact: true }).click(); await page.getByRole('row').filter({ hasText: 'doctor' }).getByRole('button', { name: '配置权限', exact: true }).click(); await expect(page.getByRole('heading', { name: '角色权限：医生', exact: true })).toBeVisible(); }
async function custom(page) { await page.getByRole('radio', { name: '自定义权限', exact: true }).locator('..').click(); }
test('catalog supplies all 11 roles, protects super admin users and renders one permission page', async ({ page }) => {
  const state = await open(page);
  await expect(page.getByRole('row').filter({ hasText: 'synthetic-super' }).getByRole('button', { name: '用户权限', exact: true })).toBeDisabled();
  await doctorRole(page);
  await expect(page.getByRole('switch', { name: '停用访问', exact: true })).toHaveCount(0);
  await expect(page.getByRole('row')).toHaveCount(12);
  await expect(page.getByRole('group', { name: '接口权限', exact: true }).getByRole('checkbox')).toHaveCount(40);
  await expect(page.getByText('当前匹配 95 项', { exact: false })).toBeVisible();
  await page.getByRole('textbox', { name: '搜索接口权限', exact: true }).fill('/clinical/action94');
  await expect(page.getByRole('group', { name: '接口权限', exact: true }).getByRole('checkbox')).toHaveCount(1);
  expect(state.errors).toEqual([]);
});
test('role policy persists explicit API permissions and optimistic version', async ({ page }) => {
  const state = await open(page); await doctorRole(page); await custom(page);
  await page.getByRole('checkbox', { name: '病历接口 0 GET /clinical/action0', exact: true }).locator('..').click();
  await page.getByRole('checkbox', { name: '病历接口 1 POST /clinical/action1', exact: true }).locator('..').click();
  await page.getByRole('button', { name: '保存权限', exact: true }).click();
  await expect.poll(() => state.writes.length).toBe(1);
  expect(state.writes[0]).toEqual({ expected_version: 1, allowed_permissions: ['clinical:1'], data_scope: 'existing', disabled: false });
  expect(state.errors).toEqual([]);
});
test('user policy cannot exceed role permissions and explicit empty selection is preserved', async ({ page }) => {
  const state = await open(page);
  await page.getByRole('row').filter({ hasText: 'synthetic-doctor' }).getByRole('button', { name: '用户权限', exact: true }).click();
  await expect(page.getByRole('heading', { name: '用户权限：synthetic-doctor', exact: true })).toBeVisible();
  await expect(page.getByRole('dialog', { name: '用户权限：synthetic-doctor', exact: true }).getByText('本人负责患者', { exact: true })).toBeVisible(); await custom(page);
  await expect(page.getByRole('checkbox', { name: '病历接口 2 GET /clinical/action2', exact: true })).toBeDisabled();
  await page.getByRole('checkbox', { name: '病历接口 0 GET /clinical/action0', exact: true }).locator('..').click();
  await expect(page.getByText('保存后禁止全部业务接口', { exact: false })).toBeVisible();
  await page.getByRole('button', { name: '保存权限', exact: true }).click();
  await expect.poll(() => state.writes.length).toBe(1); expect(state.writes[0].allowed_permissions).toEqual([]);
});
test('conflicting save keeps the draft and requires an explicit reload', async ({ page }) => {
  const state = await open(page, { conflict: true }); await doctorRole(page); await custom(page);
  await page.getByRole('checkbox', { name: '病历接口 1 POST /clinical/action1', exact: true }).locator('..').click();
  await page.getByRole('button', { name: '保存权限', exact: true }).click();
  await expect(page.getByText('权限已被其他管理员修改。请重新加载后保存。', { exact: true })).toBeVisible();
  await expect(page.getByRole('checkbox', { name: '病历接口 1 POST /clinical/action1', exact: true })).toBeChecked();
  await expect(page.getByRole('button', { name: '保存权限', exact: true })).toBeDisabled();
  expect(state.writes).toHaveLength(1);
  await page.getByRole('button', { name: '重新加载', exact: true }).click();
  await expect(page.getByRole('button', { name: '保存权限', exact: true })).toBeEnabled();
});
test('audit is fetched on demand and losing admin identity clears the editor', async ({ page }) => {
  const state = await open(page); expect(state.calls.some(call => call.path === '/api/access/audit')).toBe(false);
  await page.getByRole('tab', { name: '权限审计', exact: true }).click(); await expect(page.getByRole('cell', { name: 'role:doctor', exact: true })).toBeVisible();
  await doctorRole(page);
  await page.evaluate(() => window.__permissionProbe.store.commit('user/permissions', ['doctor']));
  await expect(page.getByText('当前账号没有权限管理权限', { exact: true })).toBeVisible();
  await expect(page.getByRole('heading', { name: '角色权限：医生', exact: true })).toHaveCount(0);
  expect(state.writes).toEqual([]); expect(state.errors).toEqual([]);
});

test('a non administrator never requests the protected catalog or user directory', async ({ page }) => {
  const state = await open(page, { initialRoles: ['patient'] });
  await expect(page.getByRole('tab', { name: '用户权限', exact: true })).toHaveCount(0);
  expect(state.calls).toEqual([]); expect(state.errors).toEqual([]);
});

test('super admin account operations remain available while immutable policies and self role changes stay protected', async ({ page }) => {
  const state = await open(page), self = page.getByRole('row').filter({ hasText: 'synthetic-super' }), other = page.getByRole('row').filter({ hasText: 'synthetic-other-super' });
  await expect(self.getByRole('button', { name: '修改角色', exact: true })).toBeDisabled();
  await expect(self.getByRole('button', { name: '删除', exact: true })).toBeDisabled();
  await expect(other.getByRole('button', { name: '用户权限', exact: true })).toBeDisabled();
  await expect(other.getByRole('button', { name: '重置密码', exact: true })).toBeEnabled();
  await other.getByRole('button', { name: '重置密码', exact: true }).click();
  await expect(page.getByRole('dialog', { name: '重置密码', exact: true })).toBeVisible();
  await page.getByRole('button', { name: '取消', exact: true }).click();
  await page.getByRole('row').filter({ hasText: 'synthetic-doctor' }).getByRole('button', { name: '修改角色', exact: true }).click();
  await page.getByRole('combobox', { name: '新角色', exact: true }).press('ArrowDown');
  await page.getByRole('option', { name: '超级管理员', exact: true }).click();
  await page.getByRole('button', { name: '保存角色', exact: true }).click();
  await expect.poll(() => state.accountWrites).toEqual([{ user_id: 2, user_role: 'super_admin' }]);
});
test('ordinary administrators cannot manage super admin accounts or assign the super admin identity', async ({ page }) => {
  await open(page, { initialRoles: ['admin'] });
  const other = page.getByRole('row').filter({ hasText: 'synthetic-other-super' });
  for (const name of ['修改角色', '重置密码', '删除']) await expect(other.getByRole('button', { name, exact: true })).toBeDisabled();
  await page.getByRole('row').filter({ hasText: 'synthetic-doctor' }).getByRole('button', { name: '修改角色', exact: true }).click();
  await page.getByRole('combobox', { name: '新角色', exact: true }).press('ArrowDown');
  await expect(page.getByRole('option', { name: '超级管理员', exact: true })).toHaveCount(0);
});

test('API grant revocation disables account and policy writes while the administrator identity stays unchanged', async ({ page }) => {
  const state = await open(page); await doctorRole(page);
  await page.evaluate(() => window.__permissionProbe.store.commit('user/authorization', { version: 'revoked', permission_codes: [], denied_route_names: [], data_scope: 'existing' }));
  await expect(page.getByRole('button', { name: '保存权限', exact: true })).toBeDisabled();
  await expect(page.getByRole('radio', { name: '自定义权限', exact: true })).toBeDisabled();
  await page.getByRole('button', { name: '关闭', exact: true }).click();
  await page.getByRole('tab', { name: '用户权限', exact: true }).click();
  const row = page.getByRole('row').filter({ hasText: 'synthetic-doctor' });
  for (const name of ['修改角色', '重置密码', '删除']) await expect(row.getByRole('button', { name, exact: true })).toBeDisabled();
  expect(state.writes).toEqual([]); expect(state.accountWrites).toEqual([]);
});
