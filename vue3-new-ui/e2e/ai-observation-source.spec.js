const { test, expect } = require("@playwright/test");
const { startObservationHarness } = require("./fixtures/observation-source-harness.cjs");

test.describe.configure({ mode: "default" });
let harness;
const stamp = "2020-01-02T03:04:05.123456Z";
const scopeA = { patient_id: 11, admission_id: "obs-admission-a" };
const scopeB = { patient_id: 22, admission_id: "obs-admission-b" };
const meta = (scope = scopeA) => ({ ...scope, status: "active", revision: 1, content_hash: "a".repeat(64), created_by: 7, can_revoke: true, recorded_at: stamp });
const point = (scope = scopeA) => ({ ...meta(scope), observation_id: `point-${scope.patient_id}`, observed_at: stamp, payload: { measurements: { spo2: { value: "0", unit: "%", absent_reason: null }, respiratory_rate: { value: null, unit: "/min", absent_reason: "not_performed" } }, supplemental_oxygen: "unknown", oxygen_device: null, consciousness: null, note: "合成原观察 <img src=x onerror=alert(1)>" } });
const urine = (scope = scopeA) => ({ ...meta(scope), interval_id: `urine-${scope.patient_id}`, start_at: "2020-01-02T02:00:00Z", end_at: "2020-01-02T03:00:00Z", payload: { volume_ml: "0", absent_reason: null, collection_completeness: "unknown", patient_total: null, collection_method: "合成收集", note: "" } });
const windowRow = (scope = scopeA) => ({ ...meta(scope), window_id: `window-${scope.patient_id}`, start_at: "2020-01-02T02:00:00Z", end_at: "2020-01-02T04:00:00Z", as_of: "2020-01-02T04:00:01Z", created_at: stamp, freshness: { state: "not_checked" } });
const windowDetail = (scope = scopeA) => ({ ...windowRow(scope), window_id: scope.window_id ?? `window-${scope.patient_id}`, freshness: { state: "current", message: "合成原资料本次一致" }, snapshot: { window_id: scope.window_id ?? `window-${scope.patient_id}`, patient_id: scope.patient_id, admission_id: scope.admission_id, points: [point(scope)], urine_intervals: [urine(scope)], limitations: ["采样计划未知，不代表连续监护齐全"], quality: { urine_coverage: "unknown" } } });

test.beforeAll(async () => { harness = await startObservationHarness(); });
test.afterAll(async () => { await harness?.close(); });

