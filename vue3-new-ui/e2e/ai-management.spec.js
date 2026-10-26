const { selectManagementTab } = require('./fixtures/ai-management-navigation.cjs');
const { test, expect } = require("@playwright/test");

async function managementSession(page, role = "super_admin") {
  const calls = [];
  const features = Array.from({ length: 80 }, (_, index) => ({
    number: index + 1, key: index === 4 ? "treatment_pathway" : `feature_${index + 1}`,
    name: index === 4 ? "治疗路径推荐" : `测试能力 ${index + 1}`, category: "cdss", priority: "P0",
    engine: "llm", scope: "patient", inputs: ["确认诊断", "审核指南"], deliverables: ["候选方案", "证据出处"],
    default_roles: ["super_admin", "doctor"], allowed_roles: ["super_admin", "doctor"],
    enabled: false, validation_status: "unreviewed", validation_note: "", prompt_version: 0, active_prompt_id: null,
    revision: 0, provider_id: null, daily_limit: 100,
    setup_check: { ready: false, issues: [{ code: "MODEL_UNASSIGNED", message: "尚未选择模型服务" }], scope_note: "实际执行仍按患者、科室、问题和资料范围重新核验。" },
  }));
  await page.addInitScript(() => localStorage.setItem("hoim-token", "isolated-ui-test-token"));
  await page.route("**/api/**", async route => {
    const path = new URL(route.request().url()).pathname;
    const method = route.request().method();
    if (path.startsWith("/api/ai/admin")) calls.push({ path, method, body: route.request().postDataJSON() });
    let data = [];
    if (path === "/api/userInfo") data = { username: "UI测试用户", permissions: role === "super_admin" ? ["super_admin", "admin"] : [role], avatar: "" };
    if (path === "/api/ai/admin/features") data = features;
    if (path === "/api/ai/admin/runs") data = [{ run_id: "history-test", feature_key: "patient_summary", feature_name: "患者全景摘要", requested_by: 42, patient_id: 1, status: "succeeded", input_tokens: 12, output_tokens: 20, feedback_count: 1 }];
    if (path === "/api/ai/admin/runs/history-test") data = {
      run_id: "history-test", feature_key: "patient_summary", feature_name: "患者全景摘要", requested_by: 42, patient_id: 1, status: "succeeded", prompt_version: 0, provider_revision: 1,
      snapshot_complete: true, result: { summary: "已留存的测试结果", sections: [], warnings: [], missing_data: [] },
      frozen_request: { system_prompt: "冻结的原始系统 Prompt", task_prompt: "冻结的原始任务 Prompt", provider_snapshot: { model: "original-requested-model-v1", api_base: "http://localhost:11434/v1" }, feature_validation: { note: "当时的隔离验证说明" }, payload: { input: { question: "原始测试问题" } } },
      feedback: [{ reviewer_id: 42, outcome: "rejected", comment: "<img src=x onerror=alert(1)> 测试复核意见" }],
    };
    if (path === "/api/ai/admin/prompts/treatment_pathway") data = {
      system_prompt: "固定系统契约：仅使用授权资料，不增补事实。",
      versions: [{ prompt_id: null, version: 0, change_note: "默认版本", task_prompt: "治疗路径推荐任务：根据审核后的指南和确认诊断整理候选方案，展示适用条件和证据。" }],
    };
    if (method === "POST" && path === "/api/ai/admin/prompts/treatment_pathway") {
      features[4].revision += 1;
      data = { prompt_id: "prompt-test-1", version: 1, revision: features[4].revision };
    }
    if (method === "PUT" && path === "/api/ai/admin/features/treatment_pathway") {
      Object.assign(features[4], route.request().postDataJSON(), { revision: features[4].revision + 1 });
      data = features[4];
    }
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ code: 200, msg: "success", data }) });
  });
  return calls;
}

