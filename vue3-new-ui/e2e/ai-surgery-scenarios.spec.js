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

async function inspect(page) { await page.getByRole('button', { name: '核对完整场景', exact: true }).first().click(); await expect(page.getByRole('article', { name: '受审完整手术场景原件', exact: true })).toBeVisible(); }
const note = F.scenario_create_request.problem_coverage.basis_note;
const publishConfig = { role: 'super_admin', governance: true, options: F.ui_extras.super_options.data, list: F.ui_extras.publish_draft_directory.data, detail: F.ui_extras.publish_super_draft.data };

for (const decision of ['publish', 'reject']) test(`Super实际完整草稿独立${decision}，CAS原版本和本次治理依据不丢`, async ({ page }) => {
  const rejecting = decision === 'reject', services = F.additional_service_states;
  const detail = rejecting ? services.rejected_super_draft : F.ui_extras.publish_super_draft.data;
  const s = await setupScenario(page, harness, { ...publishConfig, ...(rejecting ? { list: services.rejected_directory.data, detail, review: services.rejected_super } : {}) });
  await inspect(page);
  await page.getByRole('button', { name: rejecting ? '审核拒绝完整场景' : '审核发布完整场景', exact: true }).click();
  const dialog = page.getByRole('dialog', { name: '独立完整场景治理', exact: true });
  await dialog.getByRole('textbox', { name: '本次完整场景治理依据', exact: true }).fill(note);
  await dialog.getByRole('button', { name: '保存本次完整场景治理', exact: true }).click();
  await expect(page.getByRole('article', { name: '受审完整手术场景原件', exact: true })).toContainText(rejecting ? '审核拒绝' : '已审核发布');
  expect(s.writes).toEqual([{ path: `/api/ai/surgery-scenarios/${detail.scenario_id}/review`, body: { expected_revision: 1, expected_content_hash: detail.content_hash, basis_note: note, decision } }]);
  expect(await page.evaluate(() => window.__surgeryProbe.events.filter(e => e.type === 'scenario-changed').length)).toBe(1); expect(s.errors).toEqual([]);
});

test('原作者真实撤销完整场景，1000码点UTF8边界明确且普通回执不恢复私有正文', async ({ page }) => {
  const s = await setupScenario(page, harness, { list: F.ui_extras.publish_draft_directory.data }); await inspect(page);
  await page.getByRole('button', { name: '按原版本撤销完整场景', exact: true }).click();
  const dialog = page.getByRole('dialog', { name: '独立完整场景治理', exact: true }), input = dialog.getByRole('textbox', { name: '本次完整场景治理依据', exact: true }), save = dialog.getByRole('button', { name: '保存本次完整场景治理', exact: true });
  await input.fill('a'.repeat(1001)); await expect(save).toBeDisabled(); await input.fill('🩺'.repeat(1000)); await expect(save).toBeEnabled();
  await input.fill(note); await save.click();
  const original = page.getByRole('article', { name: '受审完整手术场景原件', exact: true }); await expect(original).toContainText('当前私有原件、本地身份映射及公开投影均已隐去');
  await expect(original.getByRole('button', { name: '展开完整院内场景原件', exact: true })).toHaveCount(0);
  expect(s.writes[0]).toEqual({ path: `/api/ai/surgery-scenarios/${F.http_states.published_ordinary.scenario_id}/revoke`, body: { expected_revision: 2, expected_content_hash: F.http_states.published_ordinary.content_hash, basis_note: note } }); expect(s.errors).toEqual([]);
});

test('合法旧治理回执也不能替代本次不同basis，完整hash有效仍清除并要求重新核对', async ({ page }) => {
  const s = await setupScenario(page, harness, publishConfig); await inspect(page); await page.getByRole('button', { name: '审核发布完整场景', exact: true }).click();
  const dialog = page.getByRole('dialog', { name: '独立完整场景治理', exact: true }); await dialog.getByRole('textbox', { name: '本次完整场景治理依据', exact: true }).fill(note + ' 此为另一次明确核对依据，不能接受原来回执。'); await dialog.getByRole('button', { name: '保存本次完整场景治理', exact: true }).click();
  await expect(page.getByRole('alert').filter({ hasText: '完整场景治理依据未绑定本次明确提交' })).toBeVisible(); await cleared(page);
  expect(await page.evaluate(() => window.__surgeryProbe.events.some(e => e.type === 'scenario-changed'))).toBe(false); expect(s.errors).toEqual([]);
});

