const { test, expect } = require("@playwright/test");
const { startNews2Harness } = require("./fixtures/news2-source-harness.cjs");
// Actual Vue/ElementPlus/request/API components with synthetic API replies. This
// suite verifies presentation and binding, not backend or clinical correctness.
let harness;
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

test.beforeAll(async () => { harness = await startNews2Harness(); });
test.afterAll(async () => { await harness?.close(); });
async function session(page, config = {}) {
  const state = { sources: [], profiles: [profile()], writes: [], reads: [], modelCalls: [], forbidden: [], release: null, delayed: null, canScale2: false, mutateDetail: null, ...config };
  await page.context().route("**/*", route => new URL(route.request().url()).origin === harness.origin ? route.continue() : route.abort("blockedbyclient"));
  await page.route("**/api/**", async route => {
    const request = route.request(), url = new URL(request.url()), path = url.pathname, method = request.method(); let data;
    if (/\/ai\/(runs|context|admin\/features)(\/|$)/.test(path)) { state.modelCalls.push(path); data = {}; }
    else if (method === "GET") {
      state.reads.push({ path, query: Object.fromEntries(url.searchParams) });
      if (path.endsWith("/candidates")) data = { window: { window_id: windowId, patient_id: 11, admission_id: admission, content_hash: hashes.window, as_of: asOf }, points: [point()], rule_profiles: state.profiles.filter(row => row.status === "published"), can_create_scale2: state.canScale2, conflict_groups: [] };
      else if (path.endsWith("/options")) data = { items: state.ruleOptions || [{ rule_id: "news2_2017", recipe_digest: hashes.recipe, recipe: {}, input_policy: {} }], clinical_validation: "not_provided" };
      else if (/\/(news2-assessments|risk-rule-profiles)$/.test(path)) { const rows = path.includes("risk-rule-profiles") ? state.profiles.filter(row => !url.searchParams.get("rule_id") || row.rule_id === url.searchParams.get("rule_id")) : (state.sourcePages?.[url.searchParams.get("page") || "1"] || state.sources).filter(row => String(row.patient_id) === (url.searchParams.get("patient_id") || String(row.patient_id)) && row.admission_id === (url.searchParams.get("admission_id") || row.admission_id)); data = { items: clone(rows), total: state.sourcePages && !path.includes("risk-rule-profiles") ? 51 : rows.length, page: Number(url.searchParams.get("page") || 1), page_size: 50 }; }
      else { const id = decodeURIComponent(path.split("/").at(-1)); data = clone((path.includes("risk-rule-profiles") ? state.profiles : state.sources).find(row => (row.rule_profile_id === id || row.assessment_id === id))); if (state.mutateDetail) state.mutateDetail(data); }
    } else {
      const body = request.postDataJSON(); state.writes.push({ path, body });
      if (path.endsWith("/publish") || path.endsWith("/revoke")) { const id = decodeURIComponent(path.split("/").at(-2)), row = (path.includes("risk-rule-profiles") ? state.profiles : state.sources).find(row => row.rule_profile_id === id || row.assessment_id === id); Object.assign(row, { status: path.endsWith("/publish") ? "published" : "revoked", revision: row.revision + 1 }); if (row.assessment_id) Object.assign(row, { specialist_source: null, can_revoke: false, eligible: false }); data = clone(row); }
      else if (path.endsWith("/risk-rule-profiles")) { data = profile({ rule_profile_id: "66666666-6666-4666-8666-666666666666", ...body, recipe_digest: body.expected_recipe_digest, status: "draft", revision: 1, published_at: null }); state.profiles.push(clone(data)); }
      else if (path.endsWith("/news2-assessments")) { data = assessment(body); state.sources.push(clone(data)); }
      else { state.forbidden.push({ path, method }); data = {}; }
    }
    if (state.delayed?.(method, path)) await new Promise(resolve => { state.release = resolve; });
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ code: 200, msg: "synthetic", data }) });
  });
  await page.goto(harness.origin); await page.waitForFunction(() => !!window.__news2Probe); return state;
}
async function select(page, name, option, scope = page) { const input = scope.getByRole("combobox", { name, exact: true }); await expect(input).toBeEnabled(); await input.press("ArrowDown"); await page.locator(`#${await input.getAttribute("aria-controls")}`).getByRole("option", { name: option, exact: true }).click(); }
async function draft(page) { await page.getByRole("button", { name: "登记单个原点测量的NEWS2评估来源", exact: true }).click(); const load = page.getByRole("button", { name: "读取本窗口原点测与审核规则", exact: true }); await expect(page.locator(".el-collapse-item__wrap").filter({ has: load })).not.toHaveClass(/el-collapse-transition-enter-active/); await load.click(); await expect(load).not.toHaveClass(/is-loading/); await select(page, "NEWS2原点测量", `${stamp} · ${pointId}`); await select(page, "NEWS2审核规则版本", "合成固定规则审核 · news2_2017 · v2"); }
async function attest(page, pregnancy = "已核实未妊娠", scale = "Scale 1") { await page.getByRole("textbox", { name: "NEWS2原观察时年龄", exact: true }).fill("30"); for (const name of ["NEWS2原年龄核实依据", "NEWS2妊娠状态核实依据"]) await page.getByRole("textbox", { name, exact: true }).fill(note); await select(page, "NEWS2妊娠状态", pregnancy); await select(page, "NEWS2血氧评分规则", scale); }
async function selected(page) { await select(page, "待计算NEWS2评估来源", `${stamp} · ${assessmentId} · 活动来源`); }
async function positiveSelections(page) { return page.evaluate(() => window.__news2Probe.events.filter(item => item.type === "selection" && item.value)); }
function noModel(state) { expect(state.modelCalls).toEqual([]); expect(state.forbidden).toEqual([]); }
async function admin(page) { await page.evaluate(() => { const p = window.__news2Probe; p.store.commit("user/permissions", ["super_admin"]); p.scope.mode = "management"; }); await expect(page.getByLabel("固定风险规则与评估来源治理", { exact: true })).toBeVisible(); }
function findingsWrapper(source) {
  const row = assessment({ age_at_observation_years: source.age_at_observation_years, pregnancy_status: source.pregnancy_status, spo2_scale: source.spo2_scale });
  row.specialist_source = clone(source);
  row.snapshot.point.payload.measurements = clone(source.measurements);
  row.snapshot.point.payload.supplemental_oxygen = source.supplemental_oxygen;
  row.snapshot.point.payload.consciousness = clone(source.consciousness);
  return row;
}
async function findings(page, source, analysis, sourceScope = null) { sourceScope = sourceScope ?? findingsWrapper(source); await page.evaluate(({ source, analysis, sourceScope }) => Object.assign(window.__news2Probe.scope, { mode: "findings", source, analysis, sourceScope }), { source, analysis, sourceScope }); return page.getByLabel("NEWS2确定性计算复核", { exact: true }); }

