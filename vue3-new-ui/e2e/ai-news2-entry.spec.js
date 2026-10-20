const { test, expect } = require("@playwright/test");

// Production dist main-app routes with synthetic API contracts only. These tests
// verify UI integration, not backend authorization, rule accuracy or clinical validation.
const clone = value => JSON.parse(JSON.stringify(value));
const admission = "11111111-1111-4111-8111-111111111111", windowId = "22222222-2222-4222-8222-222222222222", profileId = "33333333-3333-4333-8333-333333333333", pointId = "44444444-4444-4444-8444-444444444444", assessmentId = "55555555-5555-4555-8555-555555555555";
const stamp = "2020-01-01T00:30:00.123456Z", recorded = "2020-01-01T00:31:00.654321Z", asOf = "2020-01-02T00:00:00.123456Z", note = "已核对合成原观察时刻、身份和原临床资料，此说明仅为人工来源核实依据";
const hashes = { assessment: "a".repeat(64), window: "b".repeat(64), point: "c".repeat(64), profile: "d".repeat(64), recipe: "e".repeat(64), governance: "f".repeat(64) };
const keys = ["respiratory_rate", "spo2", "systolic_bp", "pulse_rate", "temperature", "supplemental_oxygen", "consciousness"];
const units = { respiratory_rate: "/min", spo2: "%", systolic_bp: "mm[Hg]", pulse_rate: "/min", temperature: "Cel" };
const measurements = () => Object.fromEntries(Object.entries({ respiratory_rate: "18", spo2: "98", systolic_bp: "120", pulse_rate: "80", temperature: "36.5" }).map(([key, value]) => [key, { value, unit: units[key], absent_reason: null }]));
const profile = (overrides = {}) => ({ rule_profile_id: profileId, name: "合成固定规则审核", rule_id: "news2_2017", recipe_digest: hashes.recipe, recipe: { version: "news2_decimal_v1" }, input_policy: { point_selection: "one_original_point" }, content_hash: hashes.profile, source_id: `risk_rule_profile:${profileId}:${hashes.profile.slice(0, 12)}`, governance_hash: hashes.governance, evidence_reference: "synthetic-rule-reference", rationale: note, status: "published", revision: 2, created_at: asOf, published_at: asOf, ...overrides });
const point = () => ({ observation_id: pointId, patient_id: 11, admission_id: admission, observed_at: stamp, recorded_at: recorded, content_hash: hashes.point, source_id: `inpatient_observation:${pointId}:${hashes.point.slice(0, 12)}`, status: "active", revision: 1, payload: { measurements: measurements(), supplemental_oxygen: "no", consciousness: { system: "ACVPU", code: "alert" } } });
function assessment(body = {}) {
  const original = point(), rule = profile();
  const attestation = { patient_id: 11, admission_id: admission, window_id: windowId, expected_window_hash: hashes.window, point_id: pointId, expected_point_hash: hashes.point, rule_profile_id: profileId, expected_rule_profile_hash: hashes.profile, age_at_observation_years: 30, age_basis_note: note, pregnancy_status: "not_pregnant", pregnancy_basis_note: note, spo2_scale: 1, scale2_review: null, ...body };
  const metadata = { assessment_id: assessmentId, patient_id: attestation.patient_id, admission_id: attestation.admission_id, window_id: attestation.window_id, window_content_hash: attestation.expected_window_hash, point_id: attestation.point_id, point_content_hash: attestation.expected_point_hash, rule_profile_id: attestation.rule_profile_id, rule_profile_content_hash: attestation.expected_rule_profile_hash, recipe_digest: hashes.recipe, observed_at: stamp, created_at: asOf, created_by: 7, schema_version: "news2_assessment_v1", content_hash: hashes.assessment, source_id: `news2_assessment:${assessmentId}:${hashes.assessment.slice(0, 12)}`, governance_hash: hashes.governance, status: "active", revision: 1 };
  original.patient_id = metadata.patient_id; original.admission_id = metadata.admission_id;
  const specialist = { assessment_id: metadata.assessment_id, source_id: metadata.source_id, content_hash: metadata.content_hash, source_governance_hash: metadata.governance_hash, window_id: metadata.window_id, window_source_id: `observation_window:${metadata.window_id}:${hashes.window.slice(0, 12)}`, window_content_hash: metadata.window_content_hash, as_of: asOf, point_id: metadata.point_id, point_source_id: original.source_id, observed_at: stamp, recorded_at: recorded, rule_profile_id: metadata.rule_profile_id, rule_profile_source_id: rule.source_id, rule_profile_content_hash: metadata.rule_profile_content_hash, rule_profile_governance_hash: rule.governance_hash, rule_id: "news2_2017", recipe_digest: hashes.recipe, age_at_observation_years: attestation.age_at_observation_years, pregnancy_status: attestation.pregnancy_status, spo2_scale: attestation.spo2_scale, scale2_review: attestation.scale2_review ? { hypercapnic_respiratory_failure_confirmed: true, clinical_decision_confirmed: true, target_range: "88-92", blood_gas_reference_hash: "1".repeat(64), clinical_decision_reference_hash: "2".repeat(64) } : null, measurements: clone(original.payload.measurements), supplemental_oxygen: "no", consciousness: { system: "ACVPU", code: "alert" }, conflict_codes: [] };
  return { ...metadata, snapshot: { ...metadata, point: original, rule_profile: rule, window_binding: { window_id: metadata.window_id, content_hash: hashes.window, source_id: specialist.window_source_id, as_of: asOf }, attestation, author_qualification: { actor_id: 7, role_at_creation: "doctor", doctor_id: attestation.spo2_scale === 2 ? 1 : null, doctor_user_id: attestation.spo2_scale === 2 ? 7 : null, care_authorization: "authorized_original_admission_at_creation", authorized_at: asOf, scale2_decision_signed: attestation.spo2_scale === 2 } }, specialist_source: specialist, eligible: true, exclusion_reasons: [], freshness: { state: "current" }, can_revoke: true };
}
function analysisFor(source, scores = [0, 0, 0, 0, 0, 0, 0], scope = "within_declared_scope") {
  const components = keys.map((key, i) => ({ key, raw_value: key === "supplemental_oxygen" ? source.supplemental_oxygen : key === "consciousness" ? `${source.consciousness.system}:${source.consciousness.code}` : source.measurements[key]?.value ?? null, unit: units[key] || null, observed_at: source.observed_at, source_id: source.point_source_id, score: scope === "within_declared_scope" ? scores[i] : null, status: scope !== "within_declared_scope" ? scope === "unknown" ? "requires_review" : "outside_scope" : scores[i] === null ? "missing" : "scored", reason: "synthetic_ui_only" }));
  const scored = components.filter(row => row.score !== null), red = components.filter(row => row.score === 3).map(row => row.key), subtotal = scope === "within_declared_scope" ? scored.reduce((sum, row) => sum + row.score, 0) : null, complete = scored.length === 7;
  const band = subtotal >= 7 ? "high" : subtotal >= 5 ? "medium" : red.length ? "single_red" : subtotal === 0 ? complete ? "zero" : null : "low";
  return { schema_version: "1", source_binding: clone(source), rule_id: "news2_2017", calculation_status: scope === "outside_scope" ? "outside_scope" : complete ? "computed" : "insufficient_data", scope_status: scope, components, total_score: complete ? subtotal : null, observed_subtotal: subtotal, scored_component_count: scored.length, minimum_classification: scope === "within_declared_scope" ? band : null, score_is_lower_bound: scope === "within_declared_scope" && !complete, red_flag_components: red, classification: complete ? band : null, missing_data: complete ? [] : ["合成缺项，不能补0"], warnings: ["合成UI回执，不是临床验证"], local_runtime: { engine: "stdlib-news2-rules", rule_id: "news2_2017", recipe_digest: source.recipe_digest, runtime_digest: "9".repeat(64), model_version: `news2:${"9".repeat(64)}`, prompt_handling: "provenance_only", clinical_validation: "not_provided", population_applicability: "not_independently_verified", independent_implementation: true, python_version: "3.13.5", engine_versions: { fastapi: "0.115.0", pydantic: "2.12.0" }, implementation: { "news2_contract.py": "1".repeat(64), "news2_model.py": "2".repeat(64), "news2_config.py": "3".repeat(64), "news2_server.py": "4".repeat(64) } }, instructions_digest: "8".repeat(64), attribution: "Royal College of Physicians, 2017. Independent implementation; not certified by RCP.", rule_references: ["https://www.rcp.ac.uk/resources/national-early-warning-score-news-2/", "https://www.rcp.ac.uk/media/alxev00t/news2-chart-1_the-news-scoring-system_0_0.pdf", "https://www.rcp.ac.uk/media/2acdezkd/news2-chart-2_news-thresholds-and-triggers_0.pdf", "https://www.rcp.ac.uk/media/umzn4ntq/news2_additional-guidance-002-_0.pdf"], independent_implementation: true, clinical_validation: "not_provided" };
}

