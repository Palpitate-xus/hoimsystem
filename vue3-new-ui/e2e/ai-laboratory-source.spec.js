const { test, expect } = require("@playwright/test");
const { startLaboratoryHarness } = require("./fixtures/laboratory-source-harness.cjs");

test.describe.configure({ mode: "default" });
let harness;
const stamp = "2020-01-02T03:04:05.123456Z", legacyClock = "2020-01-01T04:05:06.120000";
const scopeA = { patient_id: 11, admission_id: "obs-admission-a" }, scopeB = { patient_id: 22, admission_id: "obs-admission-b" };
const sourceId = "11111111-1111-4111-8111-111111111111", mappingId = "22222222-2222-4222-8222-222222222222", observationId = "33333333-3333-4333-8333-333333333333";
const note = "已核对合成原记录、设备来源与实际住院材料，并记录本次人工核实的完整依据";
const signature = { code_system: "local", code: "SYN-CREAT", unit: "synthetic-unit", method: "synthetic_method", specimen_type: "synthetic_specimen", value_kind: "numeric" };
const mapping = overrides => ({ mapping_id: mappingId, schema_version: "lab_mapping_v1", source_namespace: "synthetic-lis", signature: { ...signature }, analyte_key: "creatinine", analyte_label: "合成肌酐项目身份", evidence_reference: "synthetic-dictionary-reference", rationale: note, content_hash: "b".repeat(64), governance_hash: "c".repeat(64), source_id: `lab_mapping:${mappingId}:${"b".repeat(12)}`, created_at: stamp, created_by: 7, status: "published", revision: 2, published_at: stamp, review_note: note, ...overrides });
const original = (scope = scopeA, overrides = {}) => ({ observation: { observation_id: observationId, lab_result_id: "synthetic-reviewed-report", ...signature, display: "合成检验项目", value_num: "0.00000000", value_text: null, collected_at: legacyClock, time_basis: "unknown", ...overrides }, report: { lab_result_id: "synthetic-reviewed-report", lab_order_id: "synthetic-original-order", report_time: legacyClock, audit_time: legacyClock, audit_status: 1, time_basis: "unknown" }, order: { lab_order_id: "synthetic-original-order", patient_id: scope.patient_id, doctor_id: 9, status: 2, create_time: legacyClock, time_basis: "unknown" } });
function source(scope = scopeA, overrides = {}) {
  const metadata = { ...scope, lab_source_id: sourceId, source_id: `inpatient_lab:${sourceId}:${"a".repeat(12)}`, observation_id: observationId, mapping_id: mappingId, collected_at_utc: "2020-01-01T04:05:06.123456Z", registered_at: stamp, available_at: stamp, created_by: 7, schema_version: "inpatient_lab_source_v1", raw_original_hash: "d".repeat(64), mapping_content_hash: "b".repeat(64), content_hash: "a".repeat(64), status: "active", revision: 1, can_revoke: true, ...overrides };
  return { ...metadata, snapshot: { ...metadata, original: original(scope), mapping: mapping(), source_namespace: "synthetic-lis", collection_time_basis_note: note, admission_binding_note: note, source_namespace_basis_note: note, availability_basis: "server_registered_after_verification" }, mapping_current: { status: "published", revision: 2 }, eligible: true, exclusion_reasons: [], freshness: { state: "current", message: "合成原资料本次核对一致" } };
}
const candidate = (scope = scopeA) => ({ observation_id: observationId, raw_original_hash: "d".repeat(64), original: original(scope), matching_mappings: [mapping()], registration: { active_lab_source_id: null, status: "unregistered" }, scope_note: "同患者候选，尚未确认属于所选住院" });

