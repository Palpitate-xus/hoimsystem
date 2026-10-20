const { test, expect } = require("@playwright/test");
const { execFileSync } = require("node:child_process");
const path = require("node:path");
const { startSofaHarness } = require("./fixtures/sofa-source-harness.cjs");
const native = require("./fixtures/sofa-native-fixtures.cjs");
const qsofa = require("./fixtures/qsofa-fixtures.cjs");

// The parent and KeepAlive are actual Vue components, and both SOFA packets are
// immutable synthetic ORM/router DTOs. Explanations and arithmetic come from the
// actual specialist; these HTTP mocks never contact hospital services.
const clone = value => JSON.parse(JSON.stringify(value));
const daily = native["seven-daily"], change = native["change-observed"];
const patient = daily.scope.patient_id, admission = daily.scope.admission_id;
const otherAdmission = native["daily-active"].scope.admission_id;
const privateBasis = daily.scope.snapshot.attestation.age_basis_note;
const fixedResults = JSON.parse(execFileSync(
  process.env.HOIM_TEST_PYTHON || "/home/xusheng/miniconda3/bin/python",
  ["-c", String.raw`
import json,os,sys
from pathlib import Path
def guard(event,args):
 if event=='open' and isinstance(args[0],(str,bytes)) and Path(os.fsdecode(args[0])).name=='.env':raise AssertionError('no hospital dotenv')
 if event=='socket.connect':raise AssertionError('no hospital DB/network')
sys.addaudithook(guard)
from app.ai.sofa_model import generation_result_for_analysis,generation_result_for_change_analysis
values=json.load(sys.stdin)
out={key:(generation_result_for_change_analysis(value) if key=='change' else generation_result_for_analysis(value)) for key,value in values.items()}
assert not any(name in sys.modules for name in ('app.config','app.database','app.models','sqlalchemy'))
print(json.dumps(out,ensure_ascii=False))
`],
  { cwd: path.resolve(__dirname, "../../fastapi_be"), input: JSON.stringify({ daily: daily.analysis, change: change.analysis }), encoding: "utf8", maxBuffer: 1048576 },
));

let harness;
test.describe.configure({ mode: "default" });
test.beforeAll(async () => { harness = await startSofaHarness(); });
test.afterAll(async () => { await harness?.close(); });