const secondAdmission = "77777777-7777-4777-8777-777777777777";
const runtimeModel = `news2:${"9".repeat(64)}`;
function windowFixture(original) {
  const snapshot = { window_id: windowId, source_id: `observation_window:${windowId}:${hashes.window.slice(0, 12)}`, content_hash: hashes.window, patient_id: 11, admission_id: admission, schema_version: "inpatient_window_v1", start_at: "2020-01-01T00:00:00.123456Z", end_at: "2020-01-01T01:00:00.123456Z", as_of: asOf, created_at: asOf, points: [clone(original)], urine_intervals: [], quality: { measurement_gaps: [], missing_by_point: [], same_time_groups: [], urine: { overlap_groups: [], excluded_intervals: [], uncovered_intervals: [] } }, limitations: ["仅合成离散原点，不是连续监护"] };
  return { ...snapshot, snapshot, status: "active", revision: 1, freshness: { state: "current" }, can_revoke: true };
}
function responseRun(state, status = "succeeded") {
  return { run_id: "synthetic-news2-dist-run", feature_key: "deterioration_risk", feature_name: "病情恶化预警", patient_id: 11, encounter_ref: admission, status, news2_findings: status === "succeeded" ? { news2_source: clone(state.source.specialist_source), news2_assessment: clone(state.source) } : null, evidence: clone(state.evidence), result: status === "succeeded" ? { summary: "合成NEWS2主应用回执，仅UI绑定测试", sections: [], warnings: [], missing_data: [], news2_analysis: analysisFor(state.source.specialist_source, state.scores) } : null };
}
async function session(page, options = {}) {
  const row = assessment();
  const state = { role: "doctor", mode: "news2", source: row, scores: [0, 0, 0, 0, 0, 0, 0], reads: [], contexts: [], runs: [], writes: [], checks: [], completed: [], releases: {}, hold: null, runStatus: "succeeded", getRunCount: 0, mutateDetail: null, ...options };
  if (state.six || state.partial) {
    for (const values of [state.source.snapshot.point.payload.measurements, state.source.specialist_source.measurements]) { values.respiratory_rate.value = "8"; values.spo2.value = "90"; if (state.partial) values.temperature = { value: null, unit: "Cel", absent_reason: "not_performed" }; }
    state.scores = [3, 3, 0, 0, state.partial ? null : 0, 0, 0];
  }
  state.window = windowFixture(state.source.snapshot.point);
  state.evidence = [{ source_id: state.source.source_id, title: "合成原评估依据", content: JSON.stringify(state.source.snapshot) }, { source_id: state.source.specialist_source.point_source_id, title: "合成原点测", content: JSON.stringify(state.source.snapshot.point) }, { source_id: state.source.specialist_source.rule_profile_source_id, title: "合成规则审核", content: JSON.stringify(profile()) }];
  state.providers = [{ provider_id: 41, revision: 3, name: "合成本地NEWS2服务", model: "待核对旧规则版本", kind: "specialist", api_base: "http://localhost:8814", enabled: false, allows_patient_data: false, timeout_seconds: 40, max_output_tokens: 2000, supported_features: ["deterioration_risk"], has_api_key: true, validation_report: "合成管理回执；没有本项目临床验证" }];
  await page.addInitScript(() => localStorage.setItem("hoim-token", "synthetic-news2-production-dist"));
  await page.route("**/api/**", async route => {
    const request = route.request(), url = new URL(request.url()), path = url.pathname, method = request.method(), params = Object.fromEntries(url.searchParams);
    let data = [], category = null;
    if (method === "GET") state.reads.push({ path, params });
    if (path === "/api/userInfo") data = { username: "合成NEWS2主应用复核", permissions: [state.role], avatar: "" };
    if (["/api/ai/features", "/api/ai/admin/features"].includes(path)) data = [{ key: "deterioration_risk", number: 41, name: "病情恶化预警", category: "inpatient", scope: "patient", engine: "prediction", input_mode: state.mode, enabled: true, inputs: ["明确原住院与单个原点测"], deliverables: ["确定性分项和已知下界"], source_reference_keys: state.mode === "news2" ? ["observation_window_id", "news2_assessment_id"] : ["observation_window_id"], allowed_roles: ["doctor", "super_admin"], default_roles: ["doctor"], validation_status: "unreviewed", prompt_version: 1 }];
    if (path === "/api/ai/patients") data = [{ patient_id: 11, label: "合成患者甲" }, { patient_id: 22, label: "合成患者乙" }];
    if (path === "/api/ai/encounters") data = [{ encounter_ref: params.patient_id === "22" ? secondAdmission : admission, kind: "inpatient", label: "住院 · 合成原记录" }];
    if (path === "/api/ai/observation-windows") { const summary = clone(state.window); delete summary.snapshot; summary.freshness = { state: "not_checked" }; data = params.patient_id === "11" ? [summary] : []; }
    if (path === `/api/ai/observation-windows/${windowId}`) data = clone(state.window);
    if (path === "/api/ai/news2-assessments" && method === "GET") data = { items: state.source.status === "active" ? [clone(state.source)] : [], total: state.source.status === "active" ? 1 : 0, page: 1, page_size: 50 };
    if (path === `/api/ai/news2-assessments/${assessmentId}` && method === "GET") { data = clone(state.source); state.mutateDetail?.(data); }
    if (path === `/api/ai/news2-assessments/${assessmentId}/revoke` && method === "POST") { Object.assign(state.source, { status: "revoked", revision: 2, eligible: false, can_revoke: false, specialist_source: null, freshness: { state: "revoked" } }); data = clone(state.source); category = "revoke"; }
    if (path === "/api/ai/admin/risk-rule-profiles/options") data = { items: [{ rule_id: "news2_2017", recipe_digest: hashes.recipe, recipe: profile().recipe, input_policy: profile().input_policy }], clinical_validation: "not_provided" };
    if (path === "/api/ai/admin/risk-rule-profiles") data = { items: [profile()], total: 1, page: 1, page_size: 50 };
    if (path === `/api/ai/admin/risk-rule-profiles/${profileId}`) data = profile();
    if (path === "/api/ai/admin/news2-assessments") data = { items: [clone(state.source)], total: 1, page: 1, page_size: 50 };
    if (path === `/api/ai/admin/news2-assessments/${assessmentId}`) data = clone(state.source);
    if (path === "/api/ai/admin/providers") data = clone(state.providers);
    if (path === "/api/ai/admin/providers/41/news2-capabilities") {
      category = "capability"; state.checks.push(request.postDataJSON());
      data = { provider_id: 41, provider_revision: 3, configured_model: state.providers[0].model, compatible: false, issues: ["合成登记版本与服务运行版本不同", "<img src=x onerror=alert('不执行')>"], scope_note: "只核对服务声明，不发送原点测或自动保存启用。", capabilities: { schema_version: "6", feature_key: "deterioration_risk", model_version: runtimeModel, engine: "stdlib-news2-rules", recipe_digest: hashes.recipe, runtime_digest: "9".repeat(64), python_version: "3.13.5", engine_versions: { fastapi: "0.115.0", pydantic: "2.12.0" }, max_request_bytes: 131072, timeout_seconds: 30, prompt_handling: "provenance_only", clinical_validation: "not_provided" } };
    }
    if (path === "/api/ai/context") { state.contexts.push(request.postDataJSON()); data = { context: { observation_window: clone(state.window.snapshot), ...(state.mode === "news2" ? { news2_source: clone(state.source.specialist_source), news2_assessment: clone(state.source) } : {}) }, evidence: clone(state.evidence) }; category = "context"; }
    if (path === "/api/ai/runs" && method === "POST") { state.runs.push(request.postDataJSON()); data = responseRun(state, state.runStatus); category = "create-run"; }
    if (path === "/api/ai/runs/synthetic-news2-dist-run" && method === "GET") { state.getRunCount++; data = responseRun(state, state.nextRunStatus || state.runStatus); category = `poll-${state.getRunCount}`; }
    if (path === "/api/ai/runs/synthetic-news2-dist-run/cancel" && method === "POST") { state.nextRunStatus = "cancelled"; data = responseRun(state, "cancelled"); category = "cancel"; }
    if (method !== "GET" && !["/api/userInfo", "/api/ai/context", "/api/ai/runs", "/api/ai/admin/providers/41/news2-capabilities"].includes(path)) state.writes.push({ path, method, body: request.postData() ? request.postDataJSON() : null });
    const wait = state.hold?.({ path, method, category });
    if (wait) await new Promise(resolve => { state.releases[wait] = resolve; });
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ code: 200, msg: "synthetic production-dist API reply", data }) });
    if (wait) state.completed.push(wait);
  });
  return state;
}
async function select(page, label, option) { const input = page.getByRole("combobox", { name: label, exact: true }); await expect(input).toBeEnabled(); await input.press("ArrowDown"); await page.locator(`#${await input.getAttribute("aria-controls")}`).getByRole("option", { name: option, exact: true }).click(); }
async function openRisk(page, state, chooseAssessment = true) {
  await page.goto("/#/ai/workbench?feature=deterioration_risk"); await select(page, "患者", "合成患者甲"); await select(page, "本次就诊", "住院 · 合成原记录");
  await select(page, "原住院观测窗", `${state.window.start_at} 至 ${state.window.end_at} · 可用截止 ${state.window.as_of} · ${windowId.slice(0, 8)}`);
  if (chooseAssessment) await selectAssessment(page);
}
async function selectAssessment(page) { await select(page, "待计算NEWS2评估来源", `${stamp} · ${assessmentId} · 活动来源`); }
async function mutateStore(page, type) { await page.evaluate(type => { const store = document.querySelector("#hoim").__vue_app__.config.globalProperties.$store; if (type === "role") store.commit("user/setPermissions", ["admin"]); else store.commit("user/setAccessToken", "new-synthetic-news2-session"); }, type); }
const generate = page => page.getByRole("button", { name: "生成辅助建议", exact: true });

