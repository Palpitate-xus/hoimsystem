const { test, expect } = require("@playwright/test");

const fields = ["adl_score", "pressure_ulcer_risk", "fall_risk", "consciousness", "nutrition_risk"];
const emptyValues = Object.fromEntries(fields.map(key => [key, null]));
const admissions = [{ admission_id: "nursing-a", patient_id: 11, patient_name: "测试甲", admission_no: "SYN-A" }, { admission_id: "nursing-b", patient_id: 12, patient_name: "测试乙", admission_no: "SYN-B" }];
const assessment = (extra = {}) => ({ assessment_id: "502", admission_id: "nursing-a", patient_id: 11, patient_name: "测试甲", ...emptyValues, pressure_ulcer_risk: 0, entry_version: "nullable_v1", assessed_at: null, note: "原评估备注 <img src=x onerror=alert(1)>", nurse_name: "合成护士", create_time: "2026-10-20 02:00:00", status: 1, status_text: "已完成", ...extra });
const critical = (extra = {}) => ({ record_id: "601", admission_id: "nursing-a", patient_id: 11, patient_name: "测试甲", entry_version: "nullable_v1", consciousness: null, gcs_score: null, pulse: 0, spo2: 0, record_time: "2026-10-20T02:00:00Z", time_basis: "recorded_at_only", note: "合成危重备注", ...extra });
const score = (extra = {}) => ({ score_id: 701, admission_id: "nursing-a", patient_id: 11, patient_name: "测试甲", score_type: "gcs", score_type_text: "GCS", scene: "icu", total_score: 3, detail: { eye: 1, verbal: 1, motor: 1 }, calculation_version: "manual_components_v2", score_definition: "gcs_manual_components", component_integrity: { status: "complete", total_matches: true, source_verification: "not_independently_verified" }, scope_note: "仅人工分项汇总，原始观察尚未独立核实", assessed_at: null, time_basis: "assessment_time_unknown", assess_time: "2026-10-20 02:00:00", ...extra });