async function session(page, options = {}) {
  const state = { reads: [], writes: [], inference: [], forbidden: [], points: options.points ?? [point()], urine: options.urine ?? [urine()], windows: options.windows ?? [windowRow()], delayed: null, release: null, wrongList: false, wrongDetail: false, wrongCreate: false, wrongFrozen: false, freshness: "current" };
  await page.context().route("**/*", route => new URL(route.request().url()).origin === harness.origin ? route.continue() : route.abort("blockedbyclient"));
  await page.route("**/api/**", async route => {
    const request = route.request(), url = new URL(request.url()), path = url.pathname, method = request.method(), query = Object.fromEntries(url.searchParams);
    const response = value => route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ code: 200, msg: "synthetic", ...value }) });
    if (/\/ai\/(runs|context)(\/|$)/.test(path)) { state.inference.push({ path, method }); return response({ data: {} }); }
    const sourceKind = path.includes("/points") ? "points" : path.includes("/urine-intervals") ? "urine" : path.includes("/observation-windows") ? "windows" : null;
    if (!sourceKind) { state.forbidden.push({ path, method }); return route.fulfill({ status: 404, body: "unhandled synthetic API" }); }
    const idKey = { points: "observation_id", urine: "interval_id", windows: "window_id" }[sourceKind];
    if (method === "GET") {
      state.reads.push({ path, query, token: request.headers().accesstoken });
      const isList = /\/(points|urine-intervals|observation-windows)$/.test(path);
      let data;
      if (isList) {
        const rows = state[sourceKind].filter(row => (state.wrongList || !query.patient_id || String(row.patient_id) === query.patient_id) && (state.wrongList || !query.admission_id || row.admission_id === query.admission_id) && (!query.status || row.status === query.status));
        const page = Number(query.page || 1), pageSize = Number(query.page_size || 50);
        data = sourceKind === "windows" ? structuredClone(rows) : { items: structuredClone(rows.slice((page - 1) * pageSize, page * pageSize)), total: rows.length, page, page_size: pageSize };
      } else {
        const id = decodeURIComponent(path.split("/").at(-1));
        const base = state[sourceKind].find(row => row[idKey] === id);
        data = sourceKind === "windows" ? { ...windowDetail(base || scopeA), ...structuredClone(base), freshness: { state: state.freshness, message: "合成一致性说明" } } : structuredClone(base);
        if (data && state.wrongDetail) data.admission_id = "different-admission";
        if (data && state.wrongFrozen && sourceKind === "windows") data.snapshot.points[0].patient_id = 22;
        if (data && options.metadataOnlyWindow && sourceKind === "windows") data.snapshot = null;
      }
      if (state.delayed?.(path, method, query)) await new Promise(resolve => { state.release = resolve; });
      return response({ data, truncated: false });
    }
    if (method !== "POST") { state.forbidden.push({ path, method }); return route.fulfill({ status: 405 }); }
    const body = request.postDataJSON(); state.writes.push({ path, body, token: request.headers().accesstoken });
    let data;
    if (path.endsWith("/revoke")) {
      const id = decodeURIComponent(path.split("/").at(-2)); const row = state[sourceKind].find(item => item[idKey] === id);
      Object.assign(row, { status: "revoked", revision: row.revision + 1, can_revoke: false, revoked_at: stamp, revoke_reason: body.reason });
      data = sourceKind === "windows" ? { ...windowDetail(row), ...structuredClone(row), freshness: { state: "revoked" } } : structuredClone(row);
    } else {
      const scope = { patient_id: body.patient_id, admission_id: body.admission_id };
      data = sourceKind === "points" ? { ...point(scope), observation_id: `created-point-${body.patient_id}`, observed_at: body.observed_at, payload: Object.fromEntries(Object.entries(body).filter(([key]) => !["patient_id", "admission_id", "observed_at"].includes(key))) }
        : sourceKind === "urine" ? { ...urine(scope), interval_id: `created-urine-${body.patient_id}`, start_at: body.start_at, end_at: body.end_at, payload: Object.fromEntries(Object.entries(body).filter(([key]) => !["patient_id", "admission_id", "start_at", "end_at"].includes(key))) }
          : { ...windowDetail({ ...scope, window_id: `created-window-${body.patient_id}` }), start_at: body.start_at, end_at: body.end_at, as_of: body.as_of };
      state[sourceKind].push(structuredClone(data));
    }
    if (state.wrongCreate) data.admission_id = "different-admission";
    if (state.delayed?.(path, method, body)) await new Promise(resolve => { state.release = resolve; });
    return response({ data });
  });
  await page.goto(harness.origin);
  await page.waitForFunction(() => !!window.__observationProbe);
  return state;
}
async function select(page, name, option, scope = page) {
  const control = scope.getByRole("combobox", { name, exact: true }); await expect(control).toBeEnabled(); await control.press("ArrowDown");
  const listbox = page.locator(`#${await control.getAttribute("aria-controls")}`); await listbox.getByRole("option", { name: option, exact: true }).click();
}
async function pointForm(page, value = "0") { await page.getByRole("textbox", { name: "实际观察时点", exact: true }).fill("2020-01-02T11:04:05.123456+08:00"); await page.getByRole("textbox", { name: "SpO₂原始数值", exact: true }).fill(value); await select(page, "观察时吸氧情况", "吸氧情况未知"); }
const panel = page => page.getByLabel("原住院生理观测来源", { exact: true });
async function admin(page) { await page.evaluate(() => { const probe = window.__observationProbe; probe.store.commit("user/permissions", ["super_admin"]); probe.scope.mode = "management"; }); await expect(page.getByLabel("AI住院观测窗管理", { exact: true })).toBeVisible(); }
function noInference(state) { expect(state.inference).toEqual([]); expect(state.forbidden).toEqual([]); }