function sourceBinding(item, kind) {
  const source = item.source, rule = kind === "daily" ? source : source.current;
  return {
    schema_version: "sofa_context_binding_v1", kind,
    patient_id: item.scope.patient_id, admission_id: item.scope.admission_id,
    assessment_id: kind === "daily" ? source.assessment_id : source.change_assessment_id,
    source_id: source.source_id, content_hash: source.content_hash,
    governance_hash: source.assessment_governance_hash, projection_hash: item.scope.projection_hash,
    rule_id: rule.rule_id, recipe_digest: rule.recipe_digest, policy_digest: rule.policy_digest,
  };
}
function evidenceFor(item, kind) {
  const source = item.source, rule = kind === "daily" ? source : source.current;
  const indexes = [[source.source_id, "clinical_record"], [rule.rule_profile_source_id, "rule"]];
  if (kind === "change") {
    indexes.push([source.current.source_id, "clinical_record"], [source.infection.source_id, "clinical_record"]);
    if (source.baseline.mode === "observed") indexes.push([source.baseline.source.source_id, "clinical_record"]);
  }
  return indexes.map(([source_id, type]) => ({ source_id, kind: type, title: "独立真实合成冻结依据", content: JSON.stringify({ sofa_binding: sourceBinding(item, kind) }) }));
}
function sofaRun(kind) {
  const item = kind === "daily" ? daily : change;
  const findings = kind === "daily"
    ? { sofa_findings: { sofa_source: clone(item.source), sofa_assessment: clone(item.scope) } }
    : { sofa_change_findings: { sofa_change_source: clone(item.source), sofa_change_assessment: clone(item.scope) } };
  return {
    run_id: `synthetic-independent-sofa-${kind}-history`, feature_key: "sepsis_risk", feature_name: "完整SOFA原量核对",
    patient_id: patient, encounter_ref: admission, status: "succeeded", ...findings,
    result: { ...clone(fixedResults[kind]), [kind === "daily" ? "sofa_analysis" : "sofa_change_analysis"]: clone(item.analysis) },
    evidence: evidenceFor(item, kind),
  };
}
function windowFixture(row) {
  const snapshot = {
    ...clone(row.snapshot.window_binding), patient_id: 11, admission_id: qsofa.admission, created_by: 1,
    points: [clone(row.snapshot.point)], urine_intervals: [], lab_observations: [],
    quality: { measurement_gaps: [], missing_by_point: [], same_time_groups: [], laboratory: { member_count: 0, eligible_count: 0, excluded_sources: [], same_time_groups: [] }, urine: { overlap_groups: [], excluded_intervals: [], uncovered_intervals: [] } },
    limitations: ["独立合成原观测窗；不代表连续监护完整"],
  };
  return { ...snapshot, status: "active", revision: 1, snapshot, freshness: { state: "current" }, can_revoke: true };
}
async function mockApi(page, configuration = {}) {
  const state = {
    mode: "sofa1", kind: "daily", reads: [], writes: [], contexts: [], errors: [], releases: {}, completed: [],
    hold: null, detailReads: 0, listReads: 0, ...configuration,
  };
  state.qsofa = qsofa.makeAssessment(); state.window = windowFixture(state.qsofa);
  page.on("pageerror", error => state.errors.push(error.message));
  await page.addInitScript(() => localStorage.setItem("hoim-token", "synthetic-independent-sofa-parent"));
  await page.route("**/api/**", async route => {
    const request = route.request(), url = new URL(request.url()), pathname = url.pathname, method = request.method();
    const query = Object.fromEntries(url.searchParams), legacy = state.mode !== "sofa1";
    if (method === "GET") state.reads.push({ pathname, query });
    else state.writes.push({ pathname, body: request.postData() ? request.postDataJSON() : null });
    let data = [], phase = null;
    if (pathname === "/api/userInfo") data = { username: "独立合成父生命周期复核", permissions: ["doctor"], avatar: "" };
    if (["/api/ai/features", "/api/ai/admin/features"].includes(pathname)) data = [{
      key: "sepsis_risk", number: 42, name: "完整SOFA原量核对", category: "inpatient", scope: "patient", engine: "prediction", input_mode: state.mode,
      enabled: true, inputs: ["明确完整原评估与当前医生核实"], deliverables: ["固定原量、部分范围与协议核对"],
      source_reference_keys: legacy ? (state.mode === "qsofa" ? ["observation_window_id", "qsofa_assessment_id"] : ["observation_window_id"]) : ["sofa_assessment_id", "sofa_change_assessment_id"],
      allowed_roles: ["doctor", "super_admin"], default_roles: ["doctor"], validation_status: "unreviewed", prompt_version: 1,
    }];
    if (pathname === "/api/ai/patients") data = [{ patient_id: legacy ? 11 : patient, label: "独立合成原患者" }, { patient_id: 22, label: "另一合成患者" }];
    if (pathname === "/api/ai/encounters") data = [{ encounter_ref: legacy ? qsofa.admission : admission, kind: "inpatient", label: "住院 · 独立合成原住院" }, { encounter_ref: otherAdmission, kind: "inpatient", label: "住院 · 另一原住院" }];
    if (pathname === "/api/ai/sofa-assessments") data = { items: query.patient_id === String(patient) && query.admission_id === admission ? [clone(daily.scope)] : [], total: query.patient_id === String(patient) && query.admission_id === admission ? 1 : 0, page: 1, page_size: 50 };
    if (pathname === `/api/ai/sofa-assessments/${daily.scope.assessment_id}`) data = clone(daily.scope);
    if (pathname === "/api/ai/sofa-change-assessments") data = { items: [clone(change.scope)], total: 1, page: 1, page_size: 50 };
    if (pathname === `/api/ai/sofa-change-assessments/${change.scope.change_assessment_id}`) data = clone(change.scope);
    if (pathname === "/api/ai/observation-windows") { const row = clone(state.window); delete row.snapshot; row.freshness = { state: "not_checked" }; data = legacy ? [row] : []; }
    if (pathname === `/api/ai/observation-windows/${qsofa.windowId}`) data = clone(state.window);
    if (pathname === "/api/ai/qsofa-assessments") data = { items: [clone(state.qsofa)], total: 1, page: 1, page_size: 50 };
    if (pathname === `/api/ai/qsofa-assessments/${qsofa.assessmentId}`) data = clone(state.qsofa);
    if (pathname === "/api/ai/runs" && method === "GET") {
      state.listReads++; phase = "history-list";
      const full = sofaRun(state.kind);
      data = [{ run_id: full.run_id, feature_key: full.feature_key, feature_name: full.feature_name, patient_id: full.patient_id, encounter_ref: full.encounter_ref, status: "succeeded" }];
    }
    if (pathname.startsWith("/api/ai/runs/") && method === "GET") {
      state.detailReads++; phase = "history-detail"; data = sofaRun(state.kind); state.mutateRun?.(data);
    }
    if (pathname === "/api/ai/context") {
      state.contexts.push(request.postDataJSON());
      if (legacy) {
        const compact = qsofa.compactAssessment(state.qsofa); delete compact.specialist_source;
        data = { context: state.mode === "qsofa" ? { qsofa_source: clone(state.qsofa.specialist_source), qsofa_assessment: compact } : { observation_window: clone(state.window.snapshot) }, evidence: [] };
      }
    }
    if (phase && state.hold === phase) { const held = phase; state.hold = null; await new Promise(resolve => { state.releases[held] = resolve; }); await route.fulfill({ json: { code: 200, data } }); state.completed.push(held); }
    else await route.fulfill({ json: { code: 200, data } });
  });
  return state;
}
async function openHarness(page, options = {}) {
  const state = await mockApi(page, options);
  await page.context().route("**/*", route => new URL(route.request().url()).origin === harness.origin ? route.continue() : route.abort("blockedbyclient"));
  await page.goto(harness.origin);
  await page.waitForFunction(() => !!window.__sofaProbe);
  await page.evaluate(({ patientId, admissionId }) => Object.assign(window.__sofaProbe.scope, { patientId, admissionId, initialInput: {}, mode: "assistant" }), { patientId: options.mode && options.mode !== "sofa1" ? 11 : patient, admissionId: options.mode && options.mode !== "sofa1" ? qsofa.admission : admission });
  await expect(page.locator(".ai-assistant")).toBeVisible();
  await expect.poll(() => page.evaluate(() => {
    const instance = window.__sofaProbe.assistant?.$;
    if (!instance?.setupState.selected) return null;
    window.__sofaEntryReview = instance;
    return { input: instance.props.initialInput, patient: instance.setupState.patientId, admission: instance.setupState.encounterRef };
  })).toEqual({ input: {}, patient: options.mode && options.mode !== "sofa1" ? 11 : patient, admission: options.mode && options.mode !== "sofa1" ? qsofa.admission : admission });
  return state;
}
async function recent(page) { await page.getByRole("button", { name: "最近任务", exact: true }).click(); }
const viewHistory = page => page.getByRole("button", { name: "查看", exact: true }).click();
async function openHistory(page) { await recent(page); await viewHistory(page); }
async function showOriginal(page, kind = "daily") {
  await page.getByRole("button", { name: kind === "daily" ? "核对日评估原依据" : "核对变化评估原依据", exact: true }).click();
  await expect(page.getByRole("dialog", { name: "核查引用依据", exact: true })).toContainText(kind === "daily" ? privateBasis : change.scope.snapshot.attestation.note);
}
async function localState(page) {
  return page.evaluate(() => {
    const instance = window.__sofaEntryReview, state = instance.setupState;
    return { run: state.run, context: state.contextData, evidence: state.evidence, evidenceDialog: state.evidenceDialog, contextDialog: state.contextDialog, deactivated: instance.isDeactivated };
  });
}
async function invalidate(page, kind) {
  await page.evaluate(({ kind, nextAdmission, nextPatient }) => {
    const probe = window.__sofaProbe;
    if (kind === "role") probe.store.commit("user/permissions", ["admin"]);
    else if (kind === "session") probe.store.commit("user/token", "changed-independent-synthetic-session");
    else if (kind === "deactivate") probe.scope.mounted = false;
    else if (kind === "patient") probe.scope.patientId = nextPatient;
    else if (kind === "admission") probe.scope.admissionId = nextAdmission;
    else if (kind === "mode") window.__sofaEntryReview.setupState.features.find(feature => feature.key === "sepsis_risk").input_mode = "qsofa";
    else throw new Error("Unknown transition");
  }, { kind, nextAdmission: otherAdmission, nextPatient: patient + 1 });
}
async function assertCleared(page, deactivated = false) {
  await expect.poll(() => localState(page)).toEqual({ run: null, context: null, evidence: null, evidenceDialog: false, contextDialog: false, deactivated });
  await expect(page.getByLabel("AI任务结果", { exact: true })).toHaveCount(0);
  await expect(page.getByLabel("SOFA完整原资料与数值协议核对", { exact: true })).toHaveCount(0);
  await expect(page.getByRole("dialog", { name: "核查引用依据", exact: true })).toBeHidden();
  await expect(page.locator("pre").filter({ hasText: privateBasis })).toHaveCount(0);
}
async function release(state, phase) {
  state.releases[phase]();
  await expect.poll(() => state.completed.includes(phase)).toBe(true);
}