test("原单点与适用性不预填，登记只提交引用摘要及显式声明，不自动选中或计算", async ({ page }) => {
  const state = await session(page); await draft(page); await expect(page.getByRole("textbox", { name: "NEWS2原观察时年龄", exact: true })).toHaveValue(""); for (const name of ["NEWS2妊娠状态", "NEWS2血氧评分规则"]) await expect(page.getByRole("combobox", { name, exact: true })).toHaveValue(""); await expect(page.getByRole("button", { name: "仅登记NEWS2评估来源", exact: true })).toBeDisabled(); await attest(page); await page.getByRole("button", { name: "仅登记NEWS2评估来源", exact: true }).click(); await expect.poll(() => state.writes.length).toBe(1);
  expect(state.writes[0].body).toEqual({ patient_id: 11, admission_id: admission, window_id: windowId, expected_window_hash: hashes.window, point_id: pointId, expected_point_hash: hashes.point, rule_profile_id: profileId, expected_rule_profile_hash: hashes.profile, age_at_observation_years: 30, age_basis_note: note, pregnancy_status: "not_pregnant", pregnancy_basis_note: note, spo2_scale: 1, scale2_review: null }); await expect(page.getByText("评估来源已登记；请明确选择并复核，尚未调用模型或自动计算。", { exact: true })).toBeVisible(); expect(await positiveSelections(page)).toEqual([]); noModel(state);
});

test("妊娠未知来源可明确选中但不伪装成适用性验证，选择只发ID和摘要", async ({ page }) => {
  const state = await session(page, { sources: [assessment({ pregnancy_status: "unknown" })] }); await selected(page); await expect.poll(() => positiveSelections(page)).toEqual([{ type: "selection", value: { news2_assessment_id: assessmentId, content_hash: hashes.assessment } }]); await page.getByRole("button", { name: "核对所选NEWS2原来源", exact: true }).click(); await expect(page.getByRole("dialog", { name: "NEWS2原评估来源复核", exact: true })).toContainText("妊娠 unknown"); expect(state.writes).toEqual([]); noModel(state);
});