test("新观测表单空白，不默认无氧或正常；目录均绑定原患者和住院", async ({ page }) => {
  const state = await session(page);
  await expect(page.getByRole("textbox", { name: "实际观察时点", exact: true })).toHaveValue("");
  await expect(page.getByRole("textbox", { name: "SpO₂原始数值", exact: true })).toHaveValue("");
  await expect(page.getByRole("combobox", { name: "观察时吸氧情况", exact: true })).toHaveValue("");
  await expect.poll(() => state.reads.length).toBe(3);
  expect(state.reads.every(row => row.query.patient_id === "11" && row.query.admission_id === scopeA.admission_id && row.token === "synthetic-observation-session")).toBe(true);
  await expect(panel(page)).toContainText("采样计划未知"); expect(state.writes).toEqual([]); noInference(state);
});

test("原住院点测目录可翻页，不把第一页当作完整序列", async ({ page }) => {
  const points = Array.from({ length: 51 }, (_, index) => ({ ...point(), observation_id: `page-point-${index + 1}` }));
  const state = await session(page, { points }); const directory = page.getByLabel("点测量原来源目录", { exact: true });
  await expect(directory).toContainText("原目录共51项"); await expect(directory).toContainText("请翻页核对");
  await directory.getByRole("button", { name: "下一页点测量", exact: true }).click(); await expect(directory).toContainText("page-point-51");
  await expect.poll(() => state.reads.some(row => row.path.endsWith("/points") && row.query.page === "2" && row.query.patient_id === "11" && row.query.admission_id === scopeA.admission_id)).toBe(true);
  await expect(directory.getByRole("button", { name: "下一页点测量", exact: true })).toBeDisabled(); noInference(state);
});

test("点测保留明确0与独立缺失原因、原时区微秒，不自动补其余指标", async ({ page }) => {
  const state = await session(page); await pointForm(page, "0.00"); await select(page, "呼吸率缺失原因", "未测量");
  await page.getByRole("button", { name: "登记点测量", exact: true }).click(); await expect.poll(() => state.writes.length).toBe(1);
  expect(state.writes[0].body).toEqual({ ...scopeA, observed_at: "2020-01-02T11:04:05.123456+08:00", measurements: { respiratory_rate: { value: null, unit: "/min", absent_reason: "not_performed" }, spo2: { value: "0.00", unit: "%", absent_reason: null } }, supplemental_oxygen: "unknown", oxygen_device: null, consciousness: null, note: "" });
  await expect(page.getByRole("textbox", { name: "实际观察时点", exact: true })).toHaveValue(""); noInference(state);
});

test("只有明确未测原因可登记为尝试事实，完全空白仍不提交", async ({ page }) => {
  const state = await session(page);
  await page.getByRole("textbox", { name: "实际观察时点", exact: true }).fill(stamp);
  await select(page, "观察时吸氧情况", "吸氧情况未知");
  await page.getByRole("button", { name: "登记点测量", exact: true }).click();
  expect(state.writes).toEqual([]);
  await select(page, "呼吸率缺失原因", "未测量");
  await page.getByRole("button", { name: "登记点测量", exact: true }).click();
  await expect.poll(() => state.writes.length).toBe(1);
  expect(state.writes[0].body).toMatchObject({ measurements: { respiratory_rate: { value: null, unit: "/min", absent_reason: "not_performed" } }, supplemental_oxygen: "unknown", consciousness: null });
  await expect(panel(page)).toContainText("测量尝试或评估时点"); noInference(state);
});

test("非法日期、无时区、过度精度与UTC溢出不提交，数值缺失原因不能共存", async ({ page }) => {
  const state = await session(page); await pointForm(page);
  for (const time of ["2020-02-30T00:00:00Z", "2020-01-02T03:04:05", "2020-01-02T03:04:05.1234567Z", "2020-01-02T24:00:00Z", "0001-01-01T00:00:00+23:59", "9999-12-31T23:59:59-23:59"]) { await page.getByRole("textbox", { name: "实际观察时点", exact: true }).fill(time); await page.getByRole("button", { name: "登记点测量", exact: true }).click(); }
  expect(state.writes).toEqual([]); await page.getByRole("textbox", { name: "实际观察时点", exact: true }).fill(stamp); await select(page, "SpO₂缺失原因", "测量失败"); await page.getByRole("button", { name: "登记点测量", exact: true }).click(); expect(state.writes).toEqual([]); noInference(state);
});