test.beforeAll(async () => { harness = await startLaboratoryHarness(); });
test.afterAll(async () => { await harness?.close(); });
async function session(page, options = {}) {
  const state = { candidates: options.candidates ?? [candidate()], sources: options.sources ?? [], mappings: options.mappings ?? [mapping()], reads: [], writes: [], inference: [], forbidden: [], delayed: null, release: null, wrongSource: false, mutateReceipt: null };
  await page.context().route("**/*", route => new URL(route.request().url()).origin === harness.origin ? route.continue() : route.abort("blockedbyclient"));
  await page.route("**/api/**", async route => {
    const request = route.request(), url = new URL(request.url()), path = url.pathname, method = request.method(), query = Object.fromEntries(url.searchParams);
    const respond = data => route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ code: 200, msg: "synthetic", data }) });
    if (/\/ai\/(runs|context|admin\/features)(\/|$)/.test(path)) { state.inference.push({ path, method }); return respond({}); }
    const isMapping = path.startsWith("/api/ai/admin/lab-mappings"), isSource = path.startsWith("/api/inpatient-laboratory/") || path.startsWith("/api/ai/admin/lab-sources");
    if (!isMapping && !isSource) { state.forbidden.push({ path, method }); return route.fulfill({ status: 404, body: "unhandled synthetic API" }); }
    let data;
    if (method === "GET") {
      state.reads.push({ path, query, token: request.headers().accesstoken });
      if (path.endsWith("/options")) data = { analytes: [{ key: "creatinine", label: "合成肌酐项目身份" }], states: ["draft", "published", "revoked"], clinical_mapping_seeded: false };
      else if (path.endsWith("/candidates")) data = { items: structuredClone(state.candidates), truncated: false };
      else if (/\/(lab-mappings|sources|lab-sources)$/.test(path)) {
        const rows = (isMapping ? state.mappings : state.sources).filter(row => (!query.patient_id || String(row.patient_id) === query.patient_id) && (!query.admission_id || row.admission_id === query.admission_id) && (!query.status || row.status === query.status));
        data = { items: structuredClone(rows), total: rows.length, page: Number(query.page || 1), page_size: Number(query.page_size || 50) };
      } else { const id = decodeURIComponent(path.split("/").at(-1)); data = structuredClone((isMapping ? state.mappings : state.sources).find(row => row[isMapping ? "mapping_id" : "lab_source_id"] === id)); }
      if (state.delayed?.(method, path, query)) await new Promise(resolve => { state.release = resolve; });
      return respond(data);
    }
    const body = request.postDataJSON(); state.writes.push({ path, body, token: request.headers().accesstoken });
    if (path.endsWith("/publish") || path.endsWith("/revoke")) {
      const id = decodeURIComponent(path.split("/").at(-2)); const row = (isMapping ? state.mappings : state.sources).find(item => item[isMapping ? "mapping_id" : "lab_source_id"] === id);
      Object.assign(row, { status: path.endsWith("/publish") ? "published" : "revoked", revision: row.revision + 1, ...(path.endsWith("/publish") ? { published_at: stamp, review_note: body.review_note } : { can_revoke: false, revoke_reason: body.reason, revoked_at: stamp }) }); data = structuredClone(row);
    } else if (isMapping) { data = mapping({ ...body, mapping_id: "new-synthetic-mapping", status: "draft", revision: 1, published_at: null, review_note: "" }); state.mappings.push(structuredClone(data)); }
    else { data = source({ patient_id: body.patient_id, admission_id: body.admission_id }, { collected_at_utc: body.collected_at_utc, observation_id: body.observation_id, mapping_id: body.mapping_id }); Object.assign(data.snapshot, body); state.sources.push(structuredClone(data)); }
    if (state.wrongSource && !isMapping) data.admission_id = "wrong-admission";
    if (state.mutateReceipt) state.mutateReceipt(data, path);
    if (state.delayed?.(method, path, body)) await new Promise(resolve => { state.release = resolve; });
    return respond(data);
  });
  await page.goto(harness.origin); await page.waitForFunction(() => !!window.__laboratoryProbe); return state;
}
async function select(page, name, label, scope = page) { const control = scope.getByRole("combobox", { name, exact: true }); await expect(control).toBeEnabled(); await control.press("ArrowDown"); await page.locator(`#${await control.getAttribute("aria-controls")}`).getByRole("option", { name: label, exact: true }).click(); }
async function prepare(page) {
  await page.getByRole("button", { name: "登记已审核检验原来源", exact: true }).click(); await page.getByRole("button", { name: "读取已审核检验候选", exact: true }).click();
  await select(page, "待核实原检验观察项", `合成检验项目 · 0.00000000 synthetic-unit · ${legacyClock}`); await select(page, "受控检验项目映射", "合成肌酐项目身份 · synthetic-lis · v2");
}
async function attest(page) {
  await page.getByRole("textbox", { name: "人工核实采样UTC", exact: true }).fill("2020-01-01T12:05:06.123456+08:00");
  for (const label of ["我已核实此观察项的真实采样UTC", "我已核实此观察项属于所选患者和原住院", "我已核实原观察项属于所选映射的来源命名空间"]) await page.getByText(label, { exact: true }).click();
  for (const label of ["采样UTC核实依据", "检验原住院关联依据", "检验来源命名空间核实依据"]) await page.getByRole("textbox", { name: label, exact: true }).fill(note);
}
async function admin(page) { await page.evaluate(() => { const probe = window.__laboratoryProbe; probe.store.commit("user/permissions", ["super_admin"]); probe.scope.mode = "management"; }); await expect(page.getByLabel("检验项目映射与来源治理", { exact: true })).toBeVisible(); }
function noInference(state) { expect(state.inference).toEqual([]); expect(state.forbidden).toEqual([]); }