test("Super身份没有服务临床授权时不能声明Scale2，不能自举临床资格", async ({ page }) => {
  const state = await session(page); await page.evaluate(() => window.__news2Probe.store.commit("user/permissions", ["super_admin"])); await draft(page); const input = page.getByRole("combobox", { name: "NEWS2血氧评分规则", exact: true }); await input.press("ArrowDown"); await expect(page.getByRole("option", { name: /Scale 2/ })).toHaveCount(0); expect(state.writes).toEqual([]); noModel(state);
});

test("Scale2声明须实际权限与血气/临床决定双依据，已有医生Scale2可护士选择", async ({ page }) => {
  const state = await session(page, { canScale2: true }); await draft(page); await attest(page, "已核实未妊娠", "Scale 2（须临床授权及独立依据）"); const submit = page.getByRole("button", { name: "仅登记NEWS2评估来源", exact: true }); await expect(submit).toBeDisabled(); for (const label of ["已核对血气确认的高碳酸性呼吸衰竭依据", "已核对临床决定使用Scale 2及88–92目标的记录"]) await page.getByText(label, { exact: true }).click(); for (const name of ["NEWS2血气确认依据", "NEWS2临床Scale2决定依据"]) await page.getByRole("textbox", { name, exact: true }).fill(note); await submit.click(); await expect.poll(() => state.writes.length).toBe(1); expect(state.writes[0].body.scale2_review).toEqual({ hypercapnic_respiratory_failure_confirmed: true, clinical_decision_confirmed: true, target_range: "88-92", blood_gas_reference: note, clinical_decision_reference: note }); await expect(page.getByText("评估来源已登记；请明确选择并复核，尚未调用模型或自动计算。", { exact: true })).toBeVisible(); await page.evaluate(() => window.__news2Probe.store.commit("user/permissions", ["nurse"])); await selected(page); await expect.poll(() => positiveSelections(page)).toHaveLength(1); noModel(state);
});

for (const change of ["patient", "admission", "window", "session", "role", "inactive"]) {
  test(`迟到登记不跨${change}恢复原选择或适用性草稿`, async ({ page }) => {
    const state = await session(page); await draft(page); await attest(page); state.delayed = (method, path) => method === "POST" && path.endsWith("/news2-assessments"); await page.getByRole("button", { name: "仅登记NEWS2评估来源", exact: true }).click(); await expect.poll(() => !!state.release).toBe(true); await page.evaluate(change => { const { scope, store } = window.__news2Probe; if (change === "patient") scope.patientId = 22; if (change === "admission") scope.admissionId = "77777777-7777-4777-8777-777777777777"; if (change === "window") scope.windowId = "88888888-8888-4888-8888-888888888888"; if (change === "session") store.commit("user/token", "new-news2-synthetic-session"); if (change === "role") store.commit("user/permissions", ["patient"]); if (change === "inactive") scope.active = false; }, change); state.release(); await expect.poll(() => positiveSelections(page)).toEqual([]); if (["role", "inactive"].includes(change)) await expect(page.getByRole("textbox", { name: "NEWS2原观察时年龄", exact: true })).toHaveCount(0); else await expect(page.getByRole("textbox", { name: "NEWS2原观察时年龄", exact: true })).toHaveValue(""); noModel(state);
  });
}

for (const wrong of ["nested_scope", "missing_projection", "wrong_profile", "wrong_value"]) {
  test(`选择评估拒绝${wrong}，不从元数据或旧选择补齐`, async ({ page }) => {
    const state = await session(page, { sources: [assessment()] }); state.mutateDetail = row => { if (wrong === "nested_scope") row.snapshot.point.admission_id = "other-admission"; if (wrong === "missing_projection") row.specialist_source = null; if (wrong === "wrong_profile") row.specialist_source.rule_profile_content_hash = "0".repeat(64); if (wrong === "wrong_value") row.specialist_source.measurements.pulse_rate.value = "0"; }; await selected(page); await expect(page.getByRole("alert")).toContainText("不能作为当前计算来源"); expect(await positiveSelections(page)).toEqual([]); noModel(state);
  });
}