test("意识明确选择AVPU或ACVPU，不把旧编码或GCS补入来源", async ({ page }) => {
  const state = await session(page); await page.getByRole("textbox", { name: "实际观察时点", exact: true }).fill(stamp); await select(page, "观察时吸氧情况", "未吸氧"); await select(page, "意识记录体系", "AVPU");
  const code = page.getByRole("combobox", { name: "实际意识观察", exact: true }); await code.press("ArrowDown"); let list = page.locator(`#${await code.getAttribute("aria-controls")}`); await expect(list.getByRole("option", { name: "新发意识混乱（new_confusion）", exact: true })).toHaveCount(0); await code.press("Escape");
  await select(page, "意识记录体系", "ACVPU"); await select(page, "实际意识观察", "新发意识混乱（new_confusion）"); await page.getByRole("button", { name: "登记点测量", exact: true }).click(); await expect.poll(() => state.writes.length).toBe(1);
  expect(state.writes[0].body).toMatchObject({ measurements: {}, supplemental_oxygen: "no", consciousness: { system: "ACVPU", code: "new_confusion" } }); expect(state.writes[0].body).not.toHaveProperty("gcs_score"); noInference(state);
});

test("尿量不默认完整或患者总量，未知与真实0分别保留", async ({ page }) => {
  const state = await session(page); await page.getByRole("tab", { name: "尿量", exact: true }).click();
  await expect(page.getByRole("textbox", { name: "区间尿量mL", exact: true })).toHaveValue(""); await expect(page.getByRole("combobox", { name: "尿量收集完整性", exact: true })).toHaveValue(""); await expect(page.getByRole("combobox", { name: "尿量是否患者总量", exact: true })).toHaveValue("");
  const fill = async () => { await page.getByRole("textbox", { name: "尿量收集开始", exact: true }).fill("2020-01-02T02:00:00.000001Z"); await page.getByRole("textbox", { name: "尿量收集结束", exact: true }).fill("2020-01-02T03:00:00.000002Z"); await select(page, "尿量收集完整性", "完整性未知"); await select(page, "尿量是否患者总量", "总量范围未知"); await page.getByRole("textbox", { name: "尿量收集方法", exact: true }).fill("按原收集记录核对"); };
  await fill(); await select(page, "尿量缺失原因", "未测量"); await page.getByRole("button", { name: "登记分时尿量", exact: true }).click(); await expect.poll(() => state.writes.length).toBe(1);
  expect(state.writes[0].body).toMatchObject({ ...scopeA, volume_ml: null, absent_reason: "not_performed", patient_total: null, collection_completeness: "unknown", start_at: "2020-01-02T02:00:00.000001Z", end_at: "2020-01-02T03:00:00.000002Z" });
  await expect(page.getByRole("textbox", { name: "区间尿量mL", exact: true })).toBeEnabled(); await fill(); await page.getByRole("textbox", { name: "区间尿量mL", exact: true }).fill("0"); await page.getByRole("button", { name: "登记分时尿量", exact: true }).click(); await expect.poll(() => state.writes.length).toBe(2); expect(state.writes[1].body).toMatchObject({ volume_ml: "0", absent_reason: null, patient_total: null }); noInference(state);
});

test("观测窗保留微秒界限，只冻结明确原住院并发出来源事件", async ({ page }) => {
  const state = await session(page); await page.getByRole("tab", { name: "观测窗", exact: true }).click();
  await page.getByRole("textbox", { name: "观测窗开始", exact: true }).fill("2020-01-02T03:00:00.000001Z"); await page.getByRole("textbox", { name: "观测窗结束", exact: true }).fill("2020-01-02T03:00:00.000002Z"); await page.getByRole("textbox", { name: "观测窗截至时点", exact: true }).fill("2020-01-02T03:00:00.000002Z"); await page.getByRole("button", { name: "冻结本住院观测窗", exact: true }).click(); await expect.poll(() => state.writes.length).toBe(1);
  expect(state.writes[0].body).toEqual({ ...scopeA, start_at: "2020-01-02T03:00:00.000001Z", end_at: "2020-01-02T03:00:00.000002Z", as_of: "2020-01-02T03:00:00.000002Z" }); await expect.poll(() => page.evaluate(() => window.__observationProbe.events.length)).toBe(1); noInference(state);
});

