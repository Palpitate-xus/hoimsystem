const { test, expect } = require("@playwright/test");
// API mocks test workflow binding and presentation only, not a risk model.
const copy = value => JSON.parse(JSON.stringify(value));
const admission = "d1000000-0000-4000-8000-000000000001", secondAdmission = "d2000000-0000-4000-8000-000000000002";
function windowFixture(id, patient = 1, encounter = admission, hash = "a") {
  const snapshot = {
    schema_version: "inpatient_window_v1", window_id: id, patient_id: patient, admission_id: encounter,
    created_by: 1, created_at: "2026-10-20T00:00:01.123456Z", start_at: "2026-10-19T00:00:00.123456Z", end_at: "2026-10-19T01:00:00.123456Z", as_of: "2026-10-20T00:00:00.123456Z",
    snapshot_basis: "current_snapshot_retrospective", point_interval_semantics: "[start,end]", content_hash: hash.repeat(64), source_id: `observation_window:${id}:${hash.repeat(12)}`,
    points: [{ observation_id: "a1000000-0000-4000-8000-000000000001", patient_id: patient, admission_id: encounter, observed_at: "2026-10-19T00:00:00.123456Z", recorded_at: "2026-10-19T00:01:00.654321Z", status: "active", source_id: "inpatient_observation:a1000000-0000-4000-8000-000000000001:111111111111", payload: { measurements: { heart_rate: { value: "0", unit: "/min", absent_reason: null }, respiratory_rate: { value: null, unit: "/min", absent_reason: "not_performed" } }, supplemental_oxygen: "unknown", oxygen_device: null, consciousness: null } }],
    urine_intervals: [
      { interval_id: "b1000000-0000-4000-8000-000000000001", patient_id: patient, admission_id: encounter, start_at: "2026-10-19T00:00:00.123456Z", end_at: "2026-10-19T00:40:00.123456Z", recorded_at: "2026-10-19T00:41:00.123456Z", status: "active", source_id: "urine_interval:b1000000-0000-4000-8000-000000000001:222222222222", payload: { volume_ml: "0", absent_reason: null, collection_completeness: "complete", patient_total: true } },
      { interval_id: "b2000000-0000-4000-8000-000000000002", patient_id: patient, admission_id: encounter, start_at: "2026-10-19T00:30:00.123456Z", end_at: "2026-10-19T01:00:00.123456Z", recorded_at: "2026-10-19T01:01:00.123456Z", status: "active", source_id: "urine_interval:b2000000-0000-4000-8000-000000000002:333333333333", payload: { volume_ml: null, absent_reason: "unknown", collection_completeness: "partial", patient_total: null } },
    ],
    quality: { continuous_monitoring_confirmed: false, sampling_completeness: "not_verified", missing_by_point: [{ source_id: "inpatient_observation:a1000000-0000-4000-8000-000000000001:111111111111", not_recorded: ["spo2", "body_weight"], explicitly_unmeasured: ["respiratory_rate"] }], same_time_groups: [{ observed_at: "2026-10-19T00:00:00.123456Z", measurement_code: "heart_rate", source_ids: ["synthetic-a", "synthetic-b"], state: "conflicting_values_or_missing_state" }], measurement_gaps: [{ measurement_code: "heart_rate", unique_numeric_observation_times: 1, first_at: "2026-10-19T00:00:00.123456Z", last_at: "2026-10-19T00:00:00.123456Z", max_observed_gap_seconds: null, leading_gap_seconds: 0, trailing_gap_seconds: 3600 }], urine: { overlap_groups: [{ source_ids: ["synthetic-urine-a", "synthetic-urine-b"] }], excluded_intervals: [{ source_id: "synthetic-urine-a", reasons: ["overlapping_intervals"] }], uncovered_intervals: [{ start_at: "2026-10-19T00:00:00.123456Z", end_at: "2026-10-19T01:00:00.123456Z" }], volume_aggregation_performed: false, rate_calculation_performed: false } },
    lab_input_status: "not_available_requires_explicit_admission_binding_and_reviewed_mapping", model_input_validation: "not_provided", limitations: ["合成展示资料，未验证风险模型，不产生概率或临床分期"],
  };
  const secondPoint = copy(snapshot.points[0]);
  secondPoint.observation_id = "a2000000-0000-4000-8000-000000000002";
  secondPoint.source_id = "inpatient_observation:a2000000-0000-4000-8000-000000000002:444444444444";
  secondPoint.payload.measurements.heart_rate.value = "1";
  snapshot.points.push(secondPoint);
  snapshot.quality.same_time_groups[0].source_ids = snapshot.points.map(row => row.source_id);
  snapshot.quality.urine.overlap_groups[0].source_ids = snapshot.urine_intervals.map(row => row.source_id);
  snapshot.quality.urine.excluded_intervals = snapshot.urine_intervals.map((row, index) => ({ source_id: row.source_id, reasons: index ? ["overlapping_intervals", "collection_not_complete", "not_confirmed_patient_total", "volume_not_measured"] : ["overlapping_intervals"] }));
  snapshot.quality.urine.eligible_coverage_intervals = [];
  snapshot.quality.missing_by_point.push({ ...copy(snapshot.quality.missing_by_point[0]), source_id: secondPoint.source_id });
  return { ...Object.fromEntries(Object.entries(snapshot).filter(([key]) => !["points", "urine_intervals", "quality", "limitations", "lab_input_status", "model_input_validation", "snapshot_basis", "point_interval_semantics"].includes(key))), status: "active", revision: 1, can_revoke: true, freshness: { state: "current" }, snapshot };
}
const a = windowFixture("11111111-1111-4111-8111-111111111111"), b = windowFixture("22222222-2222-4222-8222-222222222222", 1, admission, "b"), c = windowFixture("33333333-3333-4333-8333-333333333333", 2, secondAdmission, "c");
const option = value => `${value.start_at} 至 ${value.end_at} · 可用截止 ${value.as_of} · ${value.window_id.slice(0, 8)}`;
async function select(page, label, optionLabel) {
  const input = page.getByRole("combobox", { name: label, exact: true }); await input.press("ArrowDown");
  await page.locator(`#${await input.getAttribute("aria-controls")}`).getByRole("option", { name: optionLabel, exact: true }).click();
}
async function session(page, options = {}) {
  const state = { contexts: [], runs: [], writes: [], details: [], completed: [], sourceReads: [], freshDirectoryReleases: [], ...options };
  await page.addInitScript(() => localStorage.setItem("hoim-token", "synthetic-observation-entry-only"));
  await page.route("**/api/**", async route => {
    const request = route.request(), url = new URL(request.url()), path = url.pathname, method = request.method(); let data = [], extra = {};
    if (path === "/api/userInfo") data = { username: "合成窗口复核人", permissions: [state.role || "super_admin"], avatar: "" };
    if (path === "/api/admission/getInpatientList") data = [{ patient_id: 1, admission_id: admission, patient_name: "合成患者甲", bed_no: "A01" }, { patient_id: 2, admission_id: secondAdmission, patient_name: "合成患者乙", bed_no: "A02" }];
    if (path.startsWith("/api/inpatient-observations/")) { state.sourceReads.push({ path, params: Object.fromEntries(url.searchParams) }); data = { items: [], total: 0, page: 1, page_size: 50 }; }
    if (["/api/ai/features", "/api/ai/admin/features"].includes(path)) data = [{ key: "deterioration_risk", number: 41, name: "病情恶化预警", category: "inpatient", scope: "patient", engine: "prediction", enabled: true, inputs: ["原住院冻结观测窗"], deliverables: ["原资料与缺口"], source_reference_keys: ["observation_window_id"] }];
    if (path === "/api/ai/patients") {
      data = state.emptyDirectories ? [] : [{ patient_id: 1, label: "合成患者甲" }, { patient_id: 2, label: "合成患者乙" }];
      if (state.holdPatients && !state.patientsHeld) { state.patientsHeld = true; await new Promise(resolve => { state.releasePatients = resolve; }); state.completed.push("held-patients"); }
      else if (state.emptyDirectories && state.holdFreshDirectories) await new Promise(resolve => state.freshDirectoryReleases.push(resolve));
    }
    if (path === "/api/ai/encounters") {
      data = state.emptyDirectories ? [] : [{ encounter_ref: url.searchParams.get("patient_id") === "2" ? secondAdmission : admission, kind: "inpatient", label: "住院 · 合成原记录" }, { encounter_ref: "outpatient-only", kind: "outpatient", label: "门诊 · 不归入风险窗" }];
      if (state.holdEncounters && !state.encountersHeld) { state.encountersHeld = true; await new Promise(resolve => { state.releaseEncounters = resolve; }); state.completed.push("held-encounters"); }
    }
    if (path === "/api/ai/observation-windows") { data = Number(url.searchParams.get("patient_id")) === 2 ? [c] : [a, b]; data = data.map(item => ({ ...copy(item), snapshot: undefined, freshness: { state: "not_checked" } })); }
    const detail = path.match(/^\/api\/ai\/observation-windows\/([^/]+)$/);
    if (detail) {
      state.details.push({ id: detail[1], params: Object.fromEntries(url.searchParams) });
      if (state.holdDetail && detail[1] === a.window_id) await new Promise(resolve => { state.releaseDetail = resolve; });
      data = copy([a, b, c].find(item => item.window_id === detail[1]));
      if (state.detailState) data.freshness.state = state.detailState;
      if (state.wrongOuter) data.patient_id = 99;
      if (state.wrongInner) data.snapshot.admission_id = secondAdmission;
      if (state.wrongHash) data.snapshot.content_hash = "f".repeat(64);
      state.completed.push(detail[1]);
    }
    if (path === "/api/ai/context") { const body = request.postDataJSON(); state.contexts.push(body); const chosen = [a, b, c].find(item => item.window_id === body.source_refs.observation_window_id); data = { context: { observation_window: chosen.snapshot }, evidence: [{ source_id: chosen.source_id, title: "冻结原住院观测窗", content: JSON.stringify(chosen.snapshot) }] }; }
    if (path === "/api/ai/runs" && method === "POST") {
      const body = request.postDataJSON(); state.runs.push(body); if (state.holdRun) await new Promise(resolve => { state.releaseRun = resolve; }); const chosen = [a, b, c].find(item => item.window_id === body.input.observation_window_id);
      data = { run_id: "synthetic-observation-ui-result", feature_key: "deterioration_risk", feature_name: "病情恶化预警", patient_id: body.patient_id, encounter_ref: body.encounter_ref, status: "succeeded", observation_findings: chosen.snapshot, evidence: [{ source_id: chosen.source_id, title: "冻结原住院观测窗", content: JSON.stringify(chosen.snapshot) }], result: { summary: "合成回执：仅测试复核界面，不是模型风险预测", sections: [], warnings: [], missing_data: [] } };
      state.completed.push("run");
    }
    if (path === "/api/ai/admin/observation-windows") { state.adminReads = (state.adminReads || 0) + 1; data = [a]; }
    if (path === `/api/ai/admin/observation-windows/${a.window_id}`) data = copy(a);
    // Existing userInfo uses POST to read the authenticated user's profile.
    if (method !== "GET" && !["/api/userInfo", "/api/ai/context", "/api/ai/runs"].includes(path)) state.writes.push(path);
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ code: 200, msg: "success", data, ...extra }) });
  });
  return state;
}
async function open(page) { await page.goto("/#/ai/workbench?feature=deterioration_risk"); await select(page, "患者", "合成患者甲"); await select(page, "本次就诊", "住院 · 合成原记录"); }
async function choose(page, value = a) { await select(page, "原住院观测窗", option(value)); }