test("空initialInput的42历史可核对真实日评估及private原件，无须先选SOFA引用", async ({ page }) => {
  const state = await openHarness(page);
  await expect(page.getByRole("button", { name: "生成辅助建议", exact: true })).toBeDisabled();
  await openHistory(page);
  const result = page.getByLabel("AI任务结果", { exact: true });
  await expect(result.getByLabel("SOFA六轴上下界与协议完整性", { exact: true }).locator("tbody tr")).toHaveCount(daily.analysis.domains.length);
  await expect(result.getByLabel("SOFA总分上下界", { exact: true })).toContainText(`${daily.analysis.lower_bound} 至 ${daily.analysis.upper_bound}`);
  await showOriginal(page);
  expect(await page.evaluate(() => window.__sofaEntryReview.setupState.sofaSelection)).toBeNull();
  expect(state.writes).toEqual([]); expect(state.errors).toEqual([]);
});

test("空引用的42历史独立展示真实observed两期变化，负下界和原基线未并成日评估", async ({ page }) => {
  const state = await openHarness(page, { kind: "change" });
  await openHistory(page);
  const result = page.getByLabel("AI任务结果", { exact: true });
  await expect(result.getByLabel("SOFA变化上下界", { exact: true })).toContainText(`${change.analysis.delta_lower_bound} 至 ${change.analysis.delta_upper_bound}`);
  await expect(result.getByLabel("当前日SOFA六轴结果", { exact: true })).toBeVisible();
  await expect(result.getByLabel("独立真实基线日SOFA六轴结果", { exact: true })).toBeVisible();
  await showOriginal(page, "change");
  expect(state.writes).toEqual([]); expect(state.errors).toEqual([]);
});

