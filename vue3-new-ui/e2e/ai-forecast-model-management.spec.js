const { test, expect } = require("@playwright/test");

const model = id => `stat-forecast:${String(id).repeat(64)}`;

async function session(page, { holdFirst = false, mismatch = "", matching = false } = {}) {
  const state = { checks: [], completed: [], writes: [], features: [], runs: [], release: null };
  const providers = [1, 2].map(id => ({ provider_id: id, revision: 3, name: `本地统计${id === 1 ? "甲" : "乙"}`, model: matching ? model(id) : "登记旧统计模型", kind: "specialist", api_base: "http://localhost:8813", enabled: false, allows_patient_data: false, timeout_seconds: 40, max_output_tokens: 2000, supported_features: ["visit_forecast"], has_api_key: true, validation_report: "仅合成界面测试，尚未验证实际运营预测效果" }));
  providers.push({ provider_id: 3, revision: 1, name: "普通文本服务", model: "text", kind: "chat", enabled: false, supported_features: ["visit_forecast"] });
  await page.addInitScript(() => localStorage.setItem("hoim-token", "isolated-forecast-admin-test"));
  await page.route("**/api/**", async route => {
    const request = route.request(), path = new URL(request.url()).pathname, method = request.method();
    let data = [], checked = null;
    if (path === "/api/userInfo") data = { username: "统计服务合成管理测试", permissions: ["super_admin", "admin"], avatar: "" };
    if (path === "/api/ai/admin/providers") data = providers;
    const match = path.match(/^\/api\/ai\/admin\/providers\/(\d+)\/forecast-capabilities$/);
    if (match) {
      const id = Number(match[1]); checked = id;
      state.checks.push({ id, method, ...request.postDataJSON() });
      if (holdFirst && id === 1) await new Promise(resolve => { state.release = resolve; });
      data = {
        provider_id: mismatch === "provider" ? 2 : id,
        provider_revision: mismatch === "revision" ? 4 : 3,
        configured_model: mismatch === "model" ? "另一保存版本" : providers[id - 1].model,
        compatible: matching,
        issues: matching ? [] : ["登记模型与实际统计运行版本不同", "<img src=x onerror=alert('不应执行')>"],
        scope_note: "仅能力声明核对，不发送日序列，不创建任务，不修改来源、启停或效果验证状态。",
        capabilities: { schema_version: "5", feature_key: "visit_forecast", model_version: model(id), engine: "stdlib-statistical-forecast", recipe: "weekday_mean_4w", recipe_digest: "b".repeat(64), runtime_digest: "c".repeat(64), python_version: "3.12.13", engine_versions: { fastapi: "0.136.1", pydantic: "2.12.4" }, history_min_days: 112, history_max_days: 366, horizon_days: [7, 14], backtest_origins: 28, nominal_coverage: 0.9, prompt_handling: "provenance_only", operational_validation: "not_provided", coverage_guarantee: "not_provided", max_request_bytes: 131072, timeout_seconds: 30 },
      };
    }
    if (method === "PUT" && /^\/api\/ai\/admin\/providers\/\d+$/.test(path)) { state.writes.push(request.postDataJSON()); data = {}; }
    if (method !== "GET" && /^\/api\/ai\/admin\/features\//.test(path)) state.features.push(request.postDataJSON());
    if (method === "POST" && path === "/api/ai/runs") state.runs.push(request.postDataJSON());
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ code: 200, msg: "success", data }) });
    if (checked !== null) state.completed.push(checked);
  });
  return state;
}

async function openCheck(page, name = "本地统计甲") {
  await page.getByRole("row").filter({ hasText: name }).getByRole("button", { name: "检查本地统计服务", exact: true }).click();
}

test("超管核对实际统计算法和范围后仅填入待保存模型，不升级效果验证", async ({ page }) => {
  const state = await session(page);
  await page.goto("/#/ai/manage"); await page.getByRole("tab", { name: "模型服务", exact: true }).click();
  await expect(page.getByRole("row").filter({ hasText: "普通文本服务" }).getByRole("button", { name: "检查本地统计服务", exact: true })).toHaveCount(0);
  await openCheck(page);
  const report = page.getByRole("dialog", { name: "本地统计预测服务核对", exact: true });
  for (const text of [model(1), "weekday_mean_4w", "112–366", "7 / 14", "28 个滚动起点", "90% 经验区间", "不保证未来覆盖", "Python 3.12.13", "fastapi 0.136.1", "not_provided", "不改变固定统计数值", "不是实际到诊人数", "不发送日序列", "不修改验证状态", "b".repeat(64), "c".repeat(64)]) await expect(report).toContainText(text);
  await expect(report).toContainText("<img src=x onerror=alert('不应执行')>"); await expect(report.locator("img")).toHaveCount(0);
  expect(state.checks).toEqual([{ id: 1, method: "POST", expected_revision: 3 }]);
  expect(state.writes).toEqual([]); expect(state.features).toEqual([]); expect(state.runs).toEqual([]);
  await report.getByRole("button", { name: "填写实际模型，待保存", exact: true }).click();
  const edit = page.getByRole("dialog", { name: "编辑模型服务", exact: true });
  await expect(edit.locator(".el-form-item").filter({ hasText: "模型标识" }).getByRole("textbox")).toHaveValue(model(1));
  await expect(edit.locator(".el-form-item").filter({ hasText: "适配器验证报告" }).getByRole("textbox")).toHaveValue("仅合成界面测试，尚未验证实际运营预测效果");
  expect(state.writes).toEqual([]);
  await edit.getByRole("button", { name: "保存服务", exact: true }).click();
  await expect.poll(() => state.writes.length).toBe(1);
  expect(state.writes[0]).toMatchObject({ model: model(1), expected_revision: 3, enabled: false, allows_patient_data: false, validation_report: "仅合成界面测试，尚未验证实际运营预测效果" });
  expect(state.features).toEqual([]); expect(state.runs).toEqual([]);
});

