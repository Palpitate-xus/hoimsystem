const { test, expect } = require("@playwright/test");

const leads = ["I", "II", "III", "aVR", "aVL", "aVF", "V1", "V2", "V3", "V4", "V5", "V6"];
const model = id => `ssl-ecg:${String(id).repeat(64)}`;

async function session(page, { holdFirst = false, wrongTarget = false, configuredMatching = false } = {}) {
  const state = { checks: [], completed: [], writes: [], featureWrites: [], runs: [], release: null };
  const providers = [1, 2].map(id => ({ provider_id: id, revision: 3, name: `本地心电${id === 1 ? "甲" : "乙"}`, model: configuredMatching ? model(id) : "登记的旧模型", kind: "specialist", api_base: "http://localhost:8820", enabled: false, allows_patient_data: false, timeout_seconds: 30, max_output_tokens: 2000, supported_features: ["ecg_analysis"], has_api_key: true, validation_report: "隔离界面测试，未进行临床质量验证" }));
  providers.push({ provider_id: 3, revision: 1, name: "普通文本服务", model: "text-only", kind: "chat", api_base: "http://localhost:8820", enabled: false, supported_features: ["ecg_analysis"] });
  await page.addInitScript(() => localStorage.setItem("hoim-token", "isolated-ecg-admin-test"));
  await page.route("**/api/**", async route => {
    const request = route.request(), path = new URL(request.url()).pathname, method = request.method();
    let data = [], checkedId = null;
    if (path === "/api/userInfo") data = { username: "心电管理测试", permissions: ["super_admin", "admin"], avatar: "" };
    if (path === "/api/ai/admin/providers") data = providers;
    const match = path.match(/^\/api\/ai\/admin\/providers\/(\d+)\/ecg-capabilities$/);
    if (match) {
      const id = Number(match[1]); checkedId = id;
      state.checks.push({ id, method, ...request.postDataJSON() });
      if (id === 1 && holdFirst) await new Promise(resolve => { state.release = resolve; });
      data = {
        provider_id: wrongTarget ? 2 : id, provider_revision: 3, configured_model: providers[id - 1].model,
        compatible: configuredMatching, issues: configuredMatching ? [] : ["登记模型与服务实际版本不同", "<img src=x onerror=alert('不应执行')>"],
        scope_note: "仅配置匹配检查，不发送患者资料、不执行识别，不证明医疗质量或完成临床验证。",
        capabilities: {
          schema_version: 3, feature_key: "ecg_analysis", model_version: model(id), engine: "ssl-ecg-cnn",
          engine_versions: { torch: "2.10.0", numpy: "2.4.4", safetensors: "0.7.0" },
          model_repository: "Tumo505/SSL-ECG-Classification-model-card", model_revision: "a".repeat(40),
          model_digest: "b".repeat(64), runtime_digest: "c".repeat(64), preprocessing_digest: "d".repeat(64),
          required_leads: leads, sample_rate_hz: 100, samples_per_lead: 1000,
          labels: ["NORM", "CD", "HYP", "MI", "STTC"], missing_sample_policy: "reject", prompt_handling: "signal_only",
          max_bytes: 33554432, timeout_seconds: 110, clinical_validation: "not_provided",
        },
      };
    }
    if (method === "PUT" && /^\/api\/ai\/admin\/providers\/\d+$/.test(path)) { state.writes.push(request.postDataJSON()); data = {}; }
    if (method !== "GET" && /^\/api\/ai\/admin\/features\//.test(path)) state.featureWrites.push(request.postDataJSON());
    if (method === "POST" && path === "/api/ai/runs") state.runs.push(request.postDataJSON());
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ code: 200, msg: "success", data }) });
    if (checkedId !== null) state.completed.push(checkedId);
  });
  return state;
}

async function openCheck(page, name) {
  await page.getByRole("row").filter({ hasText: name }).getByRole("button", { name: "检查本地心电服务", exact: true }).click();
}