test("登记只提交原引用、摘要和三项明确依据，不提交可改写数值", async ({ page }) => {
  const state = await session(page); await prepare(page);
  await expect(page.getByRole("textbox", { name: "人工核实采样UTC", exact: true })).toHaveValue(""); await expect(page.getByRole("checkbox", { name: "我已核实此观察项的真实采样UTC", exact: true })).not.toBeChecked();
  await expect(page.getByRole("button", { name: "登记本住院检验来源", exact: true })).toBeDisabled(); await expect(page.getByLabel("原住院受控检验来源", { exact: true })).toContainText(`旧采样钟点 ${legacyClock}（时区未知`);
  await attest(page); await page.getByRole("button", { name: "登记本住院检验来源", exact: true }).click(); await expect.poll(() => state.writes.length).toBe(1);
  expect(state.writes[0].body).toEqual({ ...scopeA, observation_id: observationId, mapping_id: mappingId, expected_source_hash: "d".repeat(64), expected_mapping_hash: "b".repeat(64), collected_at_utc: "2020-01-01T12:05:06.123456+08:00", collection_time_confirmed: true, collection_time_basis_note: note, admission_binding_confirmed: true, admission_binding_note: note, source_namespace_confirmed: true, source_namespace_basis_note: note });
  await expect.poll(() => page.evaluate(() => window.__laboratoryProbe.events.length)).toBe(1); noInference(state);
});

test("采样UTC拒无时区、非法日历、过精度、UTC溢出或未来，不改旧clock", async ({ page }) => {
  const state = await session(page); await prepare(page); await attest(page);
  for (const time of ["2020-01-01T12:05:06", "2020-02-30T00:00:00Z", "2020-01-01T12:05:06.1234567Z", "0001-01-01T00:00:00+23:59", "9999-01-01T00:00:00Z"]) { await page.getByRole("textbox", { name: "人工核实采样UTC", exact: true }).fill(time); await page.getByRole("button", { name: "登记本住院检验来源", exact: true }).click(); }
  expect(state.writes).toEqual([]); noInference(state);
});

test("只有精确签名且已发布的映射可选，不从相似项目或其他患者候选登记", async ({ page }) => {
  const item = candidate(); item.matching_mappings = [mapping({ status: "draft", revision: 1 }), mapping({ signature: { ...signature, unit: "other-unit" } })];
  const state = await session(page, { candidates: [item] }); await page.getByRole("button", { name: "登记已审核检验原来源", exact: true }).click(); await page.getByRole("button", { name: "读取已审核检验候选", exact: true }).click(); await select(page, "待核实原检验观察项", `合成检验项目 · 0.00000000 synthetic-unit · ${legacyClock}`); await expect(page.getByLabel("原住院受控检验来源", { exact: true })).toContainText("没有已审核且精确匹配的映射"); await expect(page.getByRole("button", { name: "登记本住院检验来源", exact: true })).toBeDisabled();
  state.candidates = [candidate(scopeB)]; await page.getByRole("button", { name: "读取已审核检验候选", exact: true }).click(); await expect(page.getByRole("alert")).toContainText("与患者或来源摘要不一致"); expect(state.writes).toEqual([]); noInference(state);
});

test("护士只读已登记来源，查看0和旧clock不授予候选登记权限", async ({ page }) => {
  const state = await session(page, { sources: [source()] }); await page.evaluate(() => window.__laboratoryProbe.store.commit("user/permissions", ["nurse"])); await expect(page.getByLabel("原住院受控检验来源", { exact: true })).toContainText("当前角色只读已登记检验来源"); await expect(page.getByRole("button", { name: "登记已审核检验原来源", exact: true })).toHaveCount(0);
  await page.getByRole("button", { name: "核对原检验来源", exact: true }).click(); const dialog = page.getByRole("dialog", { name: "受控检验原来源核对", exact: true }); await expect(dialog.getByLabel("冻结原检验值", { exact: true })).toHaveText("0.00000000 synthetic-unit"); await expect(dialog).toContainText(legacyClock); await expect(dialog.getByRole("button", { name: "撤销此检验来源", exact: true })).toHaveCount(0); expect(state.reads.some(row => row.path.endsWith("/candidates"))).toBe(false); noInference(state);
});

