const { selectManagementTab } = require('./fixtures/ai-management-navigation.cjs');
const { test, expect } = require('@playwright/test');
const native = require('./fixtures/surgery-synthetic/native-transitions.json').packet;
const business = require('./fixtures/surgery-synthetic/native-business.json');
const scenes = require('./fixtures/surgery-synthetic/scenarios.json');
const check = require('./fixtures/surgery-synthetic/providers-eight-kind.json').cases.model_mismatch.response.data;
const sourceMetadata = row => Object.fromEntries(Object.entries(row).filter(([key]) => !['payload', 'parent_binding', 'review_basis_note', 'revoke_reason'].includes(key)));
const source = business.operational_sources.duty.super_revoked;
const protectedBusiness = require('./fixtures/surgery-synthetic/protected-mapping.json');

// Built-application entry tests with intercepted synthetic API responses. All
// clinical/resource originals, governed lifecycle rows and pipeline outputs are
// actual isolated backend exports. Feature/user bootstrap values are UI setup.
async function setup(page, role = 'super_admin', { nativeBusiness = false, protectedEntry = false } = {}) {
  const state = { bootstrap: [], reads: [], writes: [], errors: [] };
  const feature = { key: 'surgery_scheduling', number: 65, name: '手术排台优化', category: 'operations', engine: 'optimizer', scope: 'hospital', input_mode: 'surgery', enabled: nativeBusiness, revision: 1, validation_status: nativeBusiness ? 'validated' : 'unreviewed', validation_note: '', requires_operational_validation: true, allowed_roles: ['admin', 'director', 'super_admin'], default_roles: ['admin', 'director'], inputs: ['明确病例与受审阶段资源'], deliverables: ['候选及原数学界'], prompt_version: 0, active_prompt_id: null, daily_limit: 50, setup_check: { ready: false, issues: [], scope_note: '仅隔离UI工程验证，不能代表真实运营或临床验证。' } };
  page.on('pageerror', error => state.errors.push(error.message));
  await page.addInitScript(() => localStorage.setItem('hoim-token', 'synthetic-surgery-production-entry'));
  const origin = new URL(process.env.E2E_BASE_URL || 'http://127.0.0.1:4180').origin;
  await page.context().route('**/*', route => new URL(route.request().url()).origin === origin ? route.continue() : route.abort('blockedbyclient'));
  await page.route('**/api/**', async route => {
    const req = route.request(), url = new URL(req.url()), path = url.pathname, method = req.method();
    let data = [], reply;
    if (path === '/api/userInfo') state.bootstrap.push({ method, path, body: req.postDataJSON() });
    else if (method === 'GET') state.reads.push({ path, query: Object.fromEntries(url.searchParams) });
    else state.writes.push({ method, path, body: req.postDataJSON() });
    if (path === '/api/userInfo') data = { username: '合成手术生产入口', permissions: role === 'super_admin' ? ['super_admin', 'admin'] : role === 'director' ? ['director', 'doctor'] : [role], avatar: '' };
    else if (['/api/ai/features', '/api/ai/admin/features'].includes(path)) data = [feature];
    else if (path === '/api/surgeryApplication/getList') reply = nativeBusiness ? native.legacy_applications : business.legacy_applications;
    else if (path === '/api/surgerySchedule/getList') reply = protectedEntry ? protectedBusiness.legacy_schedules : nativeBusiness ? native.legacy_schedules : business.legacy_schedules;
    else if (path === '/api/ai/surgery-sources/options') data = protectedEntry ? protectedBusiness.options : nativeBusiness ? native.source_options : business.options;
    else if (path === '/api/ai/surgery-scenarios') data = nativeBusiness ? native.scenario_directory : { ...scenes.http_states.published_directory, page_size: 20 };
    else if (path.startsWith('/api/ai/surgery-scenarios/')) data = nativeBusiness ? native.scenario_detail : scenes.http_states.revoked_super;
    else if (path === '/api/ai/admin/providers') data = [{ provider_id: check.provider_id, revision: check.provider_revision, model: check.configured_model, kind: 'specialist', supported_features: ['surgery_scheduling'], name: '合成只读手术优化服务', enabled: false, allows_patient_data: false, timeout_seconds: 110, max_output_tokens: 16000, temperature: 0, validation_report: '工程隔离声明核对，尚无实际临床或运营效果验证。' }];
    else if (path.endsWith('/surgery-capabilities')) data = check;
    else if (path.startsWith('/api/ai/surgery-sources/')) {
      const parts = path.split('/'), kind = parts[4], id = parts[5];
      data = id ? source : { items: !protectedEntry && kind === source.source_kind ? [sourceMetadata(source)] : [], total: !protectedEntry && kind === source.source_kind ? 1 : 0, page: 1, page_size: 20 };
    } else if (path.startsWith('/api/ai/surgery-registry/')) { const [, , , , kind, id] = path.split('/'); data = protectedEntry ? id ? protectedBusiness.registry_details[kind][id] : protectedBusiness.registry_lists[kind] : business.registry_lists[kind]; }
    else if (path === '/api/doctorManagement/getList') reply = protectedBusiness.doctors;
    else if (path === '/api/ai/runs') data = method === 'POST' ? native.receipt : [];
    else if (path === '/api/ai/runs/' + native.run_detail.run_id) data = native.run_detail;
    else if (path === '/api/ai/operational-context') data = native.inspection;
    else if (path === '/api/ai/surgery-protected-capsules') data = business.protected.draft;
    else if (path === '/api/departmentManagement/getList') reply = business.directories.departments;
    else if (path === '/api/user/getList') reply = business.directories.users;
    else if (path === '/api/equipment/list') reply = business.directories.equipment;
    else if (path === '/api/cssd/getList') reply = business.directories.cssd;
    await route.fulfill({ json: reply || { code: 200, msg: 'success', data } });
  });
  return state;
}
async function choose(page, label, option, container = page) { const input = container.getByRole('combobox', { name: label, exact: true }); await input.press('ArrowDown'); await page.locator('[id="' + await input.getAttribute('aria-controls') + '"]').getByRole('option', { name: option, exact: true }).click(); }
function bootstrapChecked(state) { expect(state.bootstrap).toEqual([{ method: 'POST', path: '/api/userInfo', body: { accesstoken: 'synthetic-surgery-production-entry' } }]); expect(state.errors).toEqual([]); }