test("撤销评估带原患者住院及expected_revision并清除当前可用选择", async ({ page }) => {
  const state = await session(page, { sources: [assessment()] }); await selected(page); await expect.poll(() => positiveSelections(page)).toHaveLength(1); await page.getByRole("textbox", { name: "NEWS2评估撤销依据", exact: true }).fill("合成原资料复核后撤销来源"); state.delayed = (method, path) => method === "POST" && path.endsWith("/revoke"); await page.getByRole("button", { name: "撤销所选NEWS2评估", exact: true }).click(); await expect.poll(() => !!state.release).toBe(true); expect(await page.evaluate(() => window.__news2Probe.events.at(-1))).toEqual({ type: "availability", value: false }); state.release(); await expect(page.getByText("原评估来源已撤销，请重新核实并明确选择，旧选择不能继续使用。", { exact: true })).toBeVisible(); expect(state.writes[0].body).toEqual({ patient_id: 11, admission_id: admission, expected_revision: 1, reason: "合成原资料复核后撤销来源" }); expect(await page.evaluate(() => window.__news2Probe.events.at(-1))).toEqual({ type: "availability", value: false }); noModel(state);
});

test("完整0总分及七个0分原样展示，不表述为无风险或患病概率", async ({ page }) => {
  const state = await session(page), source = assessment().specialist_source, view = await findings(page, source, analysisFor(source)); await expect(view.getByLabel("NEWS2完整总分", { exact: true })).toContainText("完整总分 0"); await expect(view.getByLabel("NEWS2七项原值与分值", { exact: true }).locator("tbody tr")).toHaveCount(7); await expect(view).toContainText("未获RCP认证或背书"); await expect(view).toContainText("不提供患病概率"); noModel(state);
});

for (const [name, scores, expected] of [["partial-high", [3, 3, 1, 0, null, 0, 0], "高等级"], ["partial-red", [3, 0, 0, 0, null, 0, 0], "单项3分红项"], ["partial-zero", [0, 0, 0, 0, null, 0, 0], "已知分项为0不表示低风险"]]) {
  test(`${name}保留已有分项下界与红项，完整总分缺失不填0`, async ({ page }) => {
    const state = await session(page), source = assessment().specialist_source; source.measurements.temperature = { value: null, unit: "Cel", absent_reason: "not_performed" }; if (name !== "partial-zero") source.measurements.respiratory_rate.value = "8"; if (name === "partial-high") { source.measurements.spo2.value = "90"; source.measurements.systolic_bp.value = "110"; } const view = await findings(page, source, analysisFor(source, scores)); await expect(view.getByLabel("NEWS2已知分项下界", { exact: true })).toContainText(expected); await expect(view.getByLabel("NEWS2完整总分", { exact: true })).toHaveCount(0); await expect(view).toContainText("完整总分未知"); noModel(state);
  });
}

for (const [scope, pregnancy] of [["unknown", "unknown"], ["outside_scope", "pregnant"]]) {
  test(`${scope}不把人群未核实或超出范围显示为0分`, async ({ page }) => {
    const state = await session(page), source = assessment({ pregnancy_status: pregnancy }).specialist_source, view = await findings(page, source, analysisFor(source, [], scope)); await expect(view).toContainText("未给出分项分数、合计或规则等级"); await expect(view.getByLabel("NEWS2完整总分", { exact: true })).toHaveCount(0); await expect(view.getByLabel("NEWS2已知分项下界", { exact: true })).toHaveCount(0); noModel(state);
  });
}

test("Findings拒绝外层住院串源及analysis另一原点评估绑定", async ({ page }) => {
  const state = await session(page), source = assessment().specialist_source, value = analysisFor(source); const view = await findings(page, source, value, { patient_id: 11, admission_id: "wrong-admission", window_id: windowId }); await expect(view.getByRole("alert")).toContainText("来源与原患者"); await expect(view.getByLabel("NEWS2七项原值与分值", { exact: true })).toHaveCount(0); value.source_binding.point_id = "99999999-9999-4999-8999-999999999999"; await findings(page, source, value); await expect(view.getByRole("alert")).toContainText("计算结果已拒绝展示"); noModel(state);
});