test("风险入口必须明确原住院和窗口，预览与生成共享引用且JSON不能改写原值", async ({ page }) => {
  const state = await session(page); await open(page); await expect(page.getByRole("button", { name: "生成辅助建议", exact: true })).toBeDisabled(); await choose(page);
  await expect(page.getByRole("button", { name: "生成辅助建议", exact: true })).toBeEnabled();
  await page.getByText("联调与预览选项", { exact: true }).click(); await page.getByPlaceholder("可选：专用适配器的结构化输入 JSON，由服务契约规定", { exact: true }).fill(JSON.stringify({ observation_window_id: b.window_id, vital_signs: { heart_rate: 999 }, as_of: "2099-01-01" }));
  await page.getByRole("button", { name: "查看本次资料", exact: true }).click(); const preview = page.getByRole("dialog", { name: "本次提供给 AI 的患者资料", exact: true });
  await expect(preview.getByLabel("原点测量数值与缺项", { exact: true }).locator("tbody tr").first()).toContainText("0"); await expect(preview).toContainText("未知（未测）"); await expect(preview).toContainText("未任取最后一条"); await expect(preview).toContainText("不填0"); await expect(preview).toContainText("不足两个有值时点");
  expect(state.contexts[0]).toEqual({ feature_key: "deterioration_risk", patient_id: 1, encounter_ref: admission, source_refs: { observation_window_id: a.window_id } });
  await preview.locator(".el-dialog__headerbtn").click(); await page.getByRole("button", { name: "生成辅助建议", exact: true }).click(); await expect(page.getByLabel("AI任务结果", { exact: true })).toContainText("仅测试复核界面");
  expect(state.runs[0].input).toEqual({ observation_window_id: a.window_id, question: "" }); expect(state.runs[0].encounter_ref).toBe(admission); expect(state.details[0].params).toEqual({ patient_id: "1", admission_id: admission }); expect(state.writes).toEqual([]);
});