test("观测窗拒绝反向、未来或超过168小时；当前UTC按钮只填截至时点", async ({ page }) => {
  const state = await session(page); await page.getByRole("tab", { name: "观测窗", exact: true }).click(); await page.getByRole("button", { name: "填入当前UTC", exact: true }).click(); await expect(page.getByRole("textbox", { name: "观测窗截至时点", exact: true })).not.toHaveValue(""); await expect(page.getByRole("textbox", { name: "观测窗开始", exact: true })).toHaveValue(""); await expect(page.getByRole("textbox", { name: "观测窗结束", exact: true })).toHaveValue("");
  for (const [start, end, asOf] of [["2020-01-02T03:00:00.000002Z", "2020-01-02T03:00:00.000001Z", stamp], ["2020-01-01T00:00:00Z", "2020-01-09T00:00:00Z", "2020-01-10T00:00:00Z"], ["2020-01-01T00:00:00Z", "2020-01-02T00:00:00Z", "9999-01-01T00:00:00Z"]]) { await page.getByRole("textbox", { name: "观测窗开始", exact: true }).fill(start); await page.getByRole("textbox", { name: "观测窗结束", exact: true }).fill(end); await page.getByRole("textbox", { name: "观测窗截至时点", exact: true }).fill(asOf); await page.getByRole("button", { name: "冻结本住院观测窗", exact: true }).click(); }
  expect(state.writes).toEqual([]); noInference(state);
});

test("核对原点测量保留0、缺项及文本转义，撤销绑定原患者住院和版本", async ({ page }) => {
  const state = await session(page); const directory = page.getByLabel("点测量原来源目录", { exact: true }); await directory.getByRole("button", { name: "核对原来源", exact: true }).click();
  const dialog = page.getByRole("dialog", { name: "原住院观测来源核对", exact: true }); await expect(dialog).toContainText("0 %"); await expect(dialog).toContainText("未测量"); await expect(dialog).toContainText("合成原观察 <img src=x onerror=alert(1)>"); await expect(dialog.locator("img")).toHaveCount(0);
  expect(state.reads.find(row => row.path.endsWith("/points/point-11")).query).toEqual({ patient_id: "11", admission_id: scopeA.admission_id }); await dialog.getByRole("textbox", { name: "观测来源撤销依据", exact: true }).fill("按原护理记录核对后撤销错误录入"); await dialog.getByRole("button", { name: "撤销此观测来源", exact: true }).click(); await expect.poll(() => state.writes.length).toBe(1); expect(state.writes[0].body).toEqual({ ...scopeA, expected_revision: 1, reason: "按原护理记录核对后撤销错误录入" }); await expect(dialog).toContainText("已撤销"); noInference(state);
});

test("切换患者和住院清空草稿及目录，迟到列表不能显示在新住院", async ({ page }) => {
  const state = await session(page); await expect.poll(() => state.reads.length).toBe(3); state.points.push(point(scopeB)); await pointForm(page); await page.getByRole("textbox", { name: "点测来源备注", exact: true }).fill("甲的未保存备注");
  state.delayed = (path, method, query) => method === "GET" && path.endsWith("/points") && query.patient_id === "11"; await page.getByRole("button", { name: "刷新点测量来源", exact: true }).click(); await expect.poll(() => !!state.release).toBe(true);
  await page.evaluate(() => Object.assign(window.__observationProbe.scope, { patientId: 22, admissionId: "obs-admission-b" })); await expect(page.getByRole("textbox", { name: "点测来源备注", exact: true })).toHaveValue(""); await expect(page.getByRole("textbox", { name: "实际观察时点", exact: true })).toHaveValue(""); state.release(); await expect(page.getByLabel("点测量原来源目录", { exact: true })).toContainText("point-22"); await expect(page.getByLabel("点测量原来源目录", { exact: true })).not.toContainText("point-11"); noInference(state);
});

test("来源可读不等于可撤销，界面使用服务器的当前动作权限", async ({ page }) => {
  const source = point(); source.can_revoke = false;
  const state = await session(page, { points: [source] });
  await page.getByLabel("点测量原来源目录", { exact: true }).getByRole("button", { name: "核对原来源", exact: true }).click();
  const dialog = page.getByRole("dialog", { name: "原住院观测来源核对", exact: true });
  await expect(dialog).toContainText("0 %"); await expect(dialog.getByRole("button", { name: "撤销此观测来源", exact: true })).toHaveCount(0);
  expect(state.writes).toEqual([]); noInference(state);
});