async function session(page, overrides = {}) {
  const state = { assessments: [], critical: [], plans: [], scores: [], writes: [], previews: [], runs: [], ...overrides };
  const features = [["nursing_risk_assessment", 45, "跌倒与压疮评估助手"], ["nursing_plan", 46, "护理计划草稿"], ["handover_summary", 47, "交接班重点摘要"], ["deterioration_risk", 41, "病情恶化预警"], ["sepsis_risk", 42, "脓毒症风险提示"], ["aki_risk", 43, "急性肾损伤风险提示"]].map(([key, number, name]) => ({ key, number, name, category: "inpatient", scope: "patient", engine: ["deterioration_risk", "sepsis_risk", "aki_risk"].includes(key) ? "prediction" : "llm", enabled: true, inputs: ["本次住院原记录"], deliverables: ["资料缺口与待核实事项"], allowed_roles: ["super_admin", "nurse", "doctor", "director"], source_reference_keys: ["nursing_assessment_id", "nursing_plan_id", "critical_care_record_id", "icu_score_id"] }));
  const sourceReview = (refs = {}) => ({
    selected_sources: refs, limitations: ["未知项保留未知；人工分项汇总不是自动转出依据"],
    assessments: [
      { ...assessment(), source_id: "completed_nursing_assessments:502", explicitly_selected: refs.nursing_assessment_id === "502", missing_fields: fields.filter(key => key !== "pressure_ulcer_risk"), legacy_defaults_possible: false },
      { ...assessment({ assessment_id: "503", adl_score: 100, pressure_ulcer_risk: 0, fall_risk: 0, consciousness: 0, nutrition_risk: 0, entry_version: "legacy_unverified" }), source_id: "completed_nursing_assessments:503", explicitly_selected: false, missing_fields: [], legacy_defaults_possible: true },
    ],
    critical_records: [{ ...critical(), source_id: "critical_care_records:601", explicitly_selected: refs.critical_care_record_id === "601", legacy_defaults_possible: false }],
    plans: [{ source_id: "nursing_plans:801", explicitly_selected: refs.nursing_plan_id === "801", status: 0, nursing_diagnosis: "原护理诊断", goal: "原护理目标", measures: "原护理措施" }],
    scores: [
      { ...score(), source_id: "recorded_icu_scores:701", explicitly_selected: refs.icu_score_id === "701", detail_json: '{"eye":1,"verbal":1,"motor":1}', component_check: { state: "manual_sum_matches", note: "人工分项算术一致，不是疾病概率" } },
      { ...score({ score_id: 702, calculation_version: "legacy_unverified" }), source_id: "recorded_icu_scores:702", detail_json: '{}', component_check: { state: "legacy_unverified", note: "原分项完整性未核实" } },
      { ...score({ score_id: 703, total_score: 15 }), source_id: "recorded_icu_scores:703", detail_json: '{"eye":1}', component_check: { state: "invalid_components", note: "原语言与运动分项缺失" } },
      { ...score({ score_id: 704, total_score: 15 }), source_id: "recorded_icu_scores:704", detail_json: '{"eye":1,"verbal":1,"motor":1}', component_check: { state: "total_mismatch", note: "人工分项3与原总分15不一致" } },
    ],
  });
  const evidence = [{ source_id: "completed_nursing_assessments:502", title: "原护理评估", content: "压疮原标记0，其余四项未评估；未验证标准量表" }];
  const utc = value => value == null ? null : new Date(value).toISOString().replace(".000Z", "Z");
  await page.addInitScript(() => localStorage.setItem("hoim-token", "isolated-nursing-test"));
  await page.route("**/api/**", async route => {
    const url = new URL(route.request().url()), path = url.pathname, method = route.request().method();
    let data = [];
    if (path === "/api/userInfo") data = { username: "合成护理用户", permissions: overrides.role ? [overrides.role] : ["super_admin", "admin"], avatar: "" };
    if (path === "/api/admission/getList") data = admissions;
    if (path === "/api/ai/features") data = features;
    if (path === "/api/ai/patients") data = admissions.map(a => ({ patient_id: a.patient_id, label: a.patient_name }));
    if (path === "/api/ai/encounters") data = [{ encounter_ref: "nursing-a", label: "本次合成住院", kind: "inpatient" }];
    if (path === "/api/ai/context") { const body = route.request().postDataJSON(); state.previews.push(body); data = { context: { nursing_source_review: sourceReview(body.source_refs), missing_data: ["尚缺逐项量表答案"] }, evidence }; }
    if (path === "/api/ai/runs" && method === "POST") { state.runs.push(route.request().postDataJSON()); data = { run_id: "nursing-run", status: "succeeded", feature_name: "护理辅助", patient_id: 11, nursing_findings: sourceReview(state.runs.at(-1).input), evidence, result: { summary: "合成辅助结果，待核实", sections: [], warnings: [], missing_data: ["逐项答案未记录"] } }; }
    const listKeys = { "/api/nursingAssessment/list": "assessments", "/api/criticalCareRecord/list": "critical", "/api/nursingPlan/list": "plans", "/api/icuScore/getList": "scores" };
    if (listKeys[path]) {
      const selected = url.searchParams.get("admission_id");
      const snapshot = state[listKeys[path]].filter(row => !selected || row.admission_id === selected);
      if (state.delayListA && selected === "nursing-a") await new Promise(resolve => { state.releaseListA = resolve; });
      data = snapshot;
    }
    if (method !== "GET" && /^\/api\/(nursingAssessment|criticalCareRecord|nursingPlan|icuScore)\//.test(path)) {
      const body = route.request().postDataJSON(); state.writes.push({ path, body });
      if (state.delayCreate && path.endsWith("/create")) await new Promise(resolve => { state.releaseCreate = resolve; });
      if (path === "/api/nursingAssessment/create") { data = assessment({ ...body, assessment_id: "501", assessed_at: utc(body.assessed_at), status: 0, status_text: "草稿" }); state.assessments.push(data); }
      if (path === "/api/nursingAssessment/update") { data = state.assessments.find(row => row.assessment_id === body.assessment_id); Object.assign(data, body, { assessed_at: utc(body.assessed_at) }); }
      if (path === "/api/nursingAssessment/complete") { data = state.assessments.find(row => row.assessment_id === body.assessment_id); Object.assign(data, { status: 1, status_text: "已完成" }); }
      if (path === "/api/criticalCareRecord/create") { data = critical({ ...body, record_time: utc(body.record_time) ?? "2026-10-20T02:00:00Z", time_basis: body.record_time ? "utc" : "recorded_at_only" }); state.critical.push(data); }
      if (path === "/api/icuScore/create") { data = score({ ...body, assessed_at: utc(body.assessed_at), total_score: Object.values(body.detail).reduce((a, b) => a + b, 0) }); state.scores.push(data); }
    }
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ code: 200, msg: "success", data }) });
  });
  return state;
}
async function select(page, name, value, scope = page) {
  const control = scope.getByRole("combobox", { name, exact: true });
  await control.press("ArrowDown");
  const listbox = page.locator(`#${await control.getAttribute("aria-controls")}`);
  await listbox.getByRole("option", { name: value, exact: true }).click();
}
async function patient(page, label = "测试甲（SYN-A）") { await select(page, "住院患者", label); }

