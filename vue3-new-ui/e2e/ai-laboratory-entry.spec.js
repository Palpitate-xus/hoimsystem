const { selectManagementTab } = require('./fixtures/ai-management-navigation.cjs');
const { test, expect } = require("@playwright/test");

// These tests load the production dist main application. APIs are intercepted
// with synthetic source contracts; this is UI integration evidence, not backend
// authorization, clinical validation, real laboratory data or model inference.
const copy = value => JSON.parse(JSON.stringify(value));
const admission = "d1000000-0000-4000-8000-000000000001";
const secondAdmission = "d2000000-0000-4000-8000-000000000002";
const windowId = "11111111-1111-4111-8111-111111111111";
const stamp = "2020-01-02T00:00:00.123456Z";
const legacyClock = "2020-01-01T00:30:00.654321";
const note = "合成核对依据：已核对原观察项、来源系统、真实采样UTC及明确原住院资料";
function source(index, qualitative = false) {
  const labSourceId = `${index}1000000-0000-4000-8000-000000000001`;
  const mappingId = `${index}2000000-0000-4000-8000-000000000001`;
  const observationId = `synthetic-original-observation-${index}`;
  const signature = { code_system: "synthetic-local", code: qualitative ? "SYN-CULTURE" : "SYN-CREAT", unit: qualitative ? null : "synthetic-unit", method: "synthetic-method", specimen_type: "synthetic-specimen", value_kind: qualitative ? "qualitative" : "numeric" };
  const mapping = { mapping_id: mappingId, schema_version: "lab_mapping_v1", source_namespace: "synthetic-lis", signature, analyte_key: qualitative ? "culture_result" : "creatinine", analyte_label: qualitative ? "合成培养项目" : "合成肌酐项目", evidence_reference: "synthetic-dictionary-reference", rationale: note, content_hash: "b".repeat(64), governance_hash: "c".repeat(64), source_id: `lab_mapping:${mappingId}:${"b".repeat(12)}`, created_at: stamp, created_by: 7, status: "published", revision: 2, published_at: stamp, review_note: note };
  const metadata = { lab_source_id: labSourceId, source_id: `inpatient_lab:${labSourceId}:${"a".repeat(12)}`, patient_id: 1, admission_id: admission, observation_id: observationId, mapping_id: mappingId, schema_version: "inpatient_lab_source_v1", created_by: 7, raw_original_hash: "d".repeat(64), mapping_content_hash: mapping.content_hash, content_hash: "a".repeat(64), collected_at_utc: "2020-01-01T00:30:00.654321Z", registered_at: stamp, available_at: stamp, status: "active", revision: 1 };
  const snapshot = {
    ...metadata, mapping, source_namespace: mapping.source_namespace,
    original: {
      observation: { observation_id: observationId, lab_result_id: `synthetic-report-${index}`, ...signature, display: qualitative ? "合成培养原文" : "合成肌酐原值", value_num: qualitative ? null : "0.00000000", value_text: qualitative ? "合成定性原文 <img src=x onerror=alert(1)>" : null, collected_at: legacyClock, time_basis: "unknown" },
      report: { lab_result_id: `synthetic-report-${index}`, lab_order_id: `synthetic-order-${index}`, report_time: legacyClock, audit_time: legacyClock, audit_status: 1, auditor_id: 8, technician_id: 9, time_basis: "unknown" },
      order: { lab_order_id: `synthetic-order-${index}`, patient_id: 1, doctor_id: 9, status: 2, create_time: legacyClock, time_basis: "unknown" },
    },
    availability_basis: "server_registered_after_verification", sampling_time_basis: "explicit_user_verified_utc_not_legacy_clock_proof", source_verification: "explicit_user_attestation_not_independently_verified", source_namespace_origin_basis: "explicit_user_attestation_no_stored_lis_origin",
    collection_time_confirmed: true, admission_binding_confirmed: true, source_namespace_confirmed: true,
    collection_time_basis_note: note, admission_binding_note: note, source_namespace_basis_note: note,
  };
  return { ...metadata, snapshot, can_revoke: true, mapping_current: { status: "published", revision: 2 }, eligible: true, exclusion_reasons: [], freshness: { state: "current", message: "仅合成UI核对回执" } };
}
function windowFixture(sources) {
  const snapshot = {
    schema_version: "inpatient_window_v2", window_id: windowId, patient_id: 1, admission_id: admission,
    created_by: 7, created_at: "2020-01-02T00:00:02.123456Z", start_at: "2020-01-01T00:00:00.123456Z", end_at: "2020-01-01T01:00:00.123456Z", as_of: "2020-01-02T00:00:01.123456Z", content_hash: "f".repeat(64), source_id: `observation_window:${windowId}:${"f".repeat(12)}`,
    snapshot_basis: "current_snapshot_retrospective", point_interval_semantics: "[start,end]", points: [], urine_intervals: [],
    lab_observations: copy(sources).map(row => ({ ...row, window_projection: "risk_lab_projection_v1" })),
    laboratory_projection: { schema_version: "risk_lab_projection_v1", omitted_parent_fields: ["original.report.result", "original.order.check_type", "original.order.check_items"], original_content_binding: "raw_original_hash_and_content_hash", attestation_notes: "provenance_only_not_measurement_facts" },
    quality: { laboratory: { member_count: sources.length, eligible_count: sources.length, excluded_sources: [], same_time_groups: [] }, measurement_gaps: [], missing_by_point: [], same_time_groups: [], urine: { overlap_groups: [], excluded_intervals: [], uncovered_intervals: [] } },
    model_input_validation: "not_provided", limitations: ["合成资料：受控检验子集不是全套检验或临床模型验证"],
  };
  return { ...snapshot, snapshot, status: "active", revision: 1, can_revoke: true, freshness: { state: "current" } };
}
const optionLabel = value => `${value.start_at} 至 ${value.end_at} · 可用截止 ${value.as_of} · ${value.window_id.slice(0, 8)}`;
async function select(page, label, optionLabel) {
  const input = page.getByRole("combobox", { name: label, exact: true });
  await expect(input).toBeEnabled(); await input.press("ArrowDown");
  await page.locator(`#${await input.getAttribute("aria-controls")}`).getByRole("option", { name: optionLabel, exact: true }).click();
}
async function session(page, options = {}) {
  const sources = [source(1), source(2, true)];
  const state = { role: options.role || "doctor", sources, window: windowFixture(sources), reads: [], contexts: [], runs: [], writes: [], ...options };
  await page.addInitScript(() => localStorage.setItem("hoim-token", "synthetic-dist-laboratory-entry"));
  await page.route("**/api/**", async route => {
    const request = route.request(), url = new URL(request.url()), path = url.pathname, method = request.method(), params = Object.fromEntries(url.searchParams);
    let data = [];
    if (method === "GET") state.reads.push({ path, params });
    if (path === "/api/userInfo") data = { username: "合成检验复核人", permissions: [state.role], avatar: "" };
    if (["/api/ai/features", "/api/ai/admin/features"].includes(path)) data = [{ key: "deterioration_risk", number: 41, name: "病情恶化预警", category: "inpatient", scope: "patient", engine: "prediction", enabled: true, inputs: ["明确原住院冻结窗口"], deliverables: ["来源与缺口复核"], source_reference_keys: ["observation_window_id"], allowed_roles: ["doctor"], default_roles: ["doctor"], validation_status: "unreviewed", prompt_version: 1 }];
    if (path === "/api/ai/patients") data = [{ patient_id: 1, label: "合成患者甲" }, { patient_id: 2, label: "合成患者乙" }];
    if (path === "/api/ai/encounters") data = [{ encounter_ref: params.patient_id === "2" ? secondAdmission : admission, kind: "inpatient", label: "住院 · 合成原记录" }];
    if (path === "/api/admission/getInpatientList") data = [{ patient_id: 1, admission_id: admission, patient_name: "合成患者甲", bed_no: "A01" }, { patient_id: 2, admission_id: secondAdmission, patient_name: "合成患者乙", bed_no: "A02" }];
    if (path === "/api/ai/admin/lab-mappings/options") data = { analytes: [{ key: "creatinine", label: "合成肌酐项目" }, { key: "culture_result", label: "合成培养项目" }] };
    if (path === "/api/ai/admin/lab-mappings") data = { items: [copy(state.sources[0].snapshot.mapping)], total: 1, page: 1, page_size: 50 };
    if (path.startsWith("/api/ai/admin/lab-mappings/") && !path.endsWith("/options")) data = copy(state.sources[0].snapshot.mapping);
    if (["/api/inpatient-laboratory/sources", "/api/ai/admin/lab-sources"].includes(path)) {
      const rows = state.sources.filter(row => (!params.patient_id || String(row.patient_id) === params.patient_id) && (!params.admission_id || row.admission_id === params.admission_id));
      data = { items: copy(rows), total: rows.length, page: 1, page_size: 50 };
    }
    const sourceDetail = path.match(/^\/api\/(?:inpatient-laboratory\/sources|ai\/admin\/lab-sources)\/([^/]+)$/);
    if (sourceDetail) data = copy(state.sources.find(row => row.lab_source_id === sourceDetail[1]));
    if (path === "/api/inpatient-laboratory/candidates") data = { items: [], truncated: false };
    if (path === "/api/ai/observation-windows") { const summary = copy(state.window); delete summary.snapshot; summary.freshness = { state: "not_checked" }; data = [summary]; }
    if (path === `/api/ai/observation-windows/${windowId}`) {
      data = copy(state.window);
      if (state.wrongNested === "patient") data.snapshot.lab_observations[0].snapshot.patient_id = 99;
      if (state.wrongNested === "admission") data.snapshot.lab_observations[0].snapshot.admission_id = secondAdmission;
      if (state.invalidMember === "missing_snapshot") data.snapshot.lab_observations[0].snapshot = null;
      if (state.invalidMember === "missing_projection") delete data.snapshot.lab_observations[0].window_projection;
      if (state.invalidMember === "unknown_projection") data.snapshot.lab_observations[0].window_projection = "unrecognized-risk-projection";
    }
    const evidence = [
      { source_id: state.window.source_id, title: "合成冻结原住院窗", content: JSON.stringify(state.window.snapshot) },
      ...state.window.snapshot.lab_observations.flatMap(row => [{ source_id: row.source_id, title: "合成受控检验原依据", content: JSON.stringify(row) }, { source_id: row.snapshot.mapping.source_id, title: "合成冻结项目映射依据", content: JSON.stringify(row.snapshot.mapping) }]),
    ];
    if (path === "/api/ai/context") { state.contexts.push(request.postDataJSON()); data = { context: { observation_window: copy(state.window.snapshot) }, evidence }; }
    if (path === "/api/ai/runs" && method === "POST") { state.runs.push(request.postDataJSON()); data = { run_id: "synthetic-dist-laboratory-result", feature_key: "deterioration_risk", feature_name: "病情恶化预警", patient_id: 1, encounter_ref: admission, status: "succeeded", observation_findings: copy(state.window.snapshot), evidence, result: { summary: "仅合成页面绑定与来源展示测试，未运行风险模型", sections: [], warnings: [], missing_data: [] } }; }
    const revoke = path.match(/^\/api\/inpatient-laboratory\/sources\/([^/]+)\/revoke$/);
    if (revoke && method === "POST") { const row = state.sources.find(item => item.lab_source_id === revoke[1]); Object.assign(row, { status: "revoked", revision: row.revision + 1, revoked_at: stamp, can_revoke: false, snapshot: null, eligible: false, freshness: { state: "revoked" } }); data = copy(row); }
    if (method !== "GET" && !["/api/userInfo", "/api/ai/context", "/api/ai/runs"].includes(path)) state.writes.push({ path, body: request.postDataJSON() });
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ code: 200, msg: "synthetic UI response", data }) });
  });
  return state;
}
async function openRisk(page, state) { await page.goto("/#/ai/workbench?feature=deterioration_risk"); await select(page, "患者", "合成患者甲"); await select(page, "本次就诊", "住院 · 合成原记录"); await select(page, "原住院观测窗", optionLabel(state.window)); }