test('生产手术申请实际checkbox队列进入本地完整场景，原申请不混成患者外部优化输入', async ({ page }) => {
  const state = await setup(page, 'director', { nativeBusiness: true }); await page.goto('/#/inpatient/surgery');
  const application = native.legacy_applications.data[0];
  await page.getByRole('row').filter({ hasText: application.surgery_name }).getByRole('checkbox').locator('xpath=ancestor::label[1]').click();
  await page.getByRole('button', { name: '核对所选病例的完整排程场景', exact: true }).click();
  const drawer = page.getByRole('dialog', { name: '明确原病例队列的受审排程场景', exact: true });
  await expect(drawer.getByRole('button', { name: '生成辅助建议', exact: true })).toBeDisabled();
  const row = native.scenario_detail, pool = native.source_options.pools.find(p => p.pool_id === row.pool_id);
  await choose(page, '明确手术排程资源池', pool.name + ' · 科室 #' + pool.department_id, drawer);
  await drawer.getByRole('button', { name: '核对完整场景', exact: true }).click();
  await drawer.getByRole('button', { name: '选择本条受审场景', exact: true }).click();
  await drawer.getByRole('button', { name: '生成辅助建议', exact: true }).click();
  await expect(drawer.getByLabel('AI任务结果', { exact: true })).toContainText('在明确声明范围内已证最优');
  await expect(drawer.getByLabel('手术候选逐病例排程', { exact: true })).toContainText(application.application_id);
  expect(state.writes).toEqual([{ method: 'POST', path: '/api/ai/runs', body: { feature_key: 'surgery_scheduling', input: { surgery_scenario_id: row.scenario_id, question: '' }, preview: false } }]);
  expect(state.reads.some(r => r.path === '/api/ai/service-options')).toBe(false); bootstrapChecked(state);
});

test('生产原申请专业资料入口只绑定实际application，Super技术角色不冒充临床签署', async ({ page }) => {
  const state = await setup(page); await page.goto('/#/inpatient/surgery');
  await page.getByRole('row').filter({ hasText: business.legacy_applications.data[0].surgery_name }).getByRole('button', { name: '登记手术AI原资料', exact: true }).click();
  const dialog = page.getByRole('dialog', { name: '明确原申请的手术专业资料', exact: true });
  await expect(dialog).toContainText(business.legacy_applications.data[0].application_id);
  await expect(dialog.getByRole('region', { name: '手术受控原件与资源登记治理', exact: true })).toBeVisible();
  await choose(page, '原资料类型', '病例明确需求', dialog);
  await expect(dialog).toContainText('实际医师别名');
  await expect(dialog.getByRole('button', { name: '登记明确原件草稿', exact: true })).toBeDisabled();
  expect(state.writes).toEqual([]); bootstrapChecked(state);
});