test("超管主应用实际挂载NEWS2固定审核与冻结评估审计，不自动计算或启用", async ({ page }) => {
  const state = await session(page, { role: "super_admin" }); await page.goto("/#/ai/manage"); await page.getByRole("tab", { name: "风险规则与评估", exact: true }).click();
  const panel = page.getByLabel("固定风险规则与评估来源治理", { exact: true }); await expect(panel).toContainText("合成固定规则审核"); await panel.getByRole("button", { name: "核对规则审核版本", exact: true }).click();
  const rule = page.getByRole("dialog", { name: "固定风险规则审核", exact: true }); await expect(rule).toContainText(profileId); await expect(rule).toContainText(hashes.recipe); await rule.getByRole("button", { name: "关闭", exact: true }).click();
  await panel.getByRole("tab", { name: "NEWS2评估全院审计", exact: true }).click(); await panel.getByRole("button", { name: "核对冻结NEWS2评估", exact: true }).click(); const audit = page.getByRole("dialog", { name: "NEWS2冻结评估审计", exact: true }); await expect(audit).toContainText(assessmentId); await expect(audit).toContainText(stamp); await expect(audit).toContainText(note);
  for (const path of ["/api/ai/admin/risk-rule-profiles/options", "/api/ai/admin/risk-rule-profiles", "/api/ai/admin/news2-assessments"]) expect(state.reads.some(item => item.path === path)).toBe(true);
  expect(state.runs).toEqual([]); expect(state.writes).toEqual([]); expect(state.contexts).toEqual([]);
});