for (const [name, options] of [["原资料已变化", { detailState: "stale" }], ["窗口已撤销", { detailState: "revoked" }], ["外层患者不符", { wrongOuter: true }], ["冻结住院不符", { wrongInner: true }], ["冻结哈希不符", { wrongHash: true }]]) {
  test(`${name}不接受为当前风险输入`, async ({ page }) => { const state = await session(page, options); await open(page); await choose(page); await expect(page.getByText("窗口已撤销、原资料已变化或范围不符，请重新建立并核对来源。", { exact: true })).toBeVisible(); await expect(page.getByRole("button", { name: "生成辅助建议", exact: true })).toBeDisabled(); expect(state.runs).toEqual([]); expect(state.contexts).toEqual([]); });
}

test("切换窗口后迟到详情不能恢复原选择，刷新目录清除已核对状态", async ({ page }) => {
  const state = await session(page, { holdDetail: true }); await open(page); await choose(page); await expect.poll(() => !!state.releaseDetail).toBe(true); await choose(page, b); await expect(page.getByRole("button", { name: "生成辅助建议", exact: true })).toBeEnabled(); state.releaseDetail(); await expect.poll(() => state.completed.includes(a.window_id)).toBe(true); await expect(page.getByText(new RegExp(`已核对 ${b.window_id}`))).toBeVisible();
  await page.getByRole("button", { name: "刷新可选观测窗", exact: true }).click(); await expect(page.getByRole("button", { name: "生成辅助建议", exact: true })).toBeDisabled(); await expect(page.getByText(new RegExp(`已核对 ${b.window_id}`))).toHaveCount(0); expect(state.runs).toEqual([]);
});