test("超管核对心电原始信号能力和版本后只填待保存表单，不自动启用或推理", async ({ page }) => {
  const state = await session(page);
  await page.goto("/#/ai/manage"); await page.getByRole("tab", { name: "模型服务", exact: true }).click();
  await expect(page.getByRole("row").filter({ hasText: "普通文本服务" }).getByRole("button", { name: "检查本地心电服务", exact: true })).toHaveCount(0);
  await openCheck(page, "本地心电甲");
  const report = page.getByRole("dialog", { name: "本地心电服务核对", exact: true });
  await expect(report).toContainText(model(1));
  await expect(report).toContainText("Tumo505/SSL-ECG-Classification-model-card");
  await expect(report).toContainText(leads.join("、"));
  await expect(report).toContainText("100 Hz；每导联 1000 个样本，10 秒");
  await expect(report).toContainText("NORM、CD、HYP、MI、STTC");
  await expect(report).toContainText("reject（拒绝含缺失样本的输入）");
  await expect(report).toContainText("signal_only：仅对真实信号分类");
  await expect(report).toContainText("不能补造缺失导联、波形或临床信息");
  await expect(report).toContainText("not_provided（未提供临床验证）");
  await expect(report).toContainText("<img src=x onerror=alert('不应执行')>");
  await expect(report.locator("img")).toHaveCount(0);
  expect(state.checks).toEqual([{ id: 1, method: "POST", expected_revision: 3 }]);
  expect(state.writes).toEqual([]); expect(state.featureWrites).toEqual([]); expect(state.runs).toEqual([]);
  await report.getByRole("button", { name: "填写实际模型，待保存", exact: true }).click();
  const edit = page.getByRole("dialog", { name: "编辑模型服务", exact: true });
  await expect(edit.locator(".el-form-item").filter({ hasText: "模型标识" }).getByRole("textbox")).toHaveValue(model(1));
  await expect(edit.locator(".el-form-item").filter({ hasText: "超时秒数" }).getByRole("spinbutton")).toHaveValue("120");
  await expect(edit.locator(".el-form-item").filter({ hasText: "适配器验证报告" }).getByRole("textbox")).toHaveValue("隔离界面测试，未进行临床质量验证");
  expect(state.writes).toEqual([]);
  await edit.getByRole("button", { name: "保存服务", exact: true }).click();
  await expect.poll(() => state.writes.length).toBe(1);
  expect(state.writes[0]).toMatchObject({ model: model(1), expected_revision: 3, enabled: false, allows_patient_data: false, validation_report: "隔离界面测试，未进行临床质量验证" });
  expect(state.featureWrites).toEqual([]); expect(state.runs).toEqual([]);
});

test("关闭旧心电服务检查后迟到回执不能填入另一个服务", async ({ page }) => {
  const state = await session(page, { holdFirst: true });
  await page.goto("/#/ai/manage"); await page.getByRole("tab", { name: "模型服务", exact: true }).click();
  await openCheck(page, "本地心电甲"); await expect.poll(() => !!state.release).toBe(true);
  let report = page.getByRole("dialog", { name: "本地心电服务核对", exact: true });
  await report.getByRole("button", { name: "关闭", exact: true }).click();
  await openCheck(page, "本地心电乙");
  report = page.getByRole("dialog", { name: "本地心电服务核对", exact: true });
  await expect(report).toContainText(model(2));
  state.release(); await expect.poll(() => state.completed.includes(1)).toBe(true);
  await expect(report).not.toContainText(model(1));
  await report.getByRole("button", { name: "填写实际模型，待保存", exact: true }).click();
  const edit = page.getByRole("dialog", { name: "编辑模型服务", exact: true });
  await expect(edit.locator(".el-form-item").filter({ hasText: "服务名称" }).getByRole("textbox")).toHaveValue("本地心电乙");
  await expect(edit.locator(".el-form-item").filter({ hasText: "模型标识" }).getByRole("textbox")).toHaveValue(model(2));
  expect(state.writes).toEqual([]); expect(state.featureWrites).toEqual([]); expect(state.runs).toEqual([]);
});

test("心电服务回执的服务身份不匹配时不能用于填写配置", async ({ page }) => {
  const state = await session(page, { wrongTarget: true });
  await page.goto("/#/ai/manage"); await page.getByRole("tab", { name: "模型服务", exact: true }).click();
  await openCheck(page, "本地心电甲"); await expect.poll(() => state.completed.includes(1)).toBe(true);
  await expect(page.getByText("服务核对回执与已保存配置不一致，请刷新后重新检查", { exact: true })).toBeVisible();
  const report = page.getByRole("dialog", { name: "本地心电服务核对", exact: true });
  await expect(report.getByRole("button", { name: "填写实际模型，待保存", exact: true })).toHaveCount(0);
  expect(state.writes).toEqual([]); expect(state.featureWrites).toEqual([]); expect(state.runs).toEqual([]);
});

test("心电模型标识匹配只说明配置一致，保留未临床验证提示且不改配置", async ({ page }) => {
  const state = await session(page, { configuredMatching: true });
  await page.goto("/#/ai/manage"); await page.getByRole("tab", { name: "模型服务", exact: true }).click();
  await openCheck(page, "本地心电甲");
  const report = page.getByRole("dialog", { name: "本地心电服务核对", exact: true });
  await expect(report).toContainText("服务声明与登记配置匹配；临床质量仍待验证");
  await expect(report).toContainText("未提供临床验证");
  await expect(report.getByRole("button", { name: "填写实际模型，待保存", exact: true })).toHaveCount(0);
  expect(state.writes).toEqual([]); expect(state.featureWrites).toEqual([]); expect(state.runs).toEqual([]);
});