// These are synthetic browser workflows. They do not validate a clinical scale or any model.
test("护理草稿保留五项空值，显式0可完成；评估时点和历史来源分开显示", async ({ page }) => {
  const state = await session(page);
  await page.goto("/#/vitalsign/nursingAssessment"); await patient(page);
  await expect(page.getByRole("spinbutton", { name: "ADL评分", exact: true })).toHaveValue("");
  await expect(page.getByRole("combobox", { name: "压疮风险", exact: true })).toHaveValue("");
  await page.getByRole("button", { name: "保存评估", exact: true }).click();
  await expect.poll(() => state.writes.length).toBe(1);
  expect(state.writes[0].body).toMatchObject({ ...emptyValues, assessed_at: null, patient_id: 11, admission_id: "nursing-a" });
  await expect(page.getByRole("button", { name: "完成评估", exact: true })).toBeDisabled();
  await expect(page.getByRole("button", { name: "AI 护理辅助", exact: true })).toHaveCount(0);
  await page.getByRole("button", { name: "继续填写", exact: true }).click();
  await select(page, "压疮风险", "无（0）");
  await page.getByRole("textbox", { name: "评估时点", exact: true }).fill("2026-10-20T08:30:00.123456+08:00");
  await page.getByRole("button", { name: "保存修改", exact: true }).click();
  await expect.poll(() => state.writes.length).toBe(2);
  expect(state.writes[1]).toMatchObject({ path: "/api/nursingAssessment/update", body: { assessment_id: "501", ...emptyValues, pressure_ulcer_risk: 0, assessed_at: "2026-10-20T08:30:00.123456+08:00" } });
  await expect(page.getByRole("button", { name: "完成评估", exact: true })).toBeEnabled();
  await expect(page.locator(".el-table__body-wrapper")).toContainText("2026-10-20T00:30:00.123Z");
  await page.getByRole("button", { name: "继续填写", exact: true }).click();
  const risk = page.getByRole("combobox", { name: "压疮风险", exact: true });
  // Element Plus exposes the clear action on the select wrapper when a value exists.
  const riskWrapper = risk.locator("xpath=ancestor::div[contains(@class, 'el-select__wrapper')]");
  await riskWrapper.hover(); await riskWrapper.locator(".el-select__clear").click();
  await page.getByRole("textbox", { name: "评估时点", exact: true }).fill("");
  await page.getByRole("button", { name: "保存修改", exact: true }).click(); await expect.poll(() => state.writes.length).toBe(3);
  expect(state.writes[2].body).toMatchObject({ assessment_id: "501", pressure_ulcer_risk: null, assessed_at: null });
  await expect(page.getByRole("button", { name: "完成评估", exact: true })).toBeDisabled();
  await page.getByRole("button", { name: "继续填写", exact: true }).click(); await select(page, "压疮风险", "无（0）");
  await page.getByRole("button", { name: "保存修改", exact: true }).click(); await expect.poll(() => state.writes.length).toBe(4);
  await page.getByRole("button", { name: "完成评估", exact: true }).click();
  await expect(page.getByRole("button", { name: "AI 护理辅助", exact: true })).toBeVisible();
  expect(state.writes.map(x => x.path)).toEqual(["/api/nursingAssessment/create", "/api/nursingAssessment/update", "/api/nursingAssessment/update", "/api/nursingAssessment/update", "/api/nursingAssessment/complete"]);
});