for (const [name, mutate] of [
  ["缺失冻结正文", row => { row.snapshot = null; }],
  ["原点患者串源", row => { row.snapshot.point.patient_id = 22; }],
  ["原脉搏与专用投影不一致", row => { row.snapshot.point.payload.measurements.pulse_rate.value = "123"; }],
]) {
  test(`Findings${name}拒绝分值和原测量展示`, async ({ page }) => {
    const state = await session(page), source = assessment().specialist_source, wrapper = findingsWrapper(source); mutate(wrapper);
    const view = await findings(page, source, analysisFor(source), wrapper); await expect(view.getByRole("alert")).toContainText("来源与原患者"); await expect(view.getByLabel("NEWS2完整总分", { exact: true })).toHaveCount(0); await expect(view.getByLabel("NEWS2七项原值与分值", { exact: true })).toHaveCount(0); await expect(view.getByLabel("NEWS2原点测量只读资料", { exact: true })).toHaveCount(0); noModel(state);
  });
}

test("Super固定规则草稿不自动发布，发布带固定recipe摘要与显式审核依据", async ({ page }) => {
  const state = await session(page); await admin(page); await page.getByRole("button", { name: "新建固定规则审核草稿", exact: true }).click(); let dialog = page.getByRole("dialog", { name: "新建固定规则审核草稿", exact: true }); await expect(dialog.getByRole("combobox", { name: "固定规则选项", exact: true })).toHaveValue(""); await select(page, "固定规则选项", "news2_2017", dialog); await dialog.getByRole("textbox", { name: "规则审核名称", exact: true }).fill("合成审核新版本"); await dialog.getByRole("textbox", { name: "规则依据标识", exact: true }).fill("synthetic-reference"); await dialog.getByRole("textbox", { name: "规则审核依据", exact: true }).fill(note); await dialog.getByRole("button", { name: "仅保存规则审核草稿", exact: true }).click(); await expect.poll(() => state.writes.length).toBe(1); expect(state.writes[0].body).toMatchObject({ rule_id: "news2_2017", expected_recipe_digest: hashes.recipe, name: "合成审核新版本" }); await expect(dialog).not.toBeVisible(); await page.getByRole("row").filter({ hasText: "合成审核新版本" }).getByRole("button", { name: "核对规则审核版本", exact: true }).click(); dialog = page.getByRole("dialog", { name: "固定风险规则审核", exact: true }); await expect(dialog.getByRole("button", { name: "审核并发布固定规则版本", exact: true })).toBeDisabled(); await dialog.getByText("我已核对固定规则版本、实现条款和输入策略", { exact: true }).click(); await dialog.getByRole("textbox", { name: "规则发布依据标识", exact: true }).fill("synthetic-review-reference"); await dialog.getByRole("textbox", { name: "规则发布审核说明", exact: true }).fill(note); await dialog.getByRole("button", { name: "审核并发布固定规则版本", exact: true }).click(); await expect.poll(() => state.writes.length).toBe(2); expect(state.writes[1].body).toEqual({ expected_revision: 1, expected_recipe_digest: hashes.recipe, implementation_terms_confirmed: true, review_note: note, review_evidence_reference: "synthetic-review-reference" }); await expect(dialog).toContainText("已发布 · v2"); await dialog.getByRole("textbox", { name: "固定风险治理撤销依据", exact: true }).fill("合成审查新证据后撤销规则版本"); await dialog.getByRole("button", { name: "撤销此规则版本", exact: true }).click(); await expect.poll(() => state.writes.length).toBe(3); expect(state.writes[2].body).toEqual({ expected_revision: 2, reason: "合成审查新证据后撤销规则版本" }); await expect(dialog).toContainText("已撤销 · v3"); noModel(state);
});

test("Super全院原评估审计保留0与适用性原声明，失去角色后迟到详情不展示", async ({ page }) => {
  const row = assessment(); row.snapshot.point.payload.measurements.pulse_rate.value = "0"; row.specialist_source.measurements.pulse_rate.value = "0";
  const state = await session(page, { sources: [row] }); await admin(page); await page.getByRole("tab", { name: "NEWS2评估全院审计", exact: true }).click(); await page.getByRole("button", { name: "核对冻结NEWS2评估", exact: true }).click(); const dialog = page.getByRole("dialog", { name: "NEWS2冻结评估审计", exact: true }); await expect(dialog.getByLabel("NEWS2审计冻结原测量", { exact: true }).getByRole("row").filter({ hasText: "pulse_rate" })).toContainText("0"); await expect(dialog).toContainText(note); await dialog.getByRole("button", { name: "关闭", exact: true }).click(); state.delayed = (method, path) => method === "GET" && path.endsWith(`/${assessmentId}`); await page.getByRole("button", { name: "核对冻结NEWS2评估", exact: true }).click(); await expect.poll(() => !!state.release).toBe(true); await page.evaluate(() => window.__news2Probe.store.commit("user/permissions", ["admin"])); state.release(); await expect(dialog).not.toBeVisible(); await expect(page.getByLabel("固定风险规则与评估来源治理", { exact: true })).toContainText("仅超级管理员"); noModel(state);
});