test("角色或会话变化清除观测窗，不使用迟到检查回执", async ({ page }) => {
  const state = await session(page, { holdDetail: true }); await open(page); await choose(page); await expect.poll(() => !!state.releaseDetail).toBe(true); await page.evaluate(() => document.querySelector("#hoim").__vue_app__.config.globalProperties.$store.commit("user/setPermissions", ["patient"])); state.releaseDetail(); await expect.poll(() => state.completed.includes(a.window_id)).toBe(true); await expect(page.getByRole("button", { name: "生成辅助建议", exact: true })).toBeDisabled(); await expect(page.getByText(new RegExp(`已核对 ${a.window_id}`))).toHaveCount(0); expect(state.runs).toEqual([]);
});

test("切换患者后旧任务回执不挂到新病例，旧窗口不可继续提交", async ({ page }) => {
  const state = await session(page, { holdRun: true }); await open(page); await choose(page); await expect(page.getByRole("button", { name: "生成辅助建议", exact: true })).toBeEnabled(); await page.getByRole("button", { name: "生成辅助建议", exact: true }).click(); await expect.poll(() => !!state.releaseRun).toBe(true); await select(page, "患者", "合成患者乙"); state.releaseRun(); await expect.poll(() => state.completed.includes("run")).toBe(true); await expect(page.getByLabel("AI任务结果", { exact: true })).toHaveCount(0); await expect(page.getByRole("button", { name: "生成辅助建议", exact: true })).toBeDisabled(); expect(state.runs).toHaveLength(1);
});

test("超级管理员真实管理入口核对冻结窗口，不发起推理", async ({ page }) => {
  const state = await session(page); await page.goto("/#/ai/manage"); await page.getByRole("tab", { name: "住院观测窗", exact: true }).click(); await expect(page.getByLabel("AI住院观测窗管理", { exact: true })).toContainText(a.window_id); await page.getByRole("button", { name: "核对冻结观测窗", exact: true }).click(); const dialog = page.getByRole("dialog", { name: "冻结住院观测窗审计", exact: true }); await expect(dialog).toContainText(a.content_hash); await expect(dialog.getByLabel("窗口冻结点测量", { exact: true })).toContainText("0 /min"); expect(state.adminReads).toBeGreaterThan(0); expect(state.runs).toEqual([]); expect(state.writes).toEqual([]);
});