for (const mixed of ["both-findings", "wrong-analysis"]) {
  test(`42历史拒绝daily/change混合回执：${mixed}`, async ({ page }) => {
    const state = await openHarness(page, { mutateRun: value => {
      if (mixed === "both-findings") value.sofa_change_findings = sofaRun("change").sofa_change_findings;
      else value.result.sofa_change_analysis = clone(change.analysis);
    } });
    await openHistory(page);
    await expect(page.getByRole("alert").filter({ hasText: "SOFA任务与当前原住院" })).toBeVisible();
    await assertCleared(page);
    expect(state.detailReads).toBe(1); expect(state.writes).toEqual([]); expect(state.errors).toEqual([]);
  });
}

for (const transition of ["role", "session", "deactivate", "patient", "admission", "mode"]) {
  test(`已读42历史及private依据在${transition}变化时清空，迟到detail不能恢复`, async ({ page }) => {
    const state = await openHarness(page);
    await openHistory(page);
    await expect(page.getByRole("button", { name: "核对日评估原依据", exact: true })).toBeVisible();
    state.hold = "history-detail";
    await viewHistory(page);
    await expect.poll(() => !!state.releases["history-detail"]).toBe(true);
    await showOriginal(page);
    await invalidate(page, transition);
    await assertCleared(page, transition === "deactivate");
    await release(state, "history-detail");
    await assertCleared(page, transition === "deactivate");
    if (transition === "deactivate") {
      await page.evaluate(() => { window.__sofaProbe.scope.mounted = true; });
      await expect(page.locator(".ai-assistant")).toBeVisible();
      await assertCleared(page);
    }
    expect(state.detailReads).toBe(2); expect(state.writes).toEqual([]); expect(state.errors).toEqual([]);
  });
}

