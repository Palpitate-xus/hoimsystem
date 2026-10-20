const { test, expect } = require("@playwright/test");
const { startAkiHarness } = require("./fixtures/aki-source-harness.cjs");
const { clone, admission, oldAdmission, windowId, profileId, pointId, assessmentId, stamp, cutoff, note, hashes, profile, laboratory, weight, urine, makeAssessment, negativeAssessment, analysisFor } = require("./fixtures/aki-fixtures.cjs");
// Actual new Vue/ElementPlus/request components on isolated loopback with API
// mocks. This suite does not test backend permissions, rule math or clinical validity.
let harness;
test.beforeAll(async () => { harness = await startAkiHarness(); });
test.afterAll(async () => { await harness?.close(); });
async function session(page, config = {}) {
  const state = { sources: [], writes: [], reads: [], modelCalls: [], releases: {}, completed: [], hold: null, canSign: true, mutateDetail: null, ...config };
  await page.context().route("**/*", route => new URL(route.request().url()).origin === harness.origin ? route.continue() : route.abort("blockedbyclient"));
  await page.route("**/api/**", async route => {
    const request = route.request(), url = new URL(request.url()), path = url.pathname, method = request.method(), query = Object.fromEntries(url.searchParams); let data = {};
    if (/\/ai\/(runs|context|admin\/features)(\/|$)/.test(path)) state.modelCalls.push(path);
    else if (method === "GET") {
      state.reads.push({ path, query });
      if (path.endsWith("/candidates")) {
        const originalAdmission = query.baseline_admission_id || admission;
        data = { window: { window_id: windowId, patient_id: 11, admission_id: admission, content_hash: hashes.window }, creatinine_sources: [laboratory(1, "1.40000000", stamp), laboratory(2, "1.00000000")], baseline_sources: originalAdmission === oldAdmission ? [laboratory(4, "1.00000000", "2019-12-01T00:00:00.123456Z", oldAdmission)] : [laboratory(3, "1.00000000")], baseline_admissions: [{ admission_id: admission, admission_no: "合成本次住院", status: 1 }, { admission_id: oldAdmission, admission_no: "合成较早原住院", status: 2 }], baseline_admission_id: originalAdmission, baseline_page: Number(query.baseline_page || 1), baseline_page_size: 50, baseline_total: 1, weight_points: [weight()], urine_intervals: urine(), rule_profiles: [profile()], can_sign_clinical: state.canSign, quality: {}, scope_note: "仅合成已授权目录" };
      } else if (path.endsWith("/risk-rule-profiles/options")) data = { items: [{ rule_id: "news2_2017", recipe_digest: "1".repeat(64), recipe: {}, input_policy: {} }, { rule_id: "kdigo_aki_2012", recipe_digest: hashes.recipe, recipe: {}, input_policy: {} }] };
      else if (path.endsWith("/risk-rule-profiles")) data = { items: [profile()], total: 1, page: 1, page_size: 50 };
      else if (/\/aki-assessments$/.test(path)) data = { items: clone(state.sources), total: state.sources.length, page: 1, page_size: 50 };
      else if (/\/news2-assessments$/.test(path)) data = { items: [], total: 0, page: 1, page_size: 50 };
      else if (path.endsWith(`/${profileId}`)) data = profile();
      else { data = clone(state.sources.find(row => row.assessment_id === path.split("/").at(-1))); state.mutateDetail?.(data); }
    } else {
      const body = request.postDataJSON(); state.writes.push({ path, body });
      if (path.endsWith("/revoke")) { const row = state.sources.find(item => item.assessment_id === path.split("/").at(-2)); Object.assign(row, { status: "revoked", revision: row.revision + 1, eligible: false, can_revoke: false, specialist_source: null }); data = clone(row); }
      else if (path.endsWith("/aki-assessments")) { data = makeAssessment(body); state.sources.push(clone(data)); }
    }
    const hold = state.hold?.(method, path); if (hold) await new Promise(resolve => { state.releases[hold] = resolve; });
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ code: 200, data, msg: "synthetic isolated AKI UI reply" }) }); if (hold) state.completed.push(hold);
  });
  await page.goto(harness.origin); await page.waitForFunction(() => !!window.__akiProbe); return state;
}
async function select(page, label, option) { const input = page.getByRole("combobox", { name: label, exact: true }); await expect(input).toBeEnabled(); await input.press("ArrowDown"); await page.locator(`#${await input.getAttribute("aria-controls")}`).getByRole("option", { name: option, exact: true }).click(); }
const labelLab = row => `${row.collected_at_utc} · ${row.snapshot.original.observation.value_num} ${row.snapshot.original.observation.unit} · ${row.lab_source_id}`;
async function draft(page) { await page.getByRole("button", { name: "登记明确原资料的成人AKI评估来源", exact: true }).click(); await page.getByRole("button", { name: "读取本窗AKI原来源与审核规则", exact: true }).click(); await select(page, "成人AKI审核规则版本", "合成KDIGO固定规则审核 · kdigo_aki_2012 · v2"); await page.getByRole("textbox", { name: "成人AKI评估时刻UTC", exact: true }).fill(stamp); await page.getByRole("textbox", { name: "成人AKI评估时年龄", exact: true }).fill("50"); await page.getByRole("textbox", { name: "成人AKI原年龄核实依据", exact: true }).fill(note); await select(page, "成人AKI基线策略", "未知基线"); await select(page, "成人AKI RRT临床声明", "未知，不作临床阴性声明"); }
async function selected(page) { await select(page, "待计算成人AKI评估来源", `${stamp} · ${assessmentId} · 活动来源`); }
const noModel = state => expect(state.modelCalls).toEqual([]);
const positiveSelections = page => page.evaluate(() => window.__akiProbe.events.filter(item => item.type === "selection" && item.value));
async function render(page, row, analysis) { await page.evaluate(({ row, analysis }) => Object.assign(window.__akiProbe.scope, { mode: "findings", source: row.specialist_source, analysis, sourceScope: row }), { row, analysis }); return page.getByLabel("成人AKI确定性标准复核", { exact: true }); }

