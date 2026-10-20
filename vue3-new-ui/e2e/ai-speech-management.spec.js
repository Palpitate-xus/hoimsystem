const { test, expect } = require("@playwright/test");

async function session(page, { holdFirst = false } = {}) {
  const state = { checks: [], writes: [], runs: [], release: null };
  const providers = [1, 2].map(id => ({ provider_id: id, revision: 3, name: `本地语音${id === 1 ? '甲' : '乙'}`, model: "登记的旧模型", kind: "specialist", api_base: "http://localhost:8810", enabled: false, allows_patient_data: false, timeout_seconds: 30, max_output_tokens: 2000, supported_features: ["medical_transcription"], has_api_key: true, validation_report: "隔离界面测试，未进行临床质量验证" }));
  await page.addInitScript(() => localStorage.setItem("hoim-token", "isolated-speech-admin-test"));
  await page.route("**/api/**", async route => {
    const request = route.request(), path = new URL(request.url()).pathname, method = request.method();
    let data = [];
    if (path === "/api/userInfo") data = { username: "语音管理测试", permissions: ["super_admin", "admin"], avatar: "" };
    if (path === "/api/ai/admin/providers") data = providers;
    const match = path.match(/^\/api\/ai\/admin\/providers\/(\d+)\/speech-capabilities$/);
    if (match) {
      const id = Number(match[1]); state.checks.push({ id, ...request.postDataJSON() });
      if (id === 1 && holdFirst) await new Promise(resolve => { state.release = resolve; });
      const model = `fw:${String(id).repeat(64)}`;
      data = { provider_id: id, provider_revision: 3, configured_model: providers[id - 1].model, compatible: false, issues: ["登记模型与服务实际版本不同"], scope_note: "仅配置匹配检查，不发送患者资料、不执行识别，不证明医疗质量或完成临床验证。", capabilities: { model_version: model, model_repository: "example/public-model", model_revision: "a".repeat(40), language: "zh", max_bytes: 67108864, max_duration_seconds: 300, timeout_seconds: 110, clinical_validation: "not_provided" } };
    }
    if (method === "PUT" && /^\/api\/ai\/admin\/providers\/\d+$/.test(path)) { state.writes.push(request.postDataJSON()); data = {}; }
    if (method === "POST" && path === "/api/ai/runs") state.runs.push(request.postDataJSON());
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ code: 200, msg: "success", data }) });
  });
  return state;
}

async function check(page, name) {
  await page.getByRole("row").filter({ hasText: name }).getByRole("button", { name: "检查本地语音服务", exact: true }).click();
}

test("超级管理员核对实际语音模型后只填入待保存表单，不自动启用或推理", async ({ page }) => {
  const state = await session(page);
  await page.goto("/#/ai/manage"); await page.getByRole("tab", { name: "模型服务", exact: true }).click();
  await check(page, "本地语音甲");
  const report = page.getByRole("dialog", { name: "本地语音服务核对", exact: true });
  await expect(report).toContainText(`fw:${"1".repeat(64)}`);
  await expect(report).toContainText("最长 300 秒");
  await expect(report).toContainText("不证明医疗质量或完成临床验证");
  expect(state.checks).toEqual([{ id: 1, expected_revision: 3 }]); expect(state.writes).toEqual([]); expect(state.runs).toEqual([]);
  await report.getByRole("button", { name: "填写实际模型，待保存", exact: true }).click();
  const edit = page.getByRole("dialog", { name: "编辑模型服务", exact: true });
  await expect(edit.locator(".el-form-item").filter({ hasText: "模型标识" }).getByRole("textbox")).toHaveValue(`fw:${"1".repeat(64)}`);
  await expect(edit.locator(".el-form-item").filter({ hasText: "超时秒数" }).getByRole("spinbutton")).toHaveValue("120");
  expect(state.writes).toEqual([]);
  await edit.getByRole("button", { name: "保存服务", exact: true }).click();
  await expect.poll(() => state.writes.length).toBe(1);
  expect(state.writes[0]).toMatchObject({ model: `fw:${"1".repeat(64)}`, expected_revision: 3, enabled: false, allows_patient_data: false });
  expect(state.runs).toEqual([]);
});

test("关闭旧服务检查后迟到回执不覆盖新服务的实际模型", async ({ page }) => {
  const state = await session(page, { holdFirst: true });
  await page.goto("/#/ai/manage"); await page.getByRole("tab", { name: "模型服务", exact: true }).click();
  await check(page, "本地语音甲");
  await expect.poll(() => !!state.release).toBe(true);
  let report = page.getByRole("dialog", { name: "本地语音服务核对", exact: true });
  await report.getByRole("button", { name: "关闭", exact: true }).click();
  await check(page, "本地语音乙");
  report = page.getByRole("dialog", { name: "本地语音服务核对", exact: true });
  await expect(report).toContainText(`fw:${"2".repeat(64)}`);
  state.release();
  await expect.poll(() => state.checks.length).toBe(2);
  await expect(report).not.toContainText(`fw:${"1".repeat(64)}`);
  await report.getByRole("button", { name: "填写实际模型，待保存", exact: true }).click();
  const edit = page.getByRole("dialog", { name: "编辑模型服务", exact: true });
  await expect(edit.locator(".el-form-item").filter({ hasText: "服务名称" }).getByRole("textbox")).toHaveValue("本地语音乙");
  expect(state.writes).toEqual([]); expect(state.runs).toEqual([]);
});