test("当前窗口评估目录可翻页，不把第一页未列来源当成无资料", async ({ page }) => {
  const state = await session(page, { sources: [assessment()], sourcePages: { 1: [], 2: [assessment()] } });
  await expect(page.getByText(/目录共 51 项/)).toBeVisible(); await page.locator(".el-pagination .btn-next").click(); await selected(page);
  await expect.poll(() => positiveSelections(page)).toHaveLength(1); expect(state.reads.some(read => read.path.endsWith("/news2-assessments") && read.query.window_id === windowId && read.query.page === "2")).toBe(true); noModel(state);
});

test("切换窗口后迟到旧评估详情不能恢复选择", async ({ page }) => {
  const state = await session(page, { sources: [assessment()] }); state.delayed = (method, path) => method === "GET" && path.endsWith(`/${assessmentId}`); await selected(page); await expect.poll(() => !!state.release).toBe(true);
  await page.evaluate(() => { window.__news2Probe.scope.windowId = "88888888-8888-4888-8888-888888888888"; }); state.release();
  await expect(page.getByRole("combobox", { name: "待计算NEWS2评估来源", exact: true })).toHaveValue(""); expect(await positiveSelections(page)).toEqual([]); noModel(state);
});


test("无模型原资料预览显示原0及未测，不伪装成已评分", async ({ page }) => {
  const state = await session(page), source = assessment().specialist_source; source.measurements.pulse_rate.value = "0"; source.measurements.temperature = { value: null, unit: "Cel", absent_reason: "not_performed" };
  const view = await findings(page, source, null); const raw = view.getByLabel("NEWS2原点测量只读资料", { exact: true }); await expect(raw.getByRole("row").filter({ hasText: "脉搏" })).toContainText("0"); await expect(raw.getByRole("row").filter({ hasText: "体温" })).toContainText("未测（not_performed）"); await expect(view).toContainText("原测量不等于已评分"); await expect(view.getByLabel("NEWS2完整总分", { exact: true })).toHaveCount(0); noModel(state);
});

test("共享固定规则审核明确选择KDIGO，不默认规则且不混入NEWS2来源", async ({ page }) => {
  const state = await session(page, { ruleOptions: [{ rule_id: "news2_2017", recipe_digest: hashes.recipe, recipe: {}, input_policy: {} }, { rule_id: "kdigo_aki_2012", recipe_digest: "1".repeat(64), recipe: {}, input_policy: {} }] }); await admin(page);
  await page.getByRole("button", { name: "新建固定规则审核草稿", exact: true }).click(); const dialog = page.getByRole("dialog", { name: "新建固定规则审核草稿", exact: true }); await expect(dialog.getByRole("combobox", { name: "固定规则选项", exact: true })).toHaveValue(""); await select(page, "固定规则选项", "kdigo_aki_2012", dialog); await dialog.getByRole("textbox", { name: "规则审核名称", exact: true }).fill("合成成人AKI审核草稿"); await dialog.getByRole("textbox", { name: "规则依据标识", exact: true }).fill("synthetic-kdigo-2012-reference"); await dialog.getByRole("textbox", { name: "规则审核依据", exact: true }).fill(note); await dialog.getByRole("button", { name: "仅保存规则审核草稿", exact: true }).click(); await expect(dialog).toBeHidden();
  expect(state.writes).toHaveLength(1); expect(state.writes[0].body).toMatchObject({ rule_id: "kdigo_aki_2012", expected_recipe_digest: "1".repeat(64) }); await select(page, "治理固定规则筛选", "kdigo_aki_2012"); await expect(page.getByRole("row").filter({ hasText: "合成成人AKI审核草稿" })).toBeVisible(); await expect(page.getByRole("row").filter({ hasText: "合成固定规则审核" })).toHaveCount(0); expect(state.reads.some(row => row.path.endsWith("/risk-rule-profiles") && row.query.rule_id === "kdigo_aki_2012")).toBe(true); noModel(state);
});

test.afterEach(async () => { expect(harness.unhandled).toEqual([]); });