test("关闭旧统计检查后迟到回执不替换新服务或待保存模型", async ({ page }) => {
  const state = await session(page, { holdFirst: true });
  await page.goto("/#/ai/manage"); await page.getByRole("tab", { name: "模型服务", exact: true }).click();
  await openCheck(page); await expect.poll(() => !!state.release).toBe(true);
  await page.getByRole("dialog", { name: "本地统计预测服务核对", exact: true }).getByRole("button", { name: "关闭", exact: true }).click();
  await openCheck(page, "本地统计乙");
  const report = page.getByRole("dialog", { name: "本地统计预测服务核对", exact: true });
  await expect(report).toContainText(model(2)); state.release(); await expect.poll(() => state.completed.includes(1)).toBe(true);
  await expect(report).not.toContainText(model(1));
  await report.getByRole("button", { name: "填写实际模型，待保存", exact: true }).click();
  const edit = page.getByRole("dialog", { name: "编辑模型服务", exact: true });
  await expect(edit.locator(".el-form-item").filter({ hasText: "服务名称" }).getByRole("textbox")).toHaveValue("本地统计乙");
  await expect(edit.locator(".el-form-item").filter({ hasText: "模型标识" }).getByRole("textbox")).toHaveValue(model(2));
  expect(state.writes).toEqual([]); expect(state.features).toEqual([]); expect(state.runs).toEqual([]);
});

test("统计版本匹配仍保留未验证说明且不提供重复填表或业务启用", async ({ page }) => {
  const state = await session(page, { matching: true });
  await page.goto("/#/ai/manage"); await page.getByRole("tab", { name: "模型服务", exact: true }).click(); await openCheck(page);
  const report = page.getByRole("dialog", { name: "本地统计预测服务核对", exact: true });
  await expect(report).toContainText("服务声明与登记配置匹配；运营预测效果仍待验证");
  await expect(report).toContainText("not_provided：服务未提供独立运营效果验证");
  await expect(report.getByRole("button", { name: "填写实际模型，待保存", exact: true })).toHaveCount(0);
  expect(state.writes).toEqual([]); expect(state.features).toEqual([]); expect(state.runs).toEqual([]);
});

for (const mismatch of ["provider", "revision", "model"]) {
  test(`统计核对回执的${mismatch}不匹配时不允许填表`, async ({ page }) => {
    const state = await session(page, { mismatch });
    await page.goto("/#/ai/manage"); await page.getByRole("tab", { name: "模型服务", exact: true }).click(); await openCheck(page);
    await expect(page.getByText("核对回执与已保存统计服务配置不一致，请刷新后重试", { exact: true })).toBeVisible();
    await expect(page.getByRole("dialog", { name: "本地统计预测服务核对", exact: true }).getByRole("button", { name: "填写实际模型，待保存", exact: true })).toHaveCount(0);
    expect(state.writes).toEqual([]); expect(state.features).toEqual([]); expect(state.runs).toEqual([]);
  });
}

for (const changed of ["role", "session"]) {
  test(`统计核对途中${changed}改变后清理旧报告并拒绝迟到结果`, async ({ page }) => {
    const state = await session(page, { holdFirst: true });
    await page.goto("/#/ai/manage"); await page.getByRole("tab", { name: "模型服务", exact: true }).click(); await openCheck(page); await expect.poll(() => !!state.release).toBe(true);
    await page.evaluate(changed => {
      const store = document.querySelector("#hoim").__vue_app__.config.globalProperties.$store;
      if (changed === "role") store.commit("user/setPermissions", ["admin"]);
      else store.commit("user/setAccessToken", "new-isolated-statistics-session");
    }, changed);
    await expect(page.getByRole("dialog", { name: "本地统计预测服务核对", exact: true })).toBeHidden();
    state.release(); await expect.poll(() => state.completed.includes(1)).toBe(true);
    await expect(page.getByRole("dialog", { name: "编辑模型服务", exact: true })).toHaveCount(0);
    expect(state.writes).toEqual([]); expect(state.features).toEqual([]); expect(state.runs).toEqual([]);
  });
}