// The enclosing aiManagement/nursingStation/workbench pages are production
// routes with actual lazy imports; none uses the isolated component harness.
test("超管主应用实际挂载项目映射及检验来源全院审计", async ({ page }) => {
  const state = await session(page, { role: "super_admin" }); await page.goto("/#/ai/manage");
  await selectManagementTab(page, '检验项目与来源'); const management = page.getByLabel("检验项目映射与来源治理", { exact: true });
  await expect(management).toContainText("synthetic-lis"); await management.getByRole("button", { name: "核对项目映射", exact: true }).click();
  const mappingDialog = page.getByRole("dialog", { name: "检验项目映射审核", exact: true }); await expect(mappingDialog).toContainText(state.sources[0].snapshot.mapping.mapping_id); await expect(mappingDialog).toContainText("已发布 · v2"); await mappingDialog.getByRole("button", { name: "关闭", exact: true }).click();
  await management.getByRole("tab", { name: "检验来源全院审计", exact: true }).click(); await management.getByRole("button", { name: "核对冻结检验", exact: true }).first().click();
  const sourceDialog = page.getByRole("dialog", { name: "冻结检验来源审计", exact: true }); await expect(sourceDialog.getByLabel("冻结原检验值", { exact: true })).toHaveText("0.00000000 synthetic-unit"); await expect(sourceDialog).toContainText(legacyClock);
  for (const path of ["/api/ai/admin/lab-mappings/options", "/api/ai/admin/lab-mappings", "/api/ai/admin/lab-sources"]) expect(state.reads.some(read => read.path === path)).toBe(true);
  expect(state.contexts).toEqual([]); expect(state.runs).toEqual([]); expect(state.writes).toEqual([]);
});

