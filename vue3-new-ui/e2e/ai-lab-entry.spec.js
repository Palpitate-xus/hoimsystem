const { test, expect } = require("@playwright/test");

async function setupLab(page) {
  const calls = [];
  await page.addInitScript(() => localStorage.setItem("hoim-token", "lab-ai-test"));
  await page.route("**/api/**", async route => {
    const path = new URL(route.request().url()).pathname;
    let data = [];
    if (path === "/api/userInfo") data = { username: "测试技师", permissions: ["lab_technician"], avatar: "" };
    if (path === "/api/labResult/getPending") data = [{ id: "lab-order-test", patient_name: "测试患者", check_type: "测试项目", sample_status: 1 }];
    if (path === "/api/labResult/getList") data = [{ id: "reviewed-lab", patient_id: 1, check_name: "测试已审核项目", result: "原始文本", audit_status: 1, observations: [] }, { id: "pending-lab", patient_id: 1, check_name: "待审核项目", result: "原始待审文本", audit_status: 0, observations: [] }];
    if (path === "/api/ai/features") data = [{ key: "lab_interpretation", number: 31, name: "医生端检验解读", scope: "patient", engine: "llm", enabled: true, inputs: ["审核结果"], deliverables: ["结果事实"] }];
    if (path === "/api/ai/patients") data = [{ patient_id: 1, label: "测试患者 · #1" }];
    if (route.request().method() === "POST") {
      calls.push({ path, body: route.request().postDataJSON() });
      if (path === "/api/ai/runs") data = { run_id: "lab-run-test", feature_name: "医生端检验解读", status: "queued", patient_id: 1 };
    }
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ code: 200, msg: "success", data }) });
  });
  return calls;
}

test("检验录入保留数值字符串与单位并传递明确时区", async ({ page }) => {
  const calls = await setupLab(page);
  await page.goto("/#/lab/labResult");
  await page.getByRole("button", { name: "录入结果", exact: true }).click();
  const dialog = page.getByRole("dialog");
  await dialog.getByRole("button", { name: "添加检验指标" }).click();
  await dialog.getByPlaceholder("检验项目编码", { exact: true }).fill("TEST_K");
  await dialog.getByPlaceholder("检验项目名称", { exact: true }).fill("测试指标");
  await dialog.getByPlaceholder("原始检验数值").fill("1234567890123456.12345678");
  await dialog.getByPlaceholder("按报告原样填写").fill("mmol/L");
  await dialog.getByLabel("指标采样时间").fill("2026-10-20T10:15");
  await dialog.getByRole("button", { name: "确定", exact: true }).click();
  await expect.poll(() => calls.some(item => item.path === "/api/labResult/create")).toBe(true);
  const item = calls.find(item => item.path === "/api/labResult/create").body.observations[0];
  expect(item.value_num).toBe("1234567890123456.12345678");
  expect(item.unit).toBe("mmol/L");
  expect(item.flag).toBe("unknown");
  expect(item.collected_at).toMatch(/Z$/);
  expect(item._key).toBeUndefined();
  expect(item.value_kind).toBeUndefined();
});

test("已审核报告的 AI 入口绑定报告和患者，待审核报告不开放入口", async ({ page }) => {
  const calls = await setupLab(page);
  await page.goto("/#/lab/labResult");
  await page.getByRole("tab", { name: "检查结果", exact: true }).click();
  await expect(page.getByRole("button", { name: "AI 解读", exact: true })).toHaveCount(1);
  await page.getByRole("button", { name: "AI 解读", exact: true }).click();
  const drawer = page.getByRole("dialog");
  await expect(drawer.getByRole("combobox", { name: "患者", exact: true })).toBeDisabled();
  await drawer.getByRole("button", { name: "生成辅助建议", exact: true }).click();
  await expect.poll(() => calls.some(item => item.path === "/api/ai/runs")).toBe(true);
  const body = calls.find(item => item.path === "/api/ai/runs").body;
  expect(body.patient_id).toBe(1);
  expect(body.input.lab_result_id).toBe("reviewed-lab");
});