for (const change of ["patient", "session", "role", "inactive"]) {
  test(`迟到保存不会跨越${change}绑定或清空新草稿`, async ({ page }) => {
    const state = await session(page); state.delayed = (path, method) => method === "POST" && path.endsWith("/points"); await pointForm(page); await page.getByRole("button", { name: "登记点测量", exact: true }).click(); await expect.poll(() => !!state.release).toBe(true);
    await page.evaluate(change => { const { scope, store } = window.__observationProbe; if (change === "patient") Object.assign(scope, { patientId: 22, admissionId: "obs-admission-b" }); if (change === "session") store.commit("user/token", "different-synthetic-session"); if (change === "role") store.commit("user/permissions", ["patient"]); if (change === "inactive") scope.active = false; }, change);
    if (["patient", "session"].includes(change)) { await page.getByRole("textbox", { name: "点测来源备注", exact: true }).fill("新范围草稿必须保留"); state.release(); await expect(page.getByRole("textbox", { name: "点测来源备注", exact: true })).toHaveValue("新范围草稿必须保留"); await expect(page.getByRole("button", { name: "登记点测量", exact: true })).toBeEnabled(); }
    else { state.release(); await expect(page.getByRole("textbox", { name: "点测来源备注", exact: true })).toHaveCount(0); await expect(page.getByRole("dialog", { name: "原住院观测来源核对", exact: true })).not.toBeVisible(); }
    expect(state.writes).toHaveLength(1); noInference(state);
  });
}

test("错误归属列表、原详情和保存回执不进入当前来源或清空草稿", async ({ page }) => {
  const state = await session(page); await expect.poll(() => state.reads.length).toBe(3); state.wrongDetail = true; await page.getByLabel("点测量原来源目录", { exact: true }).getByRole("button", { name: "核对原来源", exact: true }).click(); let dialog = page.getByRole("dialog", { name: "原住院观测来源核对", exact: true }); await expect(dialog.getByRole("alert")).toContainText("不一致"); await expect(dialog).not.toContainText("合成原观察"); await dialog.getByRole("button", { name: "关闭", exact: true }).click();
  state.wrongCreate = true; await pointForm(page); await page.getByRole("textbox", { name: "点测来源备注", exact: true }).fill("本住院草稿仍保留"); await page.getByRole("button", { name: "登记点测量", exact: true }).click(); await expect.poll(() => state.writes.length).toBe(1); await expect(page.getByRole("textbox", { name: "点测来源备注", exact: true })).toHaveValue("本住院草稿仍保留");
  state.points = [point(scopeB)]; state.wrongList = true; await page.getByRole("button", { name: "刷新点测量来源", exact: true }).click(); const directory = page.getByLabel("点测量原来源目录", { exact: true }); await expect(directory.getByRole("alert")).toContainText("不一致"); await expect(directory).not.toContainText("point-22"); noInference(state);
});

test("普通用户过期窗口仅显示元数据，不补回旧原值", async ({ page }) => {
  const state = await session(page, { metadataOnlyWindow: true }); state.freshness = "stale";
  await page.getByRole("tab", { name: "观测窗", exact: true }).click();
  await page.getByLabel("观测窗原来源目录", { exact: true }).getByRole("button", { name: "核对原来源", exact: true }).click();
  const dialog = page.getByRole("dialog", { name: "原住院观测来源核对", exact: true });
  await expect(dialog).toContainText("原资料已变化"); await expect(dialog).toContainText("当前响应未提供冻结数值"); await expect(dialog).not.toContainText("0 %");
  expect(state.reads.find(row => row.path.endsWith("/observation-windows/window-11")).query).toEqual({ patient_id: "11", admission_id: scopeA.admission_id }); noInference(state);
});