test("切换护理患者清空草稿；迟到的原患者保存与列表不会覆盖新患者", async ({ page }) => {
  const state = await session(page, { delayCreate: true });
  await page.goto("/#/vitalsign/nursingAssessment"); await patient(page);
  await page.getByRole("spinbutton", { name: "ADL评分", exact: true }).fill("50");
  await select(page, "意识", "清醒（0）");
  await page.getByRole("textbox", { name: "评估时点", exact: true }).fill("2026-10-20T08:30:00+08:00");
  await page.getByRole("textbox", { name: "护理评估备注", exact: true }).fill("甲的未完成护理重点");
  await page.getByRole("button", { name: "保存评估", exact: true }).click();
  await expect.poll(() => state.writes.length).toBe(1);
  await patient(page, "测试乙（SYN-B）");
  await expect(page.getByRole("spinbutton", { name: "ADL评分", exact: true })).toHaveValue("");
  await expect(page.getByRole("combobox", { name: "意识", exact: true })).toHaveValue("");
  await expect(page.getByRole("textbox", { name: "评估时点", exact: true })).toHaveValue("");
  await page.getByRole("textbox", { name: "护理评估备注", exact: true }).fill("乙的新草稿"); state.releaseCreate();
  await expect(page.getByRole("button", { name: "保存评估", exact: true })).toBeEnabled();
  await expect(page.getByRole("textbox", { name: "护理评估备注", exact: true })).toHaveValue("乙的新草稿");
  state.delayListA = true; state.assessments.push(assessment());
  await patient(page); await expect.poll(() => typeof state.releaseListA).toBe("function");
  await patient(page, "测试乙（SYN-B）"); state.releaseListA();
  await expect(page.locator(".el-table__body-wrapper")).not.toContainText("测试甲");
});

test("危重表单不预设清醒或GCS，保留真实零值并拒绝无时区或非法日期", async ({ page }) => {
  const state = await session(page, { critical: [critical({ entry_version: "legacy_unverified", gcs_score: 0, consciousness: 0, time_basis: "unspecified", record_time: "2026-10-20 02:00:00" })] });
  await page.goto("/#/vitalsign/criticalCareRecord");
  const table = page.locator(".el-table__body-wrapper"); await expect(table).toContainText("历史原值未核实"); await expect(table).toContainText("原时钟未声明时区"); await expect(table).toContainText("原值 0（未核实） / 0");
  await patient(page);
  await expect(page.getByRole("spinbutton", { name: "GCS总分", exact: true })).toHaveValue("");
  await expect(page.getByRole("combobox", { name: "意识", exact: true })).toHaveValue("");
  await page.getByRole("button", { name: "记录危重护理", exact: true }).click(); await expect.poll(() => state.writes.length).toBe(1);
  expect(state.writes[0].body).toMatchObject({ consciousness: null, gcs_score: null, pulse: null, spo2: null, record_time: null });
  await select(page, "意识", "清醒（0）"); await page.getByRole("spinbutton", { name: "脉搏", exact: true }).fill("0"); await page.getByRole("spinbutton", { name: "SpO₂", exact: true }).fill("0");
  for (const invalid of ["2026-10-20T08:30:00", "2026-02-30T08:30:00+08:00", "2026-10-20T24:00:00Z", "2026-10-20T08:30:00+08:60", "0001-01-01T00:00:00+23:59", "9999-12-31T23:59:59-23:59"]) { await page.getByRole("textbox", { name: "观测时点", exact: true }).fill(invalid); await page.getByRole("button", { name: "记录危重护理", exact: true }).click(); }
  expect(state.writes).toHaveLength(1);
  await page.getByRole("textbox", { name: "观测时点", exact: true }).fill("2026-10-20T08:30:00+08:00"); await page.getByRole("button", { name: "记录危重护理", exact: true }).click(); await expect.poll(() => state.writes.length).toBe(2);
  expect(state.writes[1].body).toMatchObject({ consciousness: 0, gcs_score: null, pulse: 0, spo2: 0, record_time: "2026-10-20T08:30:00+08:00" });
  await expect(table).toContainText("已声明观测时点（UTC）"); await expect(table).toContainText("2026-10-20T00:30:00Z");
});