test("来源详情保留定性文字与null单位并转义，不用0代替定性结果", async ({ page }) => {
  const row = source(); Object.assign(row.snapshot.original.observation, { value_num: null, value_text: "合成定性结果 <img src=x onerror=alert(1)>", unit: null });
  const state = await session(page, { sources: [row] }); await page.getByRole("button", { name: "核对原检验来源", exact: true }).click(); const dialog = page.getByRole("dialog", { name: "受控检验原来源核对", exact: true }); await expect(dialog.getByLabel("冻结原检验值", { exact: true })).toContainText("合成定性结果 <img src=x onerror=alert(1)>"); await expect(dialog.locator("img")).toHaveCount(0); await expect(dialog).toContainText("不是原报告首次可用时间"); noInference(state);
});

for (const change of ["patient", "admission", "session", "role", "inactive"]) {
  test(`迟到来源登记不跨${change}或发布旧范围事件`, async ({ page }) => {
    const state = await session(page); await prepare(page); await attest(page); state.delayed = (method, path) => method === "POST" && path.endsWith("/sources"); await page.getByRole("button", { name: "登记本住院检验来源", exact: true }).click(); await expect.poll(() => !!state.release).toBe(true);
    await page.evaluate(change => { const { scope, store } = window.__laboratoryProbe; if (change === "patient") Object.assign(scope, { patientId: 22, admissionId: "obs-admission-b" }); if (change === "admission") scope.admissionId = "same-patient-other-admission"; if (change === "session") store.commit("user/token", "new-synthetic-session"); if (change === "role") store.commit("user/permissions", ["patient"]); if (change === "inactive") scope.active = false; }, change);
    state.release(); await expect.poll(() => page.evaluate(() => window.__laboratoryProbe.events.length)).toBe(0); expect(state.writes).toHaveLength(1); noInference(state);
  });
}

test("切换原住院后迟到候选与原详情不展示；重新登记须重填三确认", async ({ page }) => {
  const state = await session(page); await prepare(page); await attest(page); state.delayed = (method, path) => method === "GET" && path.endsWith("/candidates"); await page.getByRole("button", { name: "读取已审核检验候选", exact: true }).click(); await expect.poll(() => !!state.release).toBe(true); await page.evaluate(() => Object.assign(window.__laboratoryProbe.scope, { patientId: 22, admissionId: "obs-admission-b" })); state.release(); await expect(page.getByRole("combobox", { name: "待核实原检验观察项", exact: true })).toHaveValue(""); await expect(page.getByRole("textbox", { name: "人工核实采样UTC", exact: true })).toHaveCount(0); expect(state.writes).toEqual([]); noInference(state);
});

test("原来源撤销绑定患者住院及expected_revision，元数据正确也拒内部串源", async ({ page }) => {
  const state = await session(page, { sources: [source()] }); await page.getByRole("button", { name: "核对原检验来源", exact: true }).click(); let dialog = page.getByRole("dialog", { name: "受控检验原来源核对", exact: true }); await dialog.getByRole("textbox", { name: "检验来源撤销依据", exact: true }).fill("核对原资料后撤销错误登记"); await dialog.getByRole("button", { name: "撤销此检验来源", exact: true }).click(); await expect.poll(() => state.writes.length).toBe(1); expect(state.writes[0].body).toEqual({ ...scopeA, expected_revision: 1, reason: "核对原资料后撤销错误登记" }); await dialog.getByRole("button", { name: "关闭", exact: true }).click();
  state.sources[0].snapshot.original.order.patient_id = 22; await page.getByRole("button", { name: "核对原检验来源", exact: true }).click(); await expect(dialog.getByRole("alert")).toContainText("不一致"); await expect(dialog.getByLabel("冻结原检验值", { exact: true })).toHaveCount(0); noInference(state);
});