test("护士主应用检验来源tab仅按当前原住院只读，切换患者重新限定目录", async ({ page }) => {
  const state = await session(page, { role: "nurse" }); await page.goto("/#/inpatient/nursingStation"); await page.getByRole("cell", { name: "合成患者甲", exact: true }).click();
  expect(state.reads.filter(read => read.path.includes("inpatient-laboratory"))).toEqual([]); await page.getByRole("tab", { name: "检验来源", exact: true }).click();
  const panel = page.getByLabel("原住院受控检验来源", { exact: true }); await expect(panel).toContainText(admission); await expect(panel).toContainText("当前角色只读已登记检验来源"); await expect(panel.getByRole("button", { name: "登记已审核检验原来源", exact: true })).toHaveCount(0);
  await panel.getByRole("button", { name: "核对原检验来源", exact: true }).first().click(); const dialog = page.getByRole("dialog", { name: "受控检验原来源核对", exact: true }); await expect(dialog.getByLabel("冻结原检验值", { exact: true })).toHaveText("0.00000000 synthetic-unit"); await expect(dialog.getByRole("button", { name: "撤销此检验来源", exact: true })).toHaveCount(0); await dialog.getByRole("button", { name: "关闭", exact: true }).click();
  await page.getByRole("cell", { name: "合成患者乙", exact: true }).click(); await expect(panel).toContainText(secondAdmission); await expect(panel.getByRole("button", { name: "核对原检验来源", exact: true })).toHaveCount(0);
  await expect.poll(() => state.reads.some(read => read.path === "/api/inpatient-laboratory/sources" && read.params.patient_id === "2" && read.params.admission_id === secondAdmission)).toBe(true);
  expect(state.reads.some(read => read.path.endsWith("/candidates"))).toBe(false); expect(state.runs).toEqual([]); expect(state.writes).toEqual([]);
});

