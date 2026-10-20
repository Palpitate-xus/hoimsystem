const { test, expect } = require("@playwright/test");

async function setupWorkbench(page, fail = false, options = {}) {
  const calls = [];
  const feature = { key: "patient_summary", number: 1, name: "患者全景摘要", scope: "patient", engine: "llm", enabled: true, inputs: ["就诊记录", "过敏信息"], deliverables: ["当前问题", "资料缺口"] };
  const run = { run_id: "ui-isolated-task", feature_key: feature.key, feature_name: feature.name, status: "queued", patient_id: 1, preview: 0, prompt_version: 0, provider_revision: 1, input_tokens: 20, output_tokens: 30 };
  await page.addInitScript(() => localStorage.setItem("hoim-token", "ui-test-token"));
  await page.route("**/api/**", async route => {
    const path = new URL(route.request().url()).pathname;
    let data = [];
    if (path === "/api/userInfo") data = { username: "测试医生", permissions: ["doctor"], avatar: "" };
    if (path === "/api/ai/features") data = [feature];
    if (path === "/api/ai/patients") data = options.patients || [{ patient_id: 1, label: "测试患者 · #1" }];
    if (path === "/api/ai/encounters") data = [{ encounter_ref: "test-encounter", label: "门诊 · 测试就诊" }];
    if (path === "/api/ai/runs" && route.request().method() === "POST") {
      calls.push({ kind: "submission", body: route.request().postDataJSON() });
      if (options.submissionGate) await options.submissionGate;
      if (fail) { await route.fulfill({ status: 409, contentType: "application/json", body: JSON.stringify({ detail: "未检索到本任务可用的已审核知识" }) }); return; }
      data = run;
    }
    if (path === "/api/ai/runs/ui-isolated-task") data = {
      ...run, status: "succeeded",
      result: { summary: "已整理提供的测试资料", sections: [{ title: "记录事实", content: "<img src=x onerror=alert(1)> 这是待复核的原文。", source_ids: ["record-test"] }], warnings: ["测试资料存在待确认项目"], missing_data: ["当前诊断尚待确认"] },
      evidence: [{ source_id: "record-test", kind: "patient_record", title: "已审核测试记录", content: "原始记录：仅用于界面测试。", observed_at: "2026-10-20T00:00:00" }],
    };
    if (path.endsWith("/feedback")) { calls.push({ kind: "feedback", body: route.request().postDataJSON() }); data = { feedback_id: "test-review" }; }
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ code: 200, msg: "success", data }) });
  });
  return calls;
}

test("医生提交授权患者任务并核查引用和记录复核反馈", async ({ page }) => {
  const calls = await setupWorkbench(page);
  await page.goto("/#/ai/workbench");
  await expect(page.locator("form").getByText("测试患者 · #1", { exact: true })).toBeVisible();
  await page.getByPlaceholder(/请提供与患者全景摘要相关的信息/).fill("整理本次就诊资料，列出需要核实的问题");
  await page.getByRole("button", { name: "生成辅助建议", exact: true }).click();
  await expect(page.getByText("已整理提供的测试资料", { exact: true })).toBeVisible();
  expect(calls[0].body.patient_id).toBe(1);
  expect(calls[0].body.preview).toBe(false);
  await expect(page.locator('img[src="x"]')).toHaveCount(0);
  await expect(page.getByText("<img src=x onerror=alert(1)> 这是待复核的原文。", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "查看依据：已审核测试记录" }).click();
  await expect(page.getByRole("dialog")).toContainText("原始记录：仅用于界面测试。");
  await page.getByRole("dialog").locator("button.el-dialog__headerbtn").click();
  await page.getByRole("button", { name: "记录复核反馈", exact: true }).click();
  await page.getByPlaceholder(/说明核查结果或修改内容/).fill("已核对引用来源，保留待核实项目");
  await page.getByRole("button", { name: "保存反馈", exact: true }).click();
  await expect.poll(() => calls.some(item => item.kind === "feedback")).toBe(true);
});