test("迟到冻结窗口回执不能发布给新住院或清空新窗口边界", async ({ page }) => {
  const state = await session(page); state.delayed = (path, method) => method === "POST" && path.endsWith("/observation-windows");
  await page.getByRole("tab", { name: "观测窗", exact: true }).click();
  await page.getByRole("textbox", { name: "观测窗开始", exact: true }).fill("2020-01-02T02:00:00Z"); await page.getByRole("textbox", { name: "观测窗结束", exact: true }).fill("2020-01-02T03:00:00Z"); await page.getByRole("textbox", { name: "观测窗截至时点", exact: true }).fill(stamp); await page.getByRole("button", { name: "冻结本住院观测窗", exact: true }).click();
  await expect.poll(() => !!state.release).toBe(true);
  await page.evaluate(() => Object.assign(window.__observationProbe.scope, { patientId: 22, admissionId: "obs-admission-b" }));
  await page.getByRole("tab", { name: "观测窗", exact: true }).click(); await page.getByRole("textbox", { name: "观测窗开始", exact: true }).fill("2020-01-03T02:00:00Z"); state.release();
  await expect(page.getByRole("textbox", { name: "观测窗开始", exact: true })).toHaveValue("2020-01-03T02:00:00Z");
  expect(await page.evaluate(() => window.__observationProbe.events)).toEqual([]); noInference(state);
});

test("超管按患者住院过滤，核对冻结0和未知范围并按版本撤销，不触发推理", async ({ page }) => {
  const state = await session(page); await admin(page); const management = page.getByLabel("AI住院观测窗管理", { exact: true }); await management.getByRole("textbox", { name: "观测窗治理患者ID", exact: true }).fill("11"); await management.getByRole("textbox", { name: "观测窗治理原住院ID", exact: true }).fill(scopeA.admission_id); await management.getByRole("button", { name: "查询观测窗", exact: true }).click(); await expect.poll(() => state.reads.some(row => row.path === "/api/ai/admin/observation-windows" && row.query.patient_id === "11" && row.query.admission_id === scopeA.admission_id)).toBe(true); await management.getByRole("button", { name: "核对冻结观测窗", exact: true }).click();
  const dialog = page.getByRole("dialog", { name: "冻结住院观测窗审计", exact: true }); await expect(dialog).toContainText("本次原资料一致"); await expect(dialog.getByLabel("窗口冻结点测量", { exact: true })).toContainText("0 %"); await expect(dialog.getByLabel("窗口冻结分时尿量", { exact: true })).toContainText("0 mL；完整性 未知；患者总量 未知"); expect(state.reads.some(row => row.path === "/api/ai/admin/observation-windows/window-11")).toBe(true);
  await dialog.getByRole("textbox", { name: "治理观测窗撤销依据", exact: true }).fill("核对本窗口原住院观测后撤销冻结来源"); await dialog.getByRole("button", { name: "撤销此观测窗", exact: true }).click(); await expect.poll(() => state.writes.length).toBe(1); expect(state.writes[0]).toMatchObject({ path: "/api/ai/observation-windows/window-11/revoke", body: { expected_revision: 1, reason: "核对本窗口原住院观测后撤销冻结来源" } }); await expect(dialog).toContainText("已撤销"); noInference(state);
});

test("超管失去角色或更换会话后，迟到详情与管理目录不再展示", async ({ page }) => {
  const state = await session(page); await admin(page); const management = page.getByLabel("AI住院观测窗管理", { exact: true }); await expect(management.getByRole("button", { name: "核对冻结观测窗", exact: true })).toBeVisible(); state.delayed = (path, method) => method === "GET" && path.endsWith("/window-11"); await management.getByRole("button", { name: "核对冻结观测窗", exact: true }).click(); await expect.poll(() => !!state.release).toBe(true); await page.evaluate(() => window.__observationProbe.store.commit("user/permissions", ["admin"])); state.release(); await expect(management).toContainText("仅超级管理员"); await expect(page.getByRole("dialog", { name: "冻结住院观测窗审计", exact: true })).not.toBeVisible(); await expect(management).not.toContainText("window-11"); noInference(state);
});

test("超管也拒绝外层窗口匹配但内部冻结点测属于其他患者的响应", async ({ page }) => {
  const state = await session(page); state.wrongFrozen = true; await admin(page);
  await page.getByLabel("AI住院观测窗管理", { exact: true }).getByRole("button", { name: "核对冻结观测窗", exact: true }).click();
  const dialog = page.getByRole("dialog", { name: "冻结住院观测窗审计", exact: true }); await expect(dialog.getByRole("alert")).toContainText("不一致"); await expect(dialog.getByLabel("窗口冻结点测量", { exact: true })).toHaveCount(0); noInference(state);
});

test.afterEach(async () => { expect(harness.unhandled).toEqual([]); });