test("超管草稿不自动发布，定性无单位显式null；发布需两项确认及审核依据", async ({ page }) => {
  const state = await session(page); await admin(page); await page.getByRole("button", { name: "新建项目映射草稿", exact: true }).click(); let dialog = page.getByRole("dialog", { name: "新建检验项目映射草稿", exact: true }); await expect(dialog.getByRole("combobox", { name: "映射结果类型", exact: true })).toHaveValue("");
  for (const [name, value] of [["映射来源命名空间", "synthetic-new-lis"], ["映射原编码体系", "local"], ["映射原项目编码", "SYN-QUAL"], ["映射原检测方法", "synthetic_method"], ["映射原标本类型", "synthetic_specimen"], ["映射依据来源标识", "synthetic-only-reference"], ["映射项目身份核对依据", note]]) await dialog.getByRole("textbox", { name, exact: true }).fill(value);
  await select(page, "映射结果类型", "定性", dialog); await select(page, "映射目标项目身份", "合成肌酐项目身份", dialog); await dialog.getByRole("button", { name: "仅保存映射草稿", exact: true }).click(); await expect.poll(() => state.writes.length).toBe(1); expect(state.writes[0].body.signature).toEqual({ code_system: "local", code: "SYN-QUAL", unit: null, method: "synthetic_method", specimen_type: "synthetic_specimen", value_kind: "qualitative" }); expect(state.writes[0].path).toBe("/api/ai/admin/lab-mappings");
  await page.getByRole("row").filter({ hasText: "synthetic-new-lis" }).getByRole("button", { name: "核对项目映射", exact: true }).click(); dialog = page.getByRole("dialog", { name: "检验项目映射审核", exact: true }); await expect(dialog.getByRole("button", { name: "审核并发布此映射版本", exact: true })).toBeDisabled(); await dialog.getByText("我已核对目标项目语义身份", { exact: true }).click(); await dialog.getByText("我已核对来源命名空间和完整原签名", { exact: true }).click(); await dialog.getByRole("textbox", { name: "项目映射审核说明", exact: true }).fill(note); await dialog.getByRole("button", { name: "审核并发布此映射版本", exact: true }).click(); await expect.poll(() => state.writes.length).toBe(2); expect(state.writes[1].body).toEqual({ expected_revision: 1, semantic_confirmed: true, source_signature_confirmed: true, review_note: note }); noInference(state);
});

test("超管全院检验审计保留冻结映射与0，按原范围撤销来源", async ({ page }) => {
  const row = source(); row.mapping_current = { status: "revoked", revision: 3 }; row.eligible = false; row.exclusion_reasons = ["mapping_revoked"];
  const state = await session(page, { sources: [row] }); await admin(page); await page.getByRole("tab", { name: "检验来源全院审计", exact: true }).click(); await page.getByRole("textbox", { name: "检验来源治理患者ID", exact: true }).fill("11"); await page.getByRole("textbox", { name: "检验来源治理原住院ID", exact: true }).fill(scopeA.admission_id); await page.getByRole("button", { name: "查询全院检验来源", exact: true }).click(); await page.getByRole("button", { name: "核对冻结检验", exact: true }).click(); const dialog = page.getByRole("dialog", { name: "冻结检验来源审计", exact: true }); await expect(dialog.getByLabel("冻结原检验值", { exact: true })).toHaveText("0.00000000 synthetic-unit"); await expect(dialog).toContainText("当前映射状态 revoked"); await expect(dialog).toContainText(`${mappingId} · v2 · published`); await dialog.getByRole("textbox", { name: "检验治理撤销依据", exact: true }).fill("核对全院原检验登记后撤销来源"); await dialog.getByRole("button", { name: "撤销此检验来源", exact: true }).click(); await expect.poll(() => state.writes.length).toBe(1); expect(state.writes[0].body).toEqual({ ...scopeA, expected_revision: 1, reason: "核对全院原检验登记后撤销来源" }); expect(state.reads.some(row => row.path === "/api/ai/admin/lab-sources" && row.query.patient_id === "11" && row.query.admission_id === scopeA.admission_id)).toBe(true); noInference(state);
});