test("五类人工评分须显式全部填写，0分不是默认；切换患者清空分项与时点", async ({ page }) => {
  const state = await session(page, { scores: [score({ calculation_version: "legacy_unverified", scene: "", interpretation: "旧自动解释原文", assessed_at: null })] });
  await page.goto("/#/inpatient/opsExtension"); await page.getByRole("tab", { name: "ICU/PACU 评分", exact: true }).click();
  await expect(page.locator(".el-table__body-wrapper:visible")).toContainText("原记录说明（未核实）：旧自动解释原文");
  await expect(page.locator(".el-table__body-wrapper:visible")).toContainText("未记录/未知");
  await page.getByRole("button", { name: "新建评分", exact: true }).click();
  const dialog = page.getByRole("dialog", { name: "新建专科评分", exact: true });
  await dialog.getByRole("spinbutton", { name: "评分患者ID", exact: true }).fill("11");
  await dialog.getByRole("button", { name: "提交评分", exact: true }).click(); expect(state.writes).toEqual([]);
  for (const [type, labels] of [["GCS", ["睁眼(1-4)", "语言(1-5)", "运动(1-6)"]], ["SOFA（原1996版）", ["呼吸", "凝血", "肝脏", "心血管", "神经", "肾脏"]], ["Aldrete（原1970肤色版）", ["活动", "呼吸", "循环", "意识", "肤色"]], ["Steward（原1975版）", ["清醒程度", "气道通畅", "肢体活动"]]]) {
    await select(page, "评分类型", type, dialog);
    for (const label of labels) await expect(dialog.getByRole("combobox", { name: label, exact: true })).toHaveValue("");
    await dialog.getByRole("button", { name: "提交评分", exact: true }).click(); expect(state.writes).toEqual([]);
  }
  await expect(dialog).not.toContainText("≥9"); await expect(dialog).not.toContainText("≥4");
  await select(page, "评分类型", "APACHE II", dialog);
  await dialog.getByRole("spinbutton", { name: "APS合计(0-60)", exact: true }).fill("0");
  const age = dialog.getByRole("combobox", { name: "年龄评分(0/2/3/5/6)", exact: true }); await age.press("ArrowDown");
  const ageOptions = page.locator(`#${await age.getAttribute("aria-controls")}`);
  await expect(ageOptions.getByRole("option", { name: "1", exact: true })).toHaveCount(0); await expect(ageOptions.getByRole("option", { name: "4", exact: true })).toHaveCount(0); await ageOptions.getByRole("option", { name: "0", exact: true }).click();
  await select(page, "慢性健康(0/2/5)", "0", dialog);
  await dialog.getByRole("textbox", { name: "评分评估时点", exact: true }).fill("2026-10-20T08:30:00+08:00");
  await dialog.getByRole("spinbutton", { name: "评分患者ID", exact: true }).fill("12"); await dialog.getByRole("textbox", { name: "评分住院ID", exact: true }).focus();
  await expect(dialog.getByRole("spinbutton", { name: "APS合计(0-60)", exact: true })).toHaveValue(""); await expect(dialog.getByRole("textbox", { name: "评分评估时点", exact: true })).toHaveValue("");
  await dialog.getByRole("spinbutton", { name: "APS合计(0-60)", exact: true }).fill("0"); await select(page, "年龄评分(0/2/3/5/6)", "0", dialog); await select(page, "慢性健康(0/2/5)", "0", dialog);
  await dialog.getByRole("button", { name: "提交评分", exact: true }).click(); await expect.poll(() => state.writes.length).toBe(1);
  expect(state.writes[0]).toEqual({ path: "/api/icuScore/create", body: { patient_id: 12, admission_id: null, score_type: "apache2", scene: "icu", detail: { aps_total: 0, age_points: 0, chronic_health_points: 0 }, assessed_at: null } });
});

