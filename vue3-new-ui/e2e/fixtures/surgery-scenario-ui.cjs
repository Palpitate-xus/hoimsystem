const { expect } = require('@playwright/test');
const F = require('./surgery-synthetic/scenario-form.json');
const enumLabels = { all_required_then_min_declared_cost: '必须病例为硬要求后最小声明成本', max_optional_scheduled_then_min_declared_cost: '必须病例为硬要求后最大可选安排数再最小成本', confirmed: '本件已明确核实用途', excluded: '本件明确排除用途', verified_distinct_groups: '整个自然人组经明确核实互异', reviewed_policies: '已审阅实际政策全集', true: '原明确是（true）', false: '原明确否（false）', unknown: '原未知（unknown）', not_recorded: '原未记录（not_recorded）', not_applicable: '原不适用（not_applicable）', verified: '原已核实（verified）', not_verified: '原未核实（not_verified）', available: '原可用（available）', unavailable: '原不可用（unavailable）', attested_complete: '原明确核实完整（attested_complete）', incomplete: '原不完整（incomplete）', attested_not_required: '原明确不需要其他要求' };

async function setupScenario(page, harness, config = {}) {
  const state = { role: 'director', governance: false, list: F.ui_extras.initial_directory.data, options: F.ui_extras.director_options.data, detail: F.http_states.published_ordinary, preview: F.ui_extras.preview.data, create: F.http_states.draft_ordinary, review: F.http_states.published_super, revoke: F.http_states.revoked_ordinary, writes: [], reads: [], errors: [], releases: {}, completed: [], ...config };
  page.__surgeryScenarioState = state;
  page.on('pageerror', error => state.errors.push(error.message));
  await page.context().route('**/*', route => new URL(route.request().url()).origin === harness.origin ? route.continue() : route.abort('blockedbyclient'));
  await page.route('**/api/**', async route => {
    const req = route.request(), u = new URL(req.url()), method = req.method(), path = u.pathname;
    let data;
    if (method === 'GET') {
      state.reads.push({ path, query: Object.fromEntries(u.searchParams) });
      if (path === '/api/ai/surgery-sources/options') data = state.options;
      else if (path === '/api/ai/surgery-scenarios') data = state.list;
      else if (path.startsWith('/api/ai/surgery-scenarios/')) data = state.detail;
    } else {
      const body = req.postDataJSON(); state.writes.push({ path, body });
      if (path === '/api/ai/surgery-sources/preview') data = state.preview;
      else if (path === '/api/ai/surgery-scenarios') data = state.create;
      else if (path.endsWith('/review')) data = state.review;
      else if (path.endsWith('/revoke')) data = state.revoke;
    }
    if (data === undefined) { state.errors.push(`Unhandled isolated ${method} ${path}`); await route.fulfill({ status: 500, json: { code: 500, msg: 'Synthetic route missing' } }); return; }
    const failure = state.failure?.(method, path, req), held = state.hold?.(method, path, req), original = structuredClone(data);
    if (held) await new Promise(resolve => state.releases[held] = resolve);
    try { await route.fulfill(failure ? { status: failure, json: { code: failure, msg: 'Synthetic current scope unavailable' } } : { json: { code: 200, data: state.mutate ? state.mutate(original, path, method) ?? original : original } }); }
    finally { if (held) state.completed.push(held); }
  });
  await page.goto(harness.origin); await page.waitForFunction(() => !!window.__surgeryProbe);
  await page.evaluate(({ role, governance, applicationIds, poolId }) => { const p = window.__surgeryProbe; p.store.commit('user/permissions', [role]); Object.assign(p.scope, { poolId, applicationIds, governance, mode: 'scenarios' }); }, { role: state.role, governance: state.governance, applicationIds: Object.hasOwn(config, 'applicationIds') ? config.applicationIds : F.ui_extras.capture_request.application_ids, poolId: F.scenario_create_request.pool_id });
  return state;
}
async function selectOption(page, input, value) {
  await input.press('ArrowDown');
  const options = page.locator('[id="' + await input.getAttribute('aria-controls') + '"]').getByRole('option');
  let option;
  if (value !== null && typeof value === 'object') option = options.filter({ hasText: value.source_record_id || value.resource_id });
  else if (typeof value === 'string' && /^[0-9a-f-]{36}$/.test(value)) option = options.filter({ hasText: value });
  else option = options.filter({ hasText: enumLabels[String(value)] || String(value) });
  await expect(option).toHaveCount(1); await option.click();
}
async function fieldInfo(field) {
  // Read only DOM component metadata to disambiguate repeated visible fields.
  // All values below are entered through real controls, never assigned to form.
  return field.evaluate(el => { const p = el.__vueParentComponent.props; return { key: p.fieldKey, fixed: p.fixedKeys.includes(p.fieldKey), label: p.label }; });
}
async function directField(field, key) {
  const children = field.locator(':scope > fieldset > .surgery-field');
  for (let i = 0; i < await children.count(); i++) { const child = children.nth(i); if ((await fieldInfo(child)).key === key) return child; }
  throw new Error('No rendered original field ' + key + ' under ' + (await fieldInfo(field)).label);
}
async function fillField(page, field, value) {
  const info = await fieldInfo(field);
  if (info.fixed) return;
  if (value === null) { const button = field.locator(':scope > .el-button').filter({ hasText: '明确为空' }); if (await button.count()) await button.click(); else await expect(field.locator(':scope > span')).toContainText('原明确为空'); return; }
  const start = field.locator(':scope > .el-button').filter({ hasText: /^(填写原值|改为填写原值)$/ }); if (await start.count()) await start.click();
  const input = field.locator(':scope > .el-form-item').getByRole('combobox');
  if (await input.count()) { await selectOption(page, input, value); return; }
  const text = field.locator(':scope > .el-form-item').getByRole('textbox');
  if (await text.count()) { await text.fill(String(value)); return; }
  if (Array.isArray(value)) {
    const rows = field.locator(':scope > fieldset > .array-item');
    if (value.length === 0 && await field.locator(':scope > fieldset > .el-button').filter({ hasText: '明确空集合' }).count()) await field.locator(':scope > fieldset > .el-button').filter({ hasText: '明确空集合' }).click();
    while (await rows.count() < value.length) await field.locator(':scope > fieldset > .el-button').filter({ hasText: '添加原条目' }).click();
    await expect(rows).toHaveCount(value.length);
    for (let i = 0; i < value.length; i++) await fillField(page, rows.nth(i).locator(':scope > .surgery-field'), value[i]);
    return;
  }
  if (typeof value === 'object') { for (const [key, child] of Object.entries(value)) { if (key === 'period' && info.label === '本件完整有限域与逐件审阅') continue; await fillField(page, await directField(field, key), child); } return; }
  // A fixed string discriminator has no editable control. It is supplied by the
  // real generated schema; the emitted full request is compared with the oracle.
  await expect(field.locator(':scope > p')).toBeVisible();
}
async function openCapture(page) {
  await page.getByRole('button', { name: '按业务明确病例捕获新场景', exact: true }).click();
  const dialog = page.getByRole('dialog', { name: '明确完整排程问题与全部原件用途', exact: true });
  const period = dialog.locator('.surgery-field').filter({ has: page.locator('legend').filter({ hasText: /^明确规划时区、日期与资料截止$/ }) }).first();
  await fillField(page, period, F.ui_extras.capture_request.period);
  return dialog;
}
async function capture(page) { const dialog = await openCapture(page); await dialog.getByRole('button', { name: '读取全部当前相关原件与物理资源', exact: true }).click(); await expect(dialog.getByText('本件完整有限域与逐件审阅', { exact: true })).toBeVisible(); return dialog; }
async function completeForm(page, dialog) {
  const form = dialog.locator('.surgery-field').filter({ has: page.locator('legend').filter({ hasText: /^本件完整有限域与逐件审阅$/ }) }).first();
  await fillField(page, form, F.scenario_create_request);
}
async function cleared(page) { expect(await page.evaluate(() => { const s = window.__surgeryProbe.component.$.setupState; return { selected: s.selected, preview: s.preview, form: s.form, action: s.action }; })).toEqual({ selected: null, preview: null, form: null, action: null }); }
module.exports = { F, setupScenario, selectOption, fillField, openCapture, capture, completeForm, cleared };