test('生产Super按需加载原资料与完整场景治理，撤销原件可审计且不供新选择', async ({ page }) => {
  const state = await setup(page); await page.goto('/#/ai/manage');
  await expect(page.getByRole('region', { name: 'AI 管理导航', exact: true })).toBeVisible();
  expect(state.reads.some(r => r.path.includes('/surgery-sources') || r.path.includes('/surgery-scenarios'))).toBe(false);
  await selectManagementTab(page, '手术原资料与资源治理');
  await choose(page, '明确手术资源池', business.pool.payload.name + ' · #' + business.identity.department_id);
  await page.getByRole('button', { name: '核对完整原件', exact: true }).click();
  const original = page.getByRole('article', { name: '手术原件完整核对', exact: true });
  await expect(original).toContainText(source.content_hash); await original.getByRole('button', { name: '展开完整院内冻结原件', exact: true }).click();
  await expect(original.getByRole('textbox', { name: '完整院内手术原件', exact: true })).toHaveValue(JSON.stringify(source, null, 2));
  await selectManagementTab(page, '完整手术排程场景治理');
  await page.getByRole('button', { name: '核对完整场景', exact: true }).click();
  const scene = page.getByRole('article', { name: '受审完整手术场景原件', exact: true });
  await expect(scene).toContainText(scenes.http_states.revoked_super.content_hash); await expect(scene).toContainText('当前不能执行新候选任务');
  await scene.getByRole('button', { name: '展开完整院内场景原件', exact: true }).click();
  await expect(scene.getByRole('textbox', { name: '完整院内场景原件', exact: true })).toHaveValue(JSON.stringify(scenes.http_states.revoked_super, null, 2));
  await expect(scene.getByRole('button', { name: '选择本条受审场景', exact: true })).toHaveCount(0);
  expect(state.writes).toEqual([]); bootstrapChecked(state);
});

test('生产Super只读核对手术服务并回填实际模型，仍等待人工保存与运营验证', async ({ page }) => {
  const state = await setup(page); await page.goto('/#/ai/manage'); await selectManagementTab(page, '模型服务');
  await page.getByRole('button', { name: '检查本地手术排程服务', exact: true }).click();
  const dialog = page.getByRole('dialog', { name: '本地手术候选优化服务核对', exact: true });
  await expect(dialog).toContainText(check.capabilities.runtime_digest); await dialog.getByRole('button', { name: '填写实际模型，待保存', exact: true }).click();
  await expect(page.getByRole('dialog', { name: '编辑模型服务', exact: true }).getByPlaceholder('服务端实际提供的模型名称', { exact: true })).toHaveValue(check.capabilities.model_version);
  expect(state.writes).toEqual([{ method: 'POST', path: `/api/ai/admin/providers/${check.provider_id}/surgery-capabilities`, body: { expected_revision: check.provider_revision } }]); bootstrapChecked(state);
});

test('生产普通管理员不能借管理页入口读取手术独立治理原件', async ({ page }) => {
  const state = await setup(page, 'admin'); await page.goto('/#/ai/manage'); await expect(page).toHaveURL(/#\/404/);
  expect(state.reads.some(r => r.path.startsWith('/api/ai/admin') || r.path.includes('/surgery-sources') || r.path.includes('/surgery-scenarios'))).toBe(false); expect(state.writes).toEqual([]); bootstrapChecked(state);
});


test('生产真实旧排台行进入安全忙时映射，实际房间别名核对后仍须明确UTC，不从naive时钟补值', async ({ page }) => {
  const state = await setup(page, 'super_admin', { protectedEntry: true }); await page.goto('/#/inpatient/surgery');
  const row = protectedBusiness.legacy_schedules.data[0], b = protectedBusiness.requests.room;
  await page.getByRole('row').filter({ hasText: row.surgery_name }).filter({ hasText: row.operating_room }).getByRole('button', { name: '登记原排台资源占用', exact: true }).click();
  const outer = page.getByRole('dialog', { name: '按原业务排台登记受控资源占用', exact: true });
  await expect(outer).toContainText(row.schedule_id);
  const pool = protectedBusiness.options.pools.find(p => p.pool_id === b.pool_id);
  await choose(page, '明确手术资源池', pool.name + ' · #' + pool.department_id, outer);
  await outer.getByRole('button', { name: '按业务原执行映射登记安全忙时', exact: true }).click();
  const dialog = page.getByRole('dialog', { name: '登记明确手术来源草稿', exact: true });
  await choose(page, '原执行参与位置', '原手术室', dialog);
  await choose(page, '明确映射的物理资源', 'room · ' + b.resource_id, dialog);
  await choose(page, '本条原执行专属房间映射', '本条原执行映射 · ' + b.room_alias_id, dialog);
  await expect(dialog).toContainText(JSON.stringify(row.operating_room));
  await expect(dialog.getByRole('textbox', { name: '原区间开始UTC', exact: true })).toHaveValue('');
  await expect(dialog.getByRole('button', { name: '保存原件草稿，等待审核', exact: true })).toBeDisabled();
  expect(state.reads.some(r => r.path.endsWith('/room_alias/' + b.room_alias_id))).toBe(true);
  expect(state.writes).toEqual([]); bootstrapChecked(state);
});