for (const audit of [false, true]) test(`真实失效父集合在${audit ? 'Super冻结审计' : '普通读取'}保留准确全文权限且不能选择`, async ({ page }) => {
  const services = F.additional_service_states;
  const s = await setupScenario(page, harness, { role: audit ? 'super_admin' : 'director', governance: audit, options: audit ? F.ui_extras.super_options.data : F.ui_extras.director_options.data, list: services.stale_directory.data, detail: audit ? services.stale_super : services.stale_ordinary });
  await inspect(page); const article = page.getByRole('article', { name: '受审完整手术场景原件', exact: true });
  await expect(article).toContainText('当前不能执行新候选任务');
  if (audit) { await article.getByRole('button', { name: '展开完整院内场景原件', exact: true }).click(); await expect(article.getByRole('textbox', { name: '完整院内场景原件', exact: true })).toHaveValue(JSON.stringify(services.stale_super, null, 2)); }
  else { await expect(article).toContainText('当前私有原件、本地身份映射及公开投影均已隐去'); await expect(article.getByRole('button', { name: '选择本条受审场景', exact: true })).toBeDisabled(); }
  expect(s.writes).toEqual([]); expect(s.errors).toEqual([]);
});

async function armActualCrypto(page) {
  await page.evaluate(() => {
    const p = window.__surgeryProbe, original = crypto.subtle.digest.bind(crypto.subtle);
    p.cryptoGate = { entered: false, returned: false };
    let release; const wait = new Promise(resolve => { release = resolve; }); p.releaseCrypto = release;
    crypto.subtle.digest = async (...args) => { const value = original(...args); if (!p.cryptoGate.entered) { p.cryptoGate.entered = true; const result = await value; await wait; p.cryptoGate.returned = true; return result; } return value; };
  });
}
for (const change of ['close', 'period']) test(`合法preview实际SHA等待中${change}后旧捕获不能恢复完整form`, async ({ page }) => {
  const s = await setupScenario(page, harness), dialog = await openCapture(page); await armActualCrypto(page);
  await dialog.getByRole('button', { name: '读取全部当前相关原件与物理资源', exact: true }).click(); await page.waitForFunction(() => window.__surgeryProbe.cryptoGate.entered);
  if (change === 'close') await dialog.getByRole('button', { name: '关闭', exact: true }).click(); else await dialog.getByRole('textbox', { name: '原资料可得截止UTC', exact: true }).fill('2026-10-20T12:00:00.123457Z');
  await page.evaluate(() => window.__surgeryProbe.releaseCrypto());
  expect(await page.evaluate(async original => window.__surgeryProbe.scenarios.verifySurgeryCollection(original), F.ui_extras.preview.data)).toBe(true);
  expect(await page.evaluate(() => { const s = window.__surgeryProbe.component.$.setupState; return { creating: s.creating, loading: s.loading, preview: s.preview, form: s.form }; })).toEqual({ creating: change !== 'close', loading: false, preview: null, form: null });
  expect(s.writes).toEqual([{ path: '/api/ai/surgery-sources/preview', body: F.ui_extras.capture_request }]); expect(s.errors).toEqual([]);
});

for (const change of ['token', 'role', 'deactivate']) test(`完整场景已读后${change}清除原文，旧详情晚到不恢复`, async ({ page }) => {
  const s = await setupScenario(page, harness, { list: F.ui_extras.publish_draft_directory.data }); await inspect(page);
  s.hold = (m, p) => m === 'GET' && p.startsWith('/api/ai/surgery-scenarios/') ? 'old-detail' : null;
  await page.getByRole('button', { name: '核对完整场景', exact: true }).first().click(); await expect.poll(() => !!s.releases['old-detail']).toBe(true);
  await page.evaluate(change => { const p = window.__surgeryProbe; if (change === 'token') p.store.commit('user/token', 'later-scene-session'); else if (change === 'role') p.store.commit('user/permissions', ['doctor']); else p.scope.mounted = false; }, change);
  s.releases['old-detail'](); await expect.poll(() => s.completed.includes('old-detail')).toBe(true); await cleared(page); expect(s.errors).toEqual([]);
});

for (const phase of ['list', 'detail', 'governance']) for (const status of [403, 409]) test(`场景当前${phase}${status}清除全文及选择并向父层invalidate`, async ({ page }) => {
  const s = await setupScenario(page, harness, { ...publishConfig }); await inspect(page);
  s.failure = (m, p) => phase === 'list' ? p === '/api/ai/surgery-scenarios' ? status : null : phase === 'detail' ? m === 'GET' && p.startsWith('/api/ai/surgery-scenarios/') ? status : null : m === 'POST' && p.endsWith('/review') ? status : null;
  if (phase === 'list') await page.getByRole('button', { name: '重新读取完整场景目录', exact: true }).click();
  else if (phase === 'detail') await page.getByRole('button', { name: '核对完整场景', exact: true }).first().click();
  else { await page.getByRole('button', { name: '审核发布完整场景', exact: true }).click(); const d = page.getByRole('dialog', { name: '独立完整场景治理', exact: true }); await d.getByRole('textbox', { name: '本次完整场景治理依据', exact: true }).fill(note); await d.getByRole('button', { name: '保存本次完整场景治理', exact: true }).click(); }
  await cleared(page); expect(await page.evaluate(() => window.__surgeryProbe.events.some(e => e.type === 'invalidate'))).toBe(true); expect(s.errors).toEqual([]);
});