test("主应用NEWS2服务核对只填待保存模型，保留关闭状态和原验证说明", async ({ page }) => {
  const state = await session(page, { role: "super_admin" }); await page.goto("/#/ai/manage"); await page.getByRole("tab", { name: "模型服务", exact: true }).click(); await page.getByRole("button", { name: "检查本地NEWS2服务", exact: true }).click();
  const report = page.getByRole("dialog", { name: "本地NEWS2规则服务核对", exact: true }); for (const text of [runtimeModel, "不拼接异时最新值", "完整总分未知", "not_provided", hashes.recipe, "9".repeat(64), "<img src=x onerror=alert('不执行')>"]) await expect(report).toContainText(text); await expect(report.locator("img")).toHaveCount(0);
  await report.getByRole("button", { name: "填写实际模型，待保存", exact: true }).click(); const edit = page.getByRole("dialog", { name: "编辑模型服务", exact: true }); await expect(edit.locator(".el-form-item").filter({ hasText: "模型标识" }).getByRole("textbox")).toHaveValue(runtimeModel); await expect(edit.locator(".el-form-item").filter({ hasText: "适配器验证报告" }).getByRole("textbox")).toHaveValue(state.providers[0].validation_report); await expect(edit.locator(".el-form-item").filter({ hasText: "服务启用" }).getByRole("switch")).not.toBeChecked(); await expect(edit.locator(".el-form-item").filter({ hasText: "患者资料传输" }).getByRole("switch")).not.toBeChecked();
  expect(state.checks).toEqual([{ expected_revision: 3 }]); expect(state.writes).toEqual([]); expect(state.runs).toEqual([]); expect(state.contexts).toEqual([]);
});