test("护士工作站延迟打开观测页，切换患者清除未保存测量并重新限定原住院", async ({ page }) => {
  const state = await session(page, { role: "nurse" }); await page.goto("/#/inpatient/nursingStation");
  await page.getByRole("cell", { name: "合成患者甲", exact: true }).click();
  await expect(page.getByRole("tab", { name: "结构化观测", exact: true })).toBeVisible(); expect(state.sourceReads).toEqual([]);
  await page.getByRole("tab", { name: "结构化观测", exact: true }).click(); const panel = page.getByLabel("原住院生理观测来源", { exact: true });
  await expect(panel).toContainText(admission); await expect.poll(() => state.sourceReads.length).toBe(2);
  expect(state.sourceReads.every(read => read.params.patient_id === "1" && read.params.admission_id === admission)).toBe(true);
  await panel.getByRole("textbox", { name: "心率原始数值", exact: true }).fill("0");
  await panel.getByRole("textbox", { name: "实际观察时点", exact: true }).fill("2026-10-19T00:00:00.123456Z");
  await page.getByRole("cell", { name: "合成患者乙", exact: true }).click(); await expect(panel).toContainText(secondAdmission);
  await expect(panel.getByRole("textbox", { name: "心率原始数值", exact: true })).toHaveValue(""); await expect(panel.getByRole("textbox", { name: "实际观察时点", exact: true })).toHaveValue("");
  await expect.poll(() => state.sourceReads.filter(read => read.params.patient_id === "2" && read.params.admission_id === secondAdmission).length).toBe(2);
  expect(state.runs).toEqual([]); expect(state.writes).toEqual([]);
});

for (const change of ["token", "role"]) for (const directory of ["patients", "encounters"]) {
  test(`${change}变化后${directory}旧目录回执不能重新显示患者或住院`, async ({ page }) => {
    const state = await session(page, directory === "patients" ? { holdPatients: true } : { holdEncounters: true });
    await page.addInitScript(() => {
      const counts = {}, open = XMLHttpRequest.prototype.open; window.__observationDirectorySettled = [];
      XMLHttpRequest.prototype.open = function(method, url, ...args) {
        const path = new URL(url, location.href).pathname;
        if (["/api/ai/patients", "/api/ai/encounters"].includes(path)) {
          const marker = `${path}:${counts[path] = (counts[path] || 0) + 1}`;
          // Observe the native transport; the next task follows its promise/Vue updates.
          this.addEventListener("loadend", () => setTimeout(() => window.__observationDirectorySettled.push(marker), 0), { once: true });
        }
        return open.call(this, method, url, ...args);
      };
    });
    await page.goto("/#/ai/workbench?feature=deterioration_risk");
    if (directory === "encounters") await select(page, "患者", "合成患者甲");
    const release = directory === "patients" ? "releasePatients" : "releaseEncounters";
    await expect.poll(() => !!state[release]).toBe(true); state.emptyDirectories = true; state.holdFreshDirectories = true;
    await page.evaluate(kind => {
      const store = document.querySelector("#hoim").__vue_app__.config.globalProperties.$store;
      store.commit(kind === "token" ? "user/setAccessToken" : "user/setPermissions", kind === "token" ? "synthetic-new-session" : ["patient"]);
    }, change);
    state[release](); await expect.poll(() => state.completed.includes(`held-${directory}`)).toBe(true);
    await page.waitForFunction(marker => window.__observationDirectorySettled.includes(marker), `/api/ai/${directory}:1`);
    try {
      // Element Plus displays selected labels outside the combobox input.
      await expect(page.locator(".el-select__selected-item").filter({ hasText: /^合成患者甲$/ })).toHaveCount(0);
      await expect(page.getByRole("combobox", { name: "本次就诊", exact: true })).toHaveCount(0);
      const control = page.getByRole("combobox", { name: "患者", exact: true }); await control.press("ArrowDown");
      // Keep fresh requests pending: opening a remote select must not erase evidence
      // of a stale reply before we inspect the actual rendered empty state.
      // An empty remote select hides its popup. Wait for actual focus and its next
      // rendered frame before inspecting options, rather than the search input.
      await expect(control).toBeFocused();
      await page.evaluate(() => new Promise(requestAnimationFrame));
      await expect(page.getByRole("option", { name: "合成患者甲", exact: true })).toHaveCount(0);
      await expect(page.getByRole("button", { name: "生成辅助建议", exact: true })).toBeDisabled(); expect(state.runs).toEqual([]); expect(state.contexts).toEqual([]);
    } finally { state.holdFreshDirectories = false; for (const resolve of state.freshDirectoryReleases) resolve(); }
  });
}