for (const entry of [
  { route: "vitalsign/nursingAssessment", label: "AI 护理辅助", title: "AI 原护理评估辅助", ref: "nursing_assessment_id", id: "502", feature: "nursing_risk_assessment", fixtures: { assessments: [assessment({ assessment_id: "501", status: 0, status_text: "草稿" }), assessment()] } },
  { route: "vitalsign/criticalCareRecord", label: "AI 危重护理辅助", title: "AI 原危重护理记录辅助", ref: "critical_care_record_id", id: "601", feature: "handover_summary", fixtures: { critical: [critical()] } },
  { route: "vitalsign/nursingPlan", label: "AI 护理计划辅助", title: "AI 原护理计划辅助", ref: "nursing_plan_id", id: "801", feature: "nursing_plan", fixtures: { plans: [{ plan_id: "801", admission_id: "nursing-a", patient_id: 11, patient_name: "测试甲", nursing_diagnosis: "原护理诊断", goal: "原目标", measures: "原措施", status: 0, status_text: "进行中" }] } },
  { route: "inpatient/opsExtension", label: "AI 评分资料辅助", title: "AI 原人工评分资料辅助", ref: "icu_score_id", id: "701", feature: "handover_summary", fixtures: { scores: [score(), score({ score_id: 702, admission_id: null })] } },
]) test(`${entry.label}固定原患者、住院和字符串来源标识，预览与生成不写护理记录`, async ({ page }) => {
  const state = await session(page, entry.fixtures); await page.goto(`/#/${entry.route}`);
  if (entry.route.includes("opsExtension")) await page.getByRole("tab", { name: "ICU/PACU 评分", exact: true }).click();
  await expect(page.getByRole("button", { name: entry.label, exact: true })).toHaveCount(1);
  await page.getByRole("button", { name: entry.label, exact: true }).click();
  const drawer = page.getByRole("dialog", { name: entry.title, exact: true });
  await expect(drawer.getByRole("combobox", { name: "患者", exact: true })).toBeDisabled(); await expect(drawer.getByRole("combobox", { name: "本次就诊", exact: true })).toBeDisabled();
  await drawer.getByText("联调与预览选项", { exact: true }).click(); await drawer.getByPlaceholder("可选：专用适配器的结构化输入 JSON，由服务契约规定", { exact: true }).fill(JSON.stringify({ [entry.ref]: "999" }));
  await drawer.getByRole("button", { name: "查看本次资料", exact: true }).click();
  const preview = page.getByRole("dialog", { name: "本次提供给 AI 的患者资料", exact: true });
  await expect(preview.locator(".nursing-findings")).toBeVisible(); await preview.locator(".nursing-findings .el-collapse-item__header").filter({ hasText: "已完成护理评估" }).first().click();
  await expect(preview.locator(".nursing-findings")).toContainText("未评估"); await expect(preview.locator(".nursing-findings")).toContainText("无（原标记0）"); await expect(preview.locator("img")).toHaveCount(0);
  if (entry.ref === "icu_score_id") {
    const headers = preview.locator(".nursing-findings .el-collapse-item__header");
    await headers.filter({ hasText: "已完成护理评估" }).nth(1).click();
    await expect(preview.locator(".nursing-findings")).toContainText("原默认值是否经过显式评估未核实");
    await expect(headers.filter({ hasText: "GCS（历史定义未核实）原评分" })).toHaveCount(1);
    for (let i = 0; i < 4; i++) await headers.filter({ hasText: /GCS.*原评分/ }).nth(i).click();
    for (const text of ["人工分项算术一致，临床正确性未核实", "历史分项完整性未核实", "原分项不完整或不合法", "分项与原总分矛盾", "人工分项3与原总分15不一致"]) await expect(preview.locator(".nursing-findings")).toContainText(text);
  }
  await preview.locator("button.el-dialog__headerbtn").click(); await drawer.getByRole("button", { name: "生成辅助建议", exact: true }).click();
  await expect.poll(() => state.runs.length).toBe(1);
  expect(state.previews[0]).toMatchObject({ patient_id: 11, encounter_ref: "nursing-a", source_refs: { [entry.ref]: entry.id } });
  expect(state.runs[0]).toMatchObject({ feature_key: entry.feature, patient_id: 11, encounter_ref: "nursing-a", input: { [entry.ref]: entry.id } });
  await expect(drawer.getByLabel("AI任务结果", { exact: true }).locator(".nursing-findings")).toBeVisible(); expect(state.writes).toEqual([]);
});