test("超级管理员查看80项能力并保存独立Prompt版本", async ({ page }) => {
  const calls = await managementSession(page);
  await page.goto("/#/ai/manage");
  await expect(page.getByText("规划能力", { exact: true })).toBeVisible();
  await expect(page.locator(".summary-value").first()).toHaveText("80");
  await page.getByPlaceholder("搜索名称或功能编号").fill("治疗路径推荐");
  await expect(page.locator(".el-table__body-wrapper tr").filter({ hasText: "治疗路径推荐" })).toHaveCount(1);
  await page.getByRole("button", { name: "Prompt", exact: true }).click();
  const dialog = page.getByRole("dialog");
  await expect(dialog).toContainText("治疗路径推荐：Prompt 版本");
  await dialog.locator("textarea").fill("治疗路径推荐任务：基于真实指南和本次确认诊断整理首选与备选路径，逐项给出证据出处。补充适用条件和复评信息。");
  await dialog.getByPlaceholder("说明本次修改目的和适用范围").fill("增加复评信息和证据要求");
  await dialog.getByRole("button", { name: "保存为新版本" }).click();
  await expect.poll(() => calls.some(call => call.method === "POST" && call.path.endsWith("/prompts/treatment_pathway"))).toBe(true);
  const submitted = calls.find(call => call.method === "POST" && call.path.endsWith("/prompts/treatment_pathway")).body;
  expect(submitted.expected_revision).toBe(0);
  expect(submitted.task_prompt).toContain("复评信息");
  expect(submitted).not.toHaveProperty("system_prompt");
});

test("配置面板按能力限制角色并提交版本号", async ({ page }) => {
  const calls = await managementSession(page);
  await page.goto("/#/ai/manage");
  await page.getByPlaceholder("搜索名称或功能编号").fill("治疗路径推荐");
  await page.getByRole("button", { name: "配置", exact: true }).click();
  const dialog = page.getByRole("dialog");
  await expect(dialog.getByRole("checkbox", { name: "医生", exact: true })).toBeChecked();
  await expect(dialog.getByRole("checkbox", { name: "患者", exact: true })).toHaveCount(0);
  await dialog.getByRole("button", { name: "保存配置" }).click();
  await expect(dialog).not.toBeVisible();
  const submitted = calls.find(call => call.method === "PUT").body;
  expect(submitted.allowed_roles).toEqual(["super_admin", "doctor"]);
  expect(submitted.expected_revision).toBe(0);
  expect(submitted.enabled).toBe(false);
});

test("普通管理员直接访问管理地址也不会加载AI管理接口", async ({ page }) => {
  const calls = await managementSession(page, "admin");
  await page.goto("/#/ai/manage");
  await expect(page).toHaveURL(/#\/404/);
  await expect(page.getByText("AI 管理中心", { exact: true })).toHaveCount(0);
  expect(calls).toHaveLength(0);
});

test("超级管理员逐项查看未就绪原因而无需发起模型请求", async ({ page }) => {
  const calls = await managementSession(page);
  await page.goto("/#/ai/manage");
  await page.getByPlaceholder("搜索名称或功能编号").fill("治疗路径推荐");
  await page.getByRole("button", { name: "治疗路径推荐配置检查", exact: true }).click();
  await expect(page.getByText("尚未选择模型服务", { exact: true })).toBeVisible();
  await expect(page.getByText("实际执行仍按患者、科室、问题和资料范围重新核验。", { exact: true })).toBeVisible();
  expect(calls.every(call => call.method === "GET")).toBe(true);
});

test("超级管理员追查任务当时的Prompt模型和原始反馈，反馈文本按纯文本展示", async ({ page }) => {
  await managementSession(page);
  await page.goto("/#/ai/manage");
  await selectManagementTab(page, '任务与反馈');
  await page.getByRole("button", { name: "执行溯源", exact: true }).click();
  const dialog = page.getByRole("dialog", { name: "AI 任务执行溯源", exact: true });
  await expect(dialog).toContainText("已留存的测试结果");
  await dialog.getByRole("tab", { name: "调用时 Prompt", exact: true }).click();
  await expect(dialog.getByText("冻结的原始系统 Prompt", { exact: true })).toBeVisible();
  await dialog.getByRole("tab", { name: "模型与验证快照", exact: true }).click();
  await expect(dialog.getByText("original-requested-model-v1", { exact: true })).toBeVisible();
  await dialog.getByRole("tab", { name: "人工反馈", exact: true }).click();
  await expect(dialog.getByText("<img src=x onerror=alert(1)> 测试复核意见", { exact: true })).toBeVisible();
  await expect(dialog.locator('img[src="x"]')).toHaveCount(0);
});