test("成人AKI原时点、年龄、基线与RRT不预填，来源登记不自动选择或计算", async ({ page }) => {
  const state = await session(page); await page.getByRole("button", { name: "登记明确原资料的成人AKI评估来源", exact: true }).click(); for (const label of ["成人AKI评估时刻UTC", "成人AKI评估时年龄"]) await expect(page.getByRole("textbox", { name: label, exact: true })).toHaveValue(""); for (const label of ["成人AKI基线策略", "成人AKI RRT临床声明"]) await expect(page.getByRole("combobox", { name: label, exact: true })).toHaveValue(""); await expect(page.getByRole("button", { name: "仅登记成人AKI评估来源", exact: true })).toBeDisabled(); expect(state.writes).toEqual([]); expect(await positiveSelections(page)).toEqual([]); noModel(state);
});

test("尿量原0和未知收集声明保留，护士只登记明确引用不伪签肌酐或RRT", async ({ page }) => {
  const state = await session(page, { canSign: false }); await page.evaluate(() => window.__akiProbe.store.commit("user/permissions", ["nurse"])); await draft(page); await expect(page.getByRole("combobox", { name: "成人AKI index肌酐", exact: true })).toBeDisabled(); const interval = urine()[0]; await select(page, "成人AKI原尿量区间", `${interval.start_at} 至 ${interval.end_at} · 0.00000000 mL · unknown · ${interval.interval_id}`); await page.getByRole("combobox", { name: "成人AKI原尿量区间", exact: true }).press("Escape"); await page.getByRole("button", { name: "仅登记成人AKI评估来源", exact: true }).click(); await expect.poll(() => state.writes.length).toBe(1); expect(state.writes[0].body).toMatchObject({ index_creatinine: null, comparison_48h: null, baseline_creatinine: null, baseline_mode: "unknown", serum_creatinine_confirmed: false, creatinine_review_note: null, weight_point: null, weight_applicability_confirmed: false, weight_basis_note: null, urine_intervals: [{ interval_id: interval.interval_id, expected_content_hash: interval.content_hash }], rrt_status: "unknown", rrt_started_at: null, rrt_acute_aki_confirmed: null, rrt_basis_note: null }); await expect(page.getByText("成人AKI来源已登记；请明确选择并核对，尚未调用规则服务或自动计算。", { exact: true })).toBeVisible(); expect("volume_ml" in state.writes[0].body).toBe(false); expect(await positiveSelections(page)).toEqual([]); noModel(state);
});