test("护士切换危重记录和护理计划患者时不沿用上一位患者输入", async ({ page }) => {
  const state = await session(page, { role: "nurse", critical: [critical()], plans: [{ plan_id: "801", admission_id: "nursing-a", patient_id: 11, patient_name: "测试甲", nursing_diagnosis: "原护理诊断", goal: "原目标", measures: "原措施", status: 0, status_text: "进行中" }] });
  await page.goto("/#/vitalsign/criticalCareRecord");
  await expect(page.getByRole("button", { name: "AI 危重护理辅助", exact: true })).toBeVisible();
  await patient(page); await select(page, "意识", "清醒（0）");
  for (const [name, value] of [["GCS总分", "3"], ["脉搏", "40"], ["SpO₂", "50"]]) await page.getByRole("spinbutton", { name, exact: true }).fill(value);
  for (const [name, value] of [["氧疗", "原氧疗"], ["血压", "120/80"], ["尿量", "原尿量"], ["观测时点", "2026-10-20T08:30:00+08:00"], ["危重护理备注", "原患者备注"]]) await page.getByRole("textbox", { name, exact: true }).fill(value);
  await patient(page, "测试乙（SYN-B）");
  await expect(page.getByRole("combobox", { name: "意识", exact: true })).toHaveValue("");
  for (const name of ["GCS总分", "脉搏", "SpO₂"]) await expect(page.getByRole("spinbutton", { name, exact: true })).toHaveValue("");
  for (const name of ["氧疗", "血压", "尿量", "观测时点", "危重护理备注"]) await expect(page.getByRole("textbox", { name, exact: true })).toHaveValue("");
  await page.goto("/#/vitalsign/nursingPlan"); await expect(page.getByRole("button", { name: "AI 护理计划辅助", exact: true })).toBeVisible();
  await patient(page);
  for (const placeholder of ["如活动耐力下降", "可衡量的护理目标", "具体护理措施和频次"]) await page.getByPlaceholder(placeholder, { exact: true }).fill("原患者的输入");
  await patient(page, "测试乙（SYN-B）");
  for (const placeholder of ["如活动耐力下降", "可衡量的护理目标", "具体护理措施和频次"]) await expect(page.getByPlaceholder(placeholder, { exact: true })).toHaveValue("");
  await page.getByRole("button", { name: "保存护理计划", exact: true }).click(); expect(state.writes).toEqual([]);
});