test("医生风险41的v2窗口展示0与定性原文和原依据，预览与任务只绑定窗口", async ({ page }) => {
  const state = await session(page); await openRisk(page, state); await expect(page.getByRole("button", { name: "生成辅助建议", exact: true })).toBeEnabled(); await page.getByRole("button", { name: "查看本次资料", exact: true }).click();
  const preview = page.getByRole("dialog", { name: "本次提供给 AI 的患者资料", exact: true }); await expect(preview.getByLabel("冻结原检验值", { exact: true }).first()).toHaveText("0.00000000 synthetic-unit"); await expect(preview.getByLabel("冻结原检验值", { exact: true }).nth(1)).toContainText("合成定性原文 <img src=x onerror=alert(1)>"); await expect(preview.locator("img")).toHaveCount(0);
  await expect(preview).toContainText(legacyClock); await expect(preview).toContainText("人工核实采样UTC：2020-01-01T00:30:00.654321Z"); await expect(preview).toContainText("不是原报告首次可用时间"); await expect(preview).toContainText("原报告全文与申请正文未作为本窗事实输入");
  await preview.getByRole("button", { name: "核对冻结检验依据", exact: true }).first().click(); const evidence = page.getByRole("dialog", { name: "核查引用依据", exact: true }); await expect(evidence).toContainText(state.sources[0].source_id); await expect(evidence).toContainText("raw_original_hash"); await evidence.locator(".el-dialog__headerbtn").click();
  await preview.locator(".el-dialog__headerbtn").click(); await page.getByRole("button", { name: "生成辅助建议", exact: true }).click();
  const result = page.getByLabel("AI任务结果", { exact: true }); await expect(result).toContainText("未运行风险模型"); await expect(result.getByLabel("冻结原检验值", { exact: true }).first()).toHaveText("0.00000000 synthetic-unit");
  expect(state.contexts).toEqual([{ feature_key: "deterioration_risk", patient_id: 1, encounter_ref: admission, source_refs: { observation_window_id: windowId } }]); expect(state.runs[0].input).toEqual({ observation_window_id: windowId, question: "" }); expect(state.runs[0].encounter_ref).toBe(admission); expect(state.writes).toEqual([]);
});