test("任务准备失败显示服务端原因且不重复提交", async ({ page }) => {
  const calls = await setupWorkbench(page, true);
  await page.goto("/#/ai/workbench");
  await expect(page.locator("form").getByText("测试患者 · #1", { exact: true })).toBeVisible();
  await page.getByPlaceholder(/请提供与患者全景摘要相关的信息/).fill("整理当前资料");
  await page.getByRole("button", { name: "生成辅助建议", exact: true }).click();
  await expect(page.locator(".el-message--error")).toContainText("未检索到本任务可用的已审核知识");
  expect(calls.filter(item => item.kind === "submission")).toHaveLength(1);
});

test("切换患者后历史按当前病例查询，迟到的旧病例响应不会覆盖新列表", async ({ page }) => {
  const requests = [], fulfilled = [];
  let releaseFirst;
  const firstGate = new Promise(resolve => { releaseFirst = resolve; });
  await page.addInitScript(() => localStorage.setItem("hoim-token", "history-test"));
  await page.route("**/api/**", async route => {
    const url = new URL(route.request().url());
    const path = url.pathname;
    let data = [];
    if (path === "/api/userInfo") data = { username: "测试医生", permissions: ["doctor"], avatar: "" };
    if (path === "/api/ai/features") data = [{ key: "patient_summary", number: 1, name: "患者全景摘要", scope: "patient", enabled: true, engine: "llm", inputs: ["患者记录"], deliverables: ["摘要"] }];
    if (path === "/api/ai/patients") data = [{ patient_id: 1, label: "病例甲 · #1" }, { patient_id: 2, label: "病例乙 · #2" }];
    if (path === "/api/ai/runs") {
      requests.push(Object.fromEntries(url.searchParams));
      const patient = url.searchParams.get("patient_id");
      if (patient === "1") await firstGate;
      data = [{ run_id: "history-" + patient, feature_name: patient === "1" ? "病例甲旧任务" : "病例乙当前任务", patient_id: Number(patient), status: "succeeded" }];
      fulfilled.push(patient);
    }
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ code: 200, msg: "success", data }) });
  });
  await page.goto("/#/ai/workbench");
  const patient = page.getByRole("combobox", { name: "患者", exact: true });
  await patient.press("ArrowDown");
  await page.getByRole("option", { name: "病例甲 · #1", exact: true }).click();
  await page.getByText("最近任务", { exact: true }).click();
  await expect.poll(() => requests.some(row => row.patient_id === "1")).toBe(true);
  await patient.press("ArrowDown");
  await page.getByRole("option", { name: "病例乙 · #2", exact: true }).click();
  await expect(page.getByRole("cell", { name: "病例乙当前任务", exact: true })).toBeVisible();
  releaseFirst();
  await expect.poll(() => fulfilled.includes("1")).toBe(true);
  await expect(page.getByRole("cell", { name: "病例甲旧任务", exact: true })).toHaveCount(0);
  expect(requests.every(row => row.feature_key === "patient_summary" && ["1", "2"].includes(row.patient_id))).toBe(true);
});

test("提交后切换患者，迟到的任务回执不会挂到新病例或开始轮询", async ({ page }) => {
  let release;
  const submissionGate = new Promise(resolve => { release = resolve; });
  const calls = await setupWorkbench(page, false, { submissionGate, patients: [{ patient_id: 1, label: "提交病例甲" }, { patient_id: 2, label: "切换病例乙" }] });
  await page.goto("/#/ai/workbench");
  const patient = page.getByRole("combobox", { name: "患者", exact: true });
  await patient.press("ArrowDown");
  await page.getByRole("option", { name: "提交病例甲", exact: true }).click();
  const generate = page.getByRole("button", { name: "生成辅助建议", exact: true });
  await generate.click();
  await expect.poll(() => calls.some(item => item.kind === "submission")).toBe(true);
  await patient.press("ArrowDown");
  await page.getByRole("option", { name: "切换病例乙", exact: true }).click();
  const receipt = page.waitForResponse(response => response.url().endsWith("/api/ai/runs") && response.request().method() === "POST");
  release();
  await receipt;
  await expect(generate).toBeEnabled();
  await expect(page.locator('[aria-label="AI任务结果"]')).toHaveCount(0);
  expect(calls.find(item => item.kind === "submission").body.patient_id).toBe(1);
});