test("肌酐用途须明确临床能力与逐项原依据，提交仅原ID摘要不替换数量单位", async ({ page }) => {
  const state = await session(page); await draft(page); await select(page, "成人AKI index肌酐", labelLab(laboratory(1, "1.40000000", stamp))); await select(page, "成人AKI 48小时比较肌酐", labelLab(laboratory(2, "1.00000000"))); await expect(page.getByRole("button", { name: "仅登记成人AKI评估来源", exact: true })).toBeDisabled(); await page.getByText("我已逐项核实所选index、比较值和基线均为实际血清或血浆肌酐，且原标本与项目身份适合比较", { exact: true }).click(); await page.getByRole("textbox", { name: "成人AKI肌酐用途临床依据", exact: true }).fill(note); await page.getByRole("button", { name: "仅登记成人AKI评估来源", exact: true }).click(); await expect.poll(() => state.writes.length).toBe(1); expect(state.writes[0].body).toMatchObject({ index_creatinine: { lab_source_id: laboratory(1, "").lab_source_id, expected_content_hash: "1".repeat(64) }, comparison_48h: { lab_source_id: laboratory(2, "").lab_source_id, expected_content_hash: "2".repeat(64) }, serum_creatinine_confirmed: true, creatinine_review_note: note }); expect(state.writes[0].body).not.toHaveProperty("value"); expect(state.writes[0].body).not.toHaveProperty("unit"); expect(await positiveSelections(page)).toEqual([]); noModel(state);
});

test("较早基线须明确原住院读取与独立临床声明，不把另一住院来源归到当前", async ({ page }) => {
  const state = await session(page); await draft(page); expect(state.reads.filter(row => row.query.baseline_admission_id)).toEqual([]); await select(page, "成人AKI基线原住院", `合成较早原住院 · ${oldAdmission}`); expect(state.reads.filter(row => row.query.baseline_admission_id)).toEqual([]); await page.getByRole("button", { name: "读取明确原住院基线目录", exact: true }).click(); const row = laboratory(4, "1.00000000", "2019-12-01T00:00:00.123456Z", oldAdmission); await select(page, "成人AKI明确基线肌酐", `${labelLab(row)} · 原住院 ${oldAdmission}`); await select(page, "成人AKI基线策略", "较早原基线及临床确认7日内急性升高"); await expect(page.getByRole("button", { name: "仅登记成人AKI评估来源", exact: true })).toBeDisabled(); await expect(page.getByLabel("成人AKI待登记原肌酐", { exact: true })).toContainText(oldAdmission); expect(state.reads.filter(item => item.query.baseline_admission_id).map(item => item.query)).toEqual([{ patient_id: "11", admission_id: admission, window_id: windowId, baseline_admission_id: oldAdmission, baseline_page: "1", baseline_page_size: "50" }]); expect(state.writes).toEqual([]); noModel(state);
});

for (const change of ["patient", "admission", "window", "session", "role", "inactive"]) {
  test(`AKI迟到登记不跨${change}恢复原来源或草稿`, async ({ page }) => {
    const state = await session(page); await draft(page); state.hold = (method, path) => method === "POST" && path.endsWith("/aki-assessments") ? "create" : null; await page.getByRole("button", { name: "仅登记成人AKI评估来源", exact: true }).click(); await expect.poll(() => !!state.releases.create).toBe(true); await page.evaluate(change => { const { scope, store } = window.__akiProbe; if (change === "patient") scope.patientId = 22; if (change === "admission") scope.admissionId = "77777777-7777-4777-8777-777777777777"; if (change === "window") scope.windowId = "88888888-8888-4888-8888-888888888888"; if (change === "session") store.commit("user/token", "new-synthetic-aki-session"); if (change === "role") store.commit("user/permissions", ["patient"]); if (change === "inactive") scope.active = false; }, change); state.releases.create(); await expect.poll(() => state.completed.includes("create")).toBe(true); await expect(page.getByText("成人AKI来源已登记；请明确选择并核对，尚未调用规则服务或自动计算。", { exact: true })).toHaveCount(0); expect(await positiveSelections(page)).toEqual([]); noModel(state);
  });
}