test("主应用NEWS2能力检查途中角色或会话改变，迟到回执不能填表", async ({ page }) => {
  const state = await session(page, { role: "super_admin", hold: ({ category }) => category === "capability" ? "capability" : null });
  for (const change of ["role", "session"]) {
    await page.goto("/#/ai/manage"); if (change === "session") await page.reload(); await page.getByRole("tab", { name: "模型服务", exact: true }).click(); await page.getByRole("button", { name: "检查本地NEWS2服务", exact: true }).click(); await expect.poll(() => !!state.releases.capability).toBe(true);
    await mutateStore(page, change); await expect(page.getByRole("dialog", { name: "本地NEWS2规则服务核对", exact: true })).toBeHidden(); state.releases.capability(); await expect.poll(() => state.completed.length).toBe(change === "role" ? 1 : 2); delete state.releases.capability; await expect(page.getByRole("dialog", { name: "编辑模型服务", exact: true })).toHaveCount(0);
  }
  expect(state.checks).toEqual([{ expected_revision: 3 }, { expected_revision: 3 }]); expect(state.writes).toEqual([]); expect(state.runs).toEqual([]);
});

test("医生NEWS2必须双引用，预览与提交一致且提交期间保留来源后接收六分结果", async ({ page }) => {
  const state = await session(page, { six: true, hold: ({ category }) => category === "create-run" ? "run" : null }); await openRisk(page, state, false); await expect(generate(page)).toBeDisabled(); await expect(page.getByRole("button", { name: "查看本次资料", exact: true })).toBeDisabled(); await selectAssessment(page); await expect(generate(page)).toBeEnabled();
  await page.getByRole("button", { name: "查看本次资料", exact: true }).click(); const preview = page.getByRole("dialog", { name: "本次提供给 AI 的患者资料", exact: true }); await expect(preview.getByLabel("NEWS2原点测量只读资料", { exact: true })).toContainText("8"); await expect(preview).toContainText("原测量不等于已评分"); await preview.getByRole("button", { name: "核对NEWS2评估原依据", exact: true }).click(); const evidence = page.getByRole("dialog", { name: "核查引用依据", exact: true }); await expect(evidence).toContainText(assessmentId); await expect(evidence).toContainText("age_basis_note"); await evidence.locator(".el-dialog__headerbtn").click(); await preview.locator(".el-dialog__headerbtn").click();
  await generate(page).click(); await expect.poll(() => !!state.releases.run).toBe(true); const input = page.getByLabel("NEWS2评估来源登记与选择", { exact: true }); await expect(input).toContainText(`已核对 ${assessmentId}`); await expect(input.getByRole("combobox", { name: "待计算NEWS2评估来源", exact: true })).toBeEnabled(); await expect(input.locator(".el-select__selected-item").filter({ hasText: `${stamp} · ${assessmentId} · 活动来源` })).toBeVisible(); state.releases.run();
  const result = page.getByLabel("AI任务结果", { exact: true }); await expect(result.getByLabel("NEWS2完整总分", { exact: true })).toHaveText("完整总分 6；规则等级 中等级。"); await expect(result.getByLabel("NEWS2七项原值与分值", { exact: true }).getByRole("row").filter({ hasText: "补充氧" })).toContainText("0"); await expect(result).toContainText(stamp); await expect(result).toContainText("未获RCP认证或背书");
  expect(state.contexts).toEqual([{ feature_key: "deterioration_risk", patient_id: 11, encounter_ref: admission, source_refs: { observation_window_id: windowId, news2_assessment_id: assessmentId } }]); expect(state.runs).toHaveLength(1); expect(state.runs[0]).toMatchObject({ patient_id: 11, encounter_ref: admission, input: { observation_window_id: windowId, news2_assessment_id: assessmentId, question: "" } }); expect(state.writes).toEqual([]);
});