test("超管失去角色后迟到治理详情不展示也不能发布", async ({ page }) => {
  const state = await session(page); await admin(page); state.delayed = (method, path) => method === "GET" && path.endsWith(`/${mappingId}`); await page.getByRole("button", { name: "核对项目映射", exact: true }).click(); await expect.poll(() => !!state.release).toBe(true); await page.evaluate(() => window.__laboratoryProbe.store.commit("user/permissions", ["admin"])); state.release(); await expect(page.getByLabel("检验项目映射与来源治理", { exact: true })).toContainText("仅超级管理员"); await expect(page.getByRole("dialog", { name: "检验项目映射审核", exact: true })).not.toBeVisible(); expect(state.writes).toEqual([]); noInference(state);
});

test("登记回执必须绑定两个原摘要，不清除错误回执前的人工核实", async ({ page }) => {
  const state = await session(page); await prepare(page); await attest(page);
  state.mutateReceipt = data => { data.raw_original_hash = "e".repeat(64); data.snapshot.raw_original_hash = data.raw_original_hash; };
  await page.getByRole("button", { name: "登记本住院检验来源", exact: true }).click();
  await expect(page.getByRole("alert")).toContainText("登记回执"); await expect(page.getByRole("textbox", { name: "人工核实采样UTC", exact: true })).toHaveValue("2020-01-01T12:05:06.123456+08:00");
  expect(await page.evaluate(() => window.__laboratoryProbe.events)).toEqual([]); noInference(state);
});

test("普通失效详情无冻结值时不回退到猜测原文，窗口投影明确省略父正文", async ({ page }) => {
  const row = source(); row.snapshot = null; row.freshness = { state: "stale", message: "合成来源已变化" }; row.eligible = false; row.original = original();
  const state = await session(page, { sources: [row] }); await page.getByRole("button", { name: "核对原检验来源", exact: true }).click();
  const dialog = page.getByRole("dialog", { name: "受控检验原来源核对", exact: true }); await expect(dialog).toContainText("当前响应未提供冻结原值"); await expect(dialog.getByLabel("冻结原检验值", { exact: true })).toHaveCount(0);
  await dialog.getByRole("button", { name: "关闭", exact: true }).click();
  state.sources[0] = source(); state.sources[0].window_projection = "risk_lab_projection_v1";
  await page.getByRole("button", { name: "核对原检验来源", exact: true }).click();
  await expect(dialog).toContainText("原报告全文与申请正文未作为本窗事实输入"); await expect(dialog).toContainText("人工核实说明仅用于溯源，不是测量结果"); await expect(dialog.getByLabel("冻结原检验值", { exact: true })).toHaveText("0.00000000 synthetic-unit"); noInference(state);
});

test("超管撤销发布映射按版本2请求，错误版本回执不冒称完成", async ({ page }) => {
  const state = await session(page); await admin(page); await page.getByRole("button", { name: "核对项目映射", exact: true }).click();
  const dialog = page.getByRole("dialog", { name: "检验项目映射审核", exact: true }); await dialog.getByRole("textbox", { name: "检验治理撤销依据", exact: true }).fill("合成依据复核后撤销原映射版本");
  state.mutateReceipt = data => { data.revision = 2; };
  await dialog.getByRole("button", { name: "撤销此映射版本", exact: true }).click(); await expect(dialog.getByRole("alert")).toContainText("状态、版本或内容摘要");
  expect(state.writes[0].body).toEqual({ expected_revision: 2, reason: "合成依据复核后撤销原映射版本" }); await expect(dialog).toContainText("已发布 · v2"); noInference(state);
});

test("超管会话变更后迟到发布回执不进入新会话详情", async ({ page }) => {
  const state = await session(page, { mappings: [mapping({ status: "draft", revision: 1 })] }); await admin(page); await page.getByRole("button", { name: "核对项目映射", exact: true }).click();
  const dialog = page.getByRole("dialog", { name: "检验项目映射审核", exact: true });
  for (const label of ["我已核对目标项目语义身份", "我已核对来源命名空间和完整原签名"]) await dialog.getByText(label, { exact: true }).click();
  await dialog.getByRole("textbox", { name: "项目映射审核说明", exact: true }).fill(note); state.delayed = (method, path) => method === "POST" && path.endsWith("/publish");
  await dialog.getByRole("button", { name: "审核并发布此映射版本", exact: true }).click(); await expect.poll(() => !!state.release).toBe(true);
  await page.evaluate(() => window.__laboratoryProbe.store.commit("user/token", "new-admin-synthetic-session")); state.release();
  await expect(dialog).not.toBeVisible(); expect(state.writes).toHaveLength(1); noInference(state);
});

test.afterEach(async () => { expect(harness.unhandled).toEqual([]); });