test("已有临床核实评估可护士明确选择，只发评估ID与摘要且不自动计算", async ({ page }) => {
  const state = await session(page, { sources: [makeAssessment()] }); await page.evaluate(() => window.__akiProbe.store.commit("user/permissions", ["nurse"])); await selected(page); await expect.poll(() => positiveSelections(page)).toEqual([{ type: "selection", value: { aki_assessment_id: assessmentId, content_hash: hashes.source } }]); await page.getByRole("button", { name: "核对所选成人AKI原来源", exact: true }).click(); const dialog = page.getByRole("dialog", { name: "成人AKI原评估来源复核", exact: true }); await expect(dialog).toContainText(stamp); await expect(dialog).toContainText("0.00000000 mL"); await expect(dialog).toContainText("原区间的平均量"); expect(state.writes).toEqual([]); noModel(state);
});

for (const mode of ["observed_within_7d", "presumed_within_7d"]) {
  test(`${mode}按实际策略限定基线原住院，只有明确推定策略允许另一已授权原住院`, async ({ page }) => {
    const row = makeAssessment({ baseline_mode: mode, baseline_rise_within_7d_confirmed: mode === "presumed_within_7d" ? true : null, baseline_review_note: mode === "presumed_within_7d" ? note : null });
    row.snapshot.baseline_creatinine.admission_id = row.snapshot.baseline_creatinine.snapshot.admission_id = oldAdmission;
    const state = await session(page, { sources: [row] });
    if (mode === "presumed_within_7d") { await selected(page); await expect.poll(() => positiveSelections(page)).toHaveLength(1); const view = await render(page, row, analysisFor(row.specialist_source)); await expect(view.getByLabel("AKI最低达到分期", { exact: true })).toContainText("至少达到AKI 1期"); await expect(view.getByLabel("AKI所选肌酐原值", { exact: true })).toContainText(oldAdmission); }
    else { await expect(page.getByRole("alert")).toContainText("目录与原患者、住院或窗口不一致"); expect(await positiveSelections(page)).toEqual([]); const view = await render(page, row, analysisFor(row.specialist_source)); await expect(view.getByRole("alert")).toContainText("冻结原资料不一致"); await expect(view.getByLabel("AKI最低达到分期", { exact: true })).toHaveCount(0); }
    noModel(state);
  });
}

for (const [name, mutate] of [
  ["缺冻结正文", row => { row.snapshot = null; }],
  ["原肌酐患者串源", row => { row.snapshot.index_creatinine.snapshot.original.order.patient_id = 22; }],
  ["原体重住院串源", row => { row.snapshot.weight_point.admission_id = oldAdmission; }],
  ["原尿量与计算投影不同", row => { row.snapshot.urine_intervals[0].payload.volume_ml = "999"; }],
  ["另一规则原版本", row => { row.snapshot.rule_profile.rule_id = "news2_2017"; }],
]) {
  test(`AKI来源${name}不能选中或显示分期`, async ({ page }) => {
    const row = makeAssessment(), state = await session(page, { sources: [row], mutateDetail: mutate }); await selected(page); await expect(page.getByRole("alert")).toContainText("不能作为当前计算来源"); expect(await positiveSelections(page)).toEqual([]); const bad = clone(row); mutate(bad); const view = await render(page, bad, analysisFor(row.specialist_source)); await expect(view.getByRole("alert")).toContainText("冻结原资料不一致"); await expect(view.getByLabel("AKI最低达到分期", { exact: true })).toHaveCount(0); noModel(state);
  });
}