test("主应用部分资料显示已知六分下界和红项，体温未测不补零或输出完整总分", async ({ page }) => {
  const state = await session(page, { partial: true }); await openRisk(page, state); await generate(page).click(); const result = page.getByLabel("AI任务结果", { exact: true }); await expect(result.getByLabel("NEWS2已知分项下界", { exact: true })).toContainText("至少 6（6/7项）"); await expect(result.getByLabel("NEWS2已知分项下界", { exact: true })).toContainText("中等级"); await expect(result.getByLabel("NEWS2完整总分", { exact: true })).toHaveCount(0); await expect(result).toContainText("单项红项：呼吸率、SpO₂"); const temperature = result.getByLabel("NEWS2七项原值与分值", { exact: true }).getByRole("row").filter({ hasText: "体温" }); await expect(temperature).toContainText("未提供"); await expect(temperature).toContainText("未计算"); expect(state.runs[0].input).toEqual({ observation_window_id: windowId, news2_assessment_id: assessmentId, question: "" }); expect(state.writes).toEqual([]);
});

test("主应用评估撤销请求尚未返回即清除选择并禁止预览与生成", async ({ page }) => {
  const state = await session(page, { hold: ({ category }) => category === "revoke" ? "revoke" : null }); await openRisk(page, state); await expect(generate(page)).toBeEnabled(); const input = page.getByLabel("NEWS2评估来源登记与选择", { exact: true }); await input.getByRole("textbox", { name: "NEWS2评估撤销依据", exact: true }).fill("合成核实点测来源关联错误后撤销"); await input.getByRole("button", { name: "撤销所选NEWS2评估", exact: true }).click(); await expect.poll(() => !!state.releases.revoke).toBe(true); await expect(generate(page)).toBeDisabled(); await expect(page.getByRole("button", { name: "查看本次资料", exact: true })).toBeDisabled(); await expect(page.getByRole("combobox", { name: "待计算NEWS2评估来源", exact: true })).toHaveValue(""); state.releases.revoke(); await expect(page.getByText("原评估来源已撤销，请重新核实并明确选择，旧选择不能继续使用。", { exact: true })).toBeVisible();
  expect(state.writes).toEqual([{ path: `/api/ai/news2-assessments/${assessmentId}/revoke`, method: "POST", body: { patient_id: 11, admission_id: admission, expected_revision: 1, reason: "合成核实点测来源关联错误后撤销" } }]); expect(state.runs).toEqual([]); expect(state.contexts).toEqual([]);
});