for (const transition of ["role", "session", "deactivate"]) {
  test(`无ref且首次history尚未返回时${transition}，迟到原任务目录不能重新出现`, async ({ page }) => {
    const state = await openHarness(page, { hold: "history-list" });
    await recent(page);
    await expect.poll(() => !!state.releases["history-list"]).toBe(true);
    await invalidate(page, transition);
    await release(state, "history-list");
    await assertCleared(page, transition === "deactivate");
    expect(await page.evaluate(() => window.__sofaEntryReview.setupState.history)).toEqual([]);
    if (transition === "deactivate") {
      await page.evaluate(() => { window.__sofaProbe.scope.mounted = true; });
      await expect(page.locator(".ai-assistant")).toBeVisible();
      await expect(page.getByRole("button", { name: "查看", exact: true })).toHaveCount(0);
    }
    expect(state.detailReads).toBe(0); expect(state.writes).toEqual([]); expect(state.errors).toEqual([]);
  });
}

async function choose(page, label, option) {
  const input = label === "待计算qSOFA评估来源" ? page.getByRole("combobox", { name: label, exact: true }) : page.locator(".el-form-item").filter({ has: page.locator("label").filter({ hasText: new RegExp(`^${label}$`) }) }).getByRole("combobox");
  await expect(input).toBeEnabled(); await input.press("ArrowDown");
  await page.locator(`#${await input.getAttribute("aria-controls")}`).getByRole("option", { name: option, exact: true }).click();
}
for (const mode of ["observation_window", "qsofa"]) {
  test(`42父入口原${mode}仍使用原引用，不误入SOFA或要求完整日评估`, async ({ page }) => {
    const state = await openHarness(page, { mode });
    await choose(page, "原住院观测窗", `${state.window.start_at} 至 ${state.window.end_at} · 可用截止 ${state.window.as_of} · ${qsofa.windowId.slice(0, 8)}`);
    if (mode === "qsofa") await choose(page, "待计算qSOFA评估来源", `${qsofa.review} · ${qsofa.assessmentId} · 活动来源`);
    await expect(page.getByRole("button", { name: "生成辅助建议", exact: true })).toBeEnabled();
    await page.getByRole("button", { name: "查看本次资料", exact: true }).click();
    await expect(page.getByRole("dialog", { name: "本次提供给 AI 的患者资料", exact: true })).toBeVisible();
    expect(state.contexts).toEqual([{ feature_key: "sepsis_risk", patient_id: 11, encounter_ref: qsofa.admission, source_refs: mode === "qsofa" ? { observation_window_id: qsofa.windowId, qsofa_assessment_id: qsofa.assessmentId } : { observation_window_id: qsofa.windowId } }]);
    expect(state.reads.some(row => row.pathname.startsWith("/api/ai/sofa-assessments") || row.pathname.startsWith("/api/ai/sofa-change-assessments"))).toBe(false);
    await expect(page.getByLabel("SOFA独立24小时原资料评估", { exact: true })).toHaveCount(0);
    expect(state.writes.every(row => row.pathname === "/api/ai/context")).toBe(true); expect(state.errors).toEqual([]);
  });
}