test("撤销请求未完成即清除AKI当前可用选择，expected_revision不丢失", async ({ page }) => {
  const state = await session(page, { sources: [makeAssessment()], hold: (method, path) => method === "POST" && path.endsWith("/revoke") ? "revoke" : null }); await selected(page); await expect.poll(() => positiveSelections(page)).toHaveLength(1); await page.getByRole("textbox", { name: "成人AKI评估撤销依据", exact: true }).fill("合成核实原资料关联错误后撤销"); await page.getByRole("button", { name: "撤销所选成人AKI评估", exact: true }).click(); await expect.poll(() => !!state.releases.revoke).toBe(true); await expect(page.getByRole("button", { name: "核对所选成人AKI原来源", exact: true })).toHaveCount(0); expect(await page.evaluate(() => window.__akiProbe.events.at(-1))).toEqual({ type: "availability", value: false }); state.releases.revoke(); await expect(page.getByText("成人AKI原评估已撤销；旧选择不能继续计算，请重新核实来源。", { exact: true })).toBeVisible(); expect(state.writes[0].body).toEqual({ patient_id: 11, admission_id: admission, expected_revision: 1, reason: "合成核实原资料关联错误后撤销" }); noModel(state);
});

test("AKI已知肌酐阳性保留最低1期，尿量原0与未知覆盖不抹去阳性或冒称无AKI", async ({ page }) => {
  const state = await session(page), row = makeAssessment(), view = await render(page, row, analysisFor(row.specialist_source)); await expect(view.getByLabel("AKI最低达到分期", { exact: true })).toContainText("至少达到AKI 1期"); await expect(view.getByLabel("AKI八项标准与原依据", { exact: true }).locator("tbody tr")).toHaveCount(8); await expect(view.getByLabel("AKI所选原尿量区间", { exact: true })).toContainText("0.00000000 mL"); await expect(view).toContainText("不证明每小时持续少尿"); await expect(view).toContainText("不预测未来风险"); await expect(view).toContainText("资料不足"); noModel(state);
});

test("所选标准未满足仍明确不能排除AKI，不显示0期或无AKI", async ({ page }) => {
  const state = await session(page), row = negativeAssessment(), view = await render(page, row, analysisFor(row.specialist_source, "negative")); await expect(view.getByLabel("AKI所选标准未满足", { exact: true })).toContainText("不能据此排除AKI"); await expect(view.getByLabel("AKI最低达到分期", { exact: true })).toHaveCount(0); noModel(state);
});

test("AKI超出声明范围不输出分期，结果另一来源或最低分期篡改被拒绝", async ({ page }) => {
  const state = await session(page), row = makeAssessment({ age_at_evaluation_years: 17 }); let view = await render(page, row, analysisFor(row.specialist_source, "outside")); await expect(view).toContainText("超出本软件声明的成人标准范围"); await expect(view.getByLabel("AKI最低达到分期", { exact: true })).toHaveCount(0); const report = analysisFor(row.specialist_source); report.source_binding.window_id = "77777777-7777-4777-8777-777777777777"; view = await render(page, row, report); await expect(view.getByRole("alert")).toContainText("计算结果已拒绝展示"); report.source_binding = clone(row.specialist_source); report.minimum_stage = 3; await render(page, row, report); await expect(view.getByRole("alert")).toContainText("计算结果已拒绝展示"); noModel(state);
});

test("精简冻结复核正文省略自由依据仍保留全部数量和范围绑定，不从typed投影反造原正文", async ({ page }) => {
  const state = await session(page), row = makeAssessment(); row.context_projection = "aki_review_v1"; row.snapshot.provenance_note_hashes = { age_basis_note: "7".repeat(64), creatinine_review_note: "7".repeat(64) }; for (const key of ["age_basis_note", "creatinine_review_note", "baseline_review_note", "weight_basis_note", "rrt_basis_note"]) delete row.snapshot.attestation[key]; delete row.snapshot.rule_profile.recipe; delete row.snapshot.rule_profile.input_policy; const view = await render(page, row, analysisFor(row.specialist_source)); await expect(view.getByLabel("AKI最低达到分期", { exact: true })).toContainText("至少达到AKI 1期"); await expect(view.getByLabel("AKI所选肌酐原值", { exact: true })).toContainText("1.40000000"); row.snapshot.index_creatinine.snapshot.original.observation.value_num = "7.0"; await render(page, row, analysisFor(row.specialist_source)); await expect(view.getByRole("alert")).toContainText("冻结原资料不一致"); noModel(state);
});