test("主应用取消队列任务后迟到成功轮询不恢复NEWS2分值", async ({ page }) => {
  const state = await session(page, { runStatus: "queued", hold: ({ category }) => category === "poll-1" ? "poll" : category === "cancel" ? "cancel" : null }); await openRisk(page, state); await generate(page).click(); await expect(page.getByLabel("AI任务结果", { exact: true })).toContainText("正在等待处理"); state.nextRunStatus = "succeeded"; await expect.poll(() => !!state.releases.poll).toBe(true); await page.getByRole("button", { name: "取消接收结果", exact: true }).click(); await expect.poll(() => !!state.releases.cancel).toBe(true); await expect(generate(page)).toBeDisabled(); state.releases.cancel(); await expect(page.getByLabel("AI任务结果", { exact: true })).toContainText("已取消"); state.releases.poll(); await expect.poll(() => state.completed.includes("poll")).toBe(true); await expect(page.getByLabel("NEWS2完整总分", { exact: true })).toHaveCount(0); await expect(page.getByLabel("NEWS2确定性计算复核", { exact: true })).toHaveCount(0); await expect(page.getByLabel("AI任务结果", { exact: true })).toContainText("已取消"); expect(state.runs).toHaveLength(1); expect(state.writes.map(item => item.path)).toEqual(["/api/ai/runs/synthetic-news2-dist-run/cancel"]);
});