test("医生风险入口显式撤销原检验后清除窗口选择，旧窗口不补新资料或继续提交", async ({ page }) => {
  const state = await session(page); await openRisk(page, state); await expect(page.getByRole("button", { name: "生成辅助建议", exact: true })).toBeEnabled(); await page.getByRole("button", { name: "核实原住院来源并建立观测窗", exact: true }).click();
  const panel = page.getByLabel("原住院受控检验来源", { exact: true }); await expect(panel).toContainText(admission); await panel.getByRole("button", { name: "核对原检验来源", exact: true }).first().click();
  const dialog = page.getByRole("dialog", { name: "受控检验原来源核对", exact: true }); await dialog.getByRole("textbox", { name: "检验来源撤销依据", exact: true }).fill("合成核对错误住院关联后撤销原来源"); await dialog.getByRole("button", { name: "撤销此检验来源", exact: true }).click();
  await expect(page.getByText("原来源已变化；旧观测窗不会补入新资料，请重新建立窗口并明确选择核对。", { exact: true })).toBeVisible(); await expect(page.getByRole("button", { name: "生成辅助建议", exact: true })).toBeDisabled();
  expect(state.writes).toEqual([{ path: `/api/inpatient-laboratory/sources/${state.sources[0].lab_source_id}/revoke`, body: { patient_id: 1, admission_id: admission, expected_revision: 1, reason: "合成核对错误住院关联后撤销原来源" } }]); expect(state.runs).toEqual([]); expect(state.contexts).toEqual([]);
});

for (const wrongNested of ["patient", "admission"]) {
  test(`风险窗口内检验冻结${wrongNested}串源拒绝，不展示或生成`, async ({ page }) => {
    const state = await session(page, { wrongNested }); await openRisk(page, state);
    await expect(page.getByText("窗口已撤销、原资料已变化或范围不符，请重新建立并核对来源。", { exact: true })).toBeVisible(); await expect(page.getByRole("button", { name: "生成辅助建议", exact: true })).toBeDisabled(); await expect(page.getByRole("button", { name: "查看本次资料", exact: true })).toBeDisabled();
    await expect(page.getByLabel("冻结原检验值", { exact: true })).toHaveCount(0); expect(state.runs).toEqual([]); expect(state.contexts).toEqual([]); expect(state.writes).toEqual([]);
  });
}


for (const [invalidMember, title] of [["missing_snapshot", "成员冻结正文为null"], ["missing_projection", "成员缺少投影标识"], ["unknown_projection", "成员投影标识未知"]]) {
  test(`风险v2窗口${title}拒绝选中，不把元数据当完整有效检验`, async ({ page }) => {
    const state = await session(page, { invalidMember }); await openRisk(page, state);
    await expect(page.getByText("窗口已撤销、原资料已变化或范围不符，请重新建立并核对来源。", { exact: true })).toBeVisible();
    await expect(page.getByRole("button", { name: "生成辅助建议", exact: true })).toBeDisabled();
    await expect(page.getByRole("button", { name: "查看本次资料", exact: true })).toBeDisabled();
    await expect(page.getByLabel("原住院观测窗复核", { exact: true })).toHaveCount(0);
    await expect(page.getByLabel("冻结原检验值", { exact: true })).toHaveCount(0);
    await expect(page.getByText(/来源及映射核对可纳入/)).toHaveCount(0);
    expect(state.runs).toEqual([]); expect(state.contexts).toEqual([]); expect(state.writes).toEqual([]);
  });
}