test("没有实际临床能力的Super不能自签肌酐用途或RRT状态", async ({ page }) => {
  const state = await session(page, { canSign: false }); await page.evaluate(() => window.__akiProbe.store.commit("user/permissions", ["super_admin"])); await draft(page); await expect(page.getByRole("combobox", { name: "成人AKI index肌酐", exact: true })).toBeDisabled(); const rrt = page.getByRole("combobox", { name: "成人AKI RRT临床声明", exact: true }); await rrt.press("ArrowDown"); const list = page.locator(`#${await rrt.getAttribute("aria-controls")}`); await expect(list.getByRole("option", { name: "临床核实因AKI新启动急性RRT", exact: true })).toHaveCount(0); await expect(list.getByRole("option", { name: "临床核实未启动", exact: true })).toHaveCount(0); expect(state.writes).toEqual([]); noModel(state);
});

test("临床急性RRT声明必须原启动UTC、AKI适应证及原依据，不能从医嘱推断", async ({ page }) => {
  const state = await session(page); await draft(page); await select(page, "成人AKI RRT临床声明", "临床核实因AKI新启动急性RRT"); await expect(page.getByRole("button", { name: "仅登记成人AKI评估来源", exact: true })).toBeDisabled(); await page.getByRole("textbox", { name: "成人AKI RRT原启动UTC", exact: true }).fill(stamp); await page.getByRole("textbox", { name: "成人AKI RRT原临床依据", exact: true }).fill(note); await expect(page.getByRole("button", { name: "仅登记成人AKI评估来源", exact: true })).toBeDisabled(); await page.getByText("我已核实为因AKI新启动急性RRT，非维持性治疗或仅有医嘱", { exact: true }).click(); await page.getByRole("button", { name: "仅登记成人AKI评估来源", exact: true }).click(); await expect.poll(() => state.writes.length).toBe(1); expect(state.writes[0].body).toMatchObject({ rrt_status: "acute_initiated_for_aki", rrt_started_at: stamp, rrt_acute_aki_confirmed: true, rrt_basis_note: note }); expect(await positiveSelections(page)).toEqual([]); noModel(state);
});

test("切换基线原住院后旧目录迟到不能带回另一住院候选或自动选择", async ({ page }) => {
  const state = await session(page); await draft(page); await select(page, "成人AKI基线原住院", `合成较早原住院 · ${oldAdmission}`); state.hold = (method, path) => method === "GET" && path.endsWith("/candidates") ? "baseline" : null; await page.getByRole("button", { name: "读取明确原住院基线目录", exact: true }).click(); await expect.poll(() => !!state.releases.baseline).toBe(true); await select(page, "成人AKI基线原住院", `合成本次住院 · ${admission}`); state.releases.baseline(); await expect.poll(() => state.completed.includes("baseline")).toBe(true); const input = page.getByRole("combobox", { name: "成人AKI明确基线肌酐", exact: true }); await input.press("ArrowDown"); await expect(page.locator(`#${await input.getAttribute("aria-controls")}`).getByRole("option")).toHaveCount(0); expect(state.writes).toEqual([]); expect(await positiveSelections(page)).toEqual([]); noModel(state);
});

test("Super全院AKI审计独立显示原0和临床声明，迟到旧详情不混入NEWS2目录", async ({ page }) => {
  const state = await session(page, { sources: [makeAssessment()] }); await page.evaluate(() => { window.__akiProbe.store.commit("user/permissions", ["super_admin"]); window.__akiProbe.scope.mode = "management"; }); const panel = page.getByLabel("固定风险规则与评估来源治理", { exact: true }); await panel.getByRole("tab", { name: "成人AKI评估全院审计", exact: true }).click(); await panel.getByRole("button", { name: "核对冻结成人AKI评估", exact: true }).click(); const dialog = page.getByRole("dialog", { name: "成人AKI冻结评估审计", exact: true }); await expect(dialog.getByLabel("AKI审计冻结原尿量", { exact: true })).toContainText("0.00000000 mL"); await expect(dialog).toContainText(note); await expect(dialog).toContainText(stamp); await dialog.getByRole("button", { name: "关闭", exact: true }).click(); state.hold = (method, path) => method === "GET" && path === `/api/ai/admin/aki-assessments/${assessmentId}` ? "detail" : null; await panel.getByRole("button", { name: "核对冻结成人AKI评估", exact: true }).click(); await expect.poll(() => !!state.releases.detail).toBe(true); await dialog.getByRole("button", { name: "关闭", exact: true }).click(); await panel.getByRole("tab", { name: "NEWS2评估全院审计", exact: true }).click(); state.releases.detail(); await expect.poll(() => state.completed.includes("detail")).toBe(true); await expect(dialog).toBeHidden(); await expect(panel.getByRole("button", { name: "核对冻结成人AKI评估", exact: true })).toHaveCount(0); expect(state.reads.some(row => row.path === "/api/ai/admin/news2-assessments")).toBe(true); expect(state.writes).toEqual([]); noModel(state);
});