test("主应用评估嵌套患者住院窗口或原点串源均拒绝，不能预览或提交", async ({ page }) => {
  const state = await session(page);
  const mutations = [row => { row.snapshot.point.patient_id = 22; }, row => { row.snapshot.admission_id = secondAdmission; }, row => { row.snapshot.window_binding.window_id = "88888888-8888-4888-8888-888888888888"; }, row => { row.specialist_source.point_id = "99999999-9999-4999-8999-999999999999"; }];
  for (const mutate of mutations) { state.mutateDetail = mutate; await page.reload(); await openRisk(page, state); await expect(page.getByText("原评估、窗口、点测或规则已变化，不能作为当前计算来源", { exact: true })).toBeVisible(); await expect(generate(page)).toBeDisabled(); await expect(page.getByRole("button", { name: "查看本次资料", exact: true })).toBeDisabled(); await expect(page.getByLabel("NEWS2七项原值与分值", { exact: true })).toHaveCount(0); }
  expect(state.runs).toEqual([]); expect(state.contexts).toEqual([]); expect(state.writes).toEqual([]);
});

test("主应用患者或会话切换后拒绝迟到NEWS2任务回执，不带回旧选择", async ({ page }) => {
  const state = await session(page, { hold: ({ category }) => category === "create-run" ? "run" : null });
  for (const change of ["patient", "session"]) { if (change === "session") await page.reload(); await openRisk(page, state); await generate(page).click(); await expect.poll(() => !!state.releases.run).toBe(true); if (change === "patient") await select(page, "患者", "合成患者乙"); else await mutateStore(page, "session"); state.releases.run(); await expect.poll(() => state.completed.filter(item => item === "run").length).toBe(change === "patient" ? 1 : 2); delete state.releases.run; await expect(page.getByLabel("AI任务结果", { exact: true })).toHaveCount(0); await expect(page.getByLabel("NEWS2确定性计算复核", { exact: true })).toHaveCount(0); await expect(generate(page)).toBeDisabled(); await expect(page.getByRole("combobox", { name: "待计算NEWS2评估来源", exact: true })).toHaveCount(0); }
  expect(state.runs).toHaveLength(2); expect(state.writes).toEqual([]);
});

test("原41外部观测窗模式仍仅需明确窗口，不强制NEWS2来源或冒称规则计算", async ({ page }) => {
  const state = await session(page, { mode: "observation_window" }); await openRisk(page, state, false); await expect(generate(page)).toBeEnabled(); await expect(page.getByLabel("NEWS2评估来源登记与选择", { exact: true })).toHaveCount(0); await page.getByRole("button", { name: "查看本次资料", exact: true }).click(); const preview = page.getByRole("dialog", { name: "本次提供给 AI 的患者资料", exact: true }); await expect(preview.getByLabel("NEWS2确定性计算复核", { exact: true })).toHaveCount(0); expect(state.contexts[0].source_refs).toEqual({ observation_window_id: windowId }); expect(state.reads.some(item => item.path.includes("news2-assessments"))).toBe(false); expect(state.runs).toEqual([]); expect(state.writes).toEqual([]);
});