test("AKI报告精确原差值或选段总量与冻结原量矛盾时拒绝展示", async ({ page }) => {
  const state = await session(page), row = makeAssessment(), report = analysisFor(row.specialist_source); report.criteria[0].evidence.absolute_change = "99.9"; const view = await render(page, row, report); await expect(view.getByRole("alert")).toContainText("计算结果已拒绝展示"); const complete = negativeAssessment(), negative = analysisFor(complete.specialist_source, "negative"); negative.criteria[3].evidence.total_volume_ml = "0"; await render(page, complete, negative); await expect(view.getByRole("alert")).toContainText("计算结果已拒绝展示"); noModel(state);
});

test("尿量标准声称已满足却没有任何原区间证据链时拒绝分期", async ({ page }) => {
  const state = await session(page), row = makeAssessment(), report = analysisFor(row.specialist_source); report.criteria[3].status = "met"; report.criteria[3].stage = 1; const view = await render(page, row, report); await expect(view.getByRole("alert")).toContainText("计算结果已拒绝展示"); await expect(view.getByLabel("AKI最低达到分期", { exact: true })).toHaveCount(0); noModel(state);
});

test("完整原尿量子段支持阳性时仍展示其他覆盖缺口，不将区间均值说成逐小时持续", async ({ page }) => {
  const state = await session(page), row = negativeAssessment(), source = row.specialist_source;
  row.snapshot.urine_intervals[0].payload.volume_ml = source.urine_intervals[0].volume_ml = "0.00000000";
  row.snapshot.urine_coverage_issues = source.urine_coverage_issues = ["gap"];
  const later = clone(row.snapshot.urine_intervals[0]); later.interval_id = "61000000-0000-4000-8000-000000000001"; later.source_id = `urine_interval:${later.interval_id}:${later.content_hash.slice(0, 12)}`; later.start_at = "2020-01-02T06:00:00.123456Z"; later.end_at = "2020-01-02T07:00:00.123456Z"; later.payload.volume_ml = "100.00000000"; row.snapshot.urine_intervals.push(later); row.snapshot.attestation.urine_intervals.push({ interval_id: later.interval_id, expected_content_hash: later.content_hash }); source.urine_intervals.push({ interval_id: later.interval_id, source_id: later.source_id, content_hash: later.content_hash, governance_hash: later.governance_hash, start_at: later.start_at, end_at: later.end_at, recorded_at: later.recorded_at, ...later.payload });
  row.evaluation_at = row.snapshot.evaluation_at = row.snapshot.attestation.evaluation_at = source.evaluation_at = row.snapshot.window_binding.end_at = source.end_at = "2020-01-02T12:00:00.123456Z";
  const report = analysisFor(source, "negative"); for (const item of report.criteria.slice(3, 7)) { item.status = "met"; item.stage = item.key === "urine_6h" ? 1 : item.key === "urine_12h" ? 2 : 3; item.evidence.total_volume_ml = "0"; item.evidence.rate_numerator = item.key === "anuria_12h" ? null : "0"; item.evidence.rate_denominator = item.key === "anuria_12h" ? null : "1"; item.evidence.coverage_issues = ["gap"]; } Object.assign(report, { detection: "met", minimum_stage: 3, stage_is_lower_bound: false }); const view = await render(page, row, report); await expect(view.getByLabel("AKI最低达到分期", { exact: true })).toContainText("至少达到AKI 3期"); await expect(view).toContainText("选段复核覆盖缺口：gap"); await expect(view).toContainText("不证明每小时持续少尿"); noModel(state);
});

test.afterEach(async () => { expect(harness.unhandled).toEqual([]); });
