const { test, expect } = require("@playwright/test");

async function setupService(page, navigation) {
  const submissions = [], businessWrites = [];
  const feature = navigation ? { key: "hospital_navigation", number: 58, name: "院内办事与导航助手" } : { key: "appointment_assistant", number: 59, name: "预约办理助手" };
  await page.addInitScript(() => localStorage.setItem("hoim-token", "service-ai-test"));
  await page.route("**/api/**", async route => {
    const path = new URL(route.request().url()).pathname;
    const method = route.request().method();
    let data = [];
    if (path === "/api/userInfo") data = { username: "测试患者", permissions: ["patient"], avatar: "" };
    if (path === "/api/ai/features") data = [{ ...feature, scope: "input", engine: "llm", enabled: true, inputs: ["院内已配置资料"], deliverables: ["候选与依据"] }];
    if (path === "/api/ai/service-options") data = { departments: [{ department_id: 1, name: "测试预约科室" }], doctors: [{ doctor_id: 2, name: "测试预约医生", department_id: 1 }], navigation_nodes: [{ node_id: 11, name: "测试入口" }, { node_id: 12, name: "测试收费处" }], truncated: false };
    if (path === "/api/appointmentManagement/appointmentList") data = [{ id: 7, doctor_id: 2, department_id: 1, doctor: "测试预约医生", date: "2026-10-21", time: "02", stock: 10, specialist: 1 }];
    if (path === "/api/ai/runs" && method === "POST") { submissions.push(route.request().postDataJSON()); data = { run_id: "service-run", feature_name: feature.name, status: "queued" }; }
    if (path === "/api/ai/runs/service-run") data = {
      run_id: "service-run", feature_name: feature.name, status: "succeeded",
      result: { summary: "请核查原始院内资料", sections: [], warnings: [], missing_data: [] },
      tool_findings: navigation
        ? { hospital_navigation: { scope_note: "未配置开放时间及实时封路信息，需现场确认", route: { source_id: "route:test", nodes: [{ name: "测试入口" }, { name: "测试收费处" }], steps: [{ instruction: "沿院内已配置路线前行", distance: 12.5 }] }, hospital_faq: [], missing_data: [] } }
        : { appointment_candidates: { scope_note: "当前周期共享库存不等于按日期独立号源，候选不锁号", candidates: [{ source_id: "schedule:test", schedule_id: 7, doctor_name: "测试预约医生", department_name: "测试预约科室", appointment_date: "2026-10-21", recorded_period: "02", current_shared_stock: 10 }], window_start: "2026-10-21", window_end: "2026-10-21", missing_data: [], truncated: false } },
      evidence: [{ source_id: navigation ? "route:test" : "schedule:test", title: navigation ? "院内已配置节点与路线" : "当前排班与共享号源记录", content: navigation ? "原始路线方向：入口至收费处" : "排班7当前共享库存10，未锁号" }],
    };
    if (method !== "GET" && /^\/api\/(appointmentManagement|navigation)\//.test(path)) businessWrites.push(path);
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ code: 200, msg: "success", data }) });
  });
  return { submissions, businessWrites };
}

test("院内导航 AI 使用明确节点并展示原始路线与缺失信息", async ({ page }) => {
  const { submissions, businessWrites } = await setupService(page, true);
  await page.goto("/#/patient/navigation");
  await page.getByRole("button", { name: "AI 办事与导航", exact: true }).click();
  const drawer = page.getByRole("dialog", { name: "AI 院内办事与路线解释", exact: true });
  const start = drawer.getByRole("combobox", { name: "导航起点", exact: true }), end = drawer.getByRole("combobox", { name: "导航终点", exact: true });
  await start.press("ArrowDown");
  await page.locator(`#${await start.getAttribute("aria-controls")}`).getByRole("option", { name: "测试入口", exact: true }).click();
  await end.press("ArrowDown");
  await page.locator(`#${await end.getAttribute("aria-controls")}`).getByRole("option", { name: "测试收费处", exact: true }).click();
  await drawer.getByRole("button", { name: "生成辅助建议", exact: true }).click();
  await expect.poll(() => submissions.length).toBe(1);
  expect(submissions[0]).toMatchObject({ feature_key: "hospital_navigation", input: { start_node_id: 11, end_node_id: 12 } });
  expect(submissions[0].patient_id ?? null).toBeNull();
  await expect(drawer.getByText("测试入口 → 测试收费处", { exact: true })).toBeVisible();
  await expect(drawer.getByText(/未配置开放时间及实时封路信息/)).toBeVisible();
  await drawer.getByRole("button", { name: "查看路线依据", exact: true }).click();
  await expect(page.getByRole("dialog", { name: "核查引用依据", exact: true })).toContainText("原始路线方向");
  expect(businessWrites).toEqual([]);
});

test("所选号源 AI 说明绑定真实排班和日期，候选展示不会预约或扣库存", async ({ page }) => {
  const { submissions, businessWrites } = await setupService(page, false);
  await page.goto("/#/patient/appointment");
  await page.getByRole("button", { name: "预约挂号", exact: true }).click();
  await page.getByRole("button", { name: "AI 号源说明", exact: true }).click();
  const drawer = page.getByRole("dialog", { name: "AI 所选号源核对", exact: true });
  await expect(drawer.getByRole("combobox", { name: "预约医生", exact: true })).toBeDisabled();
  await drawer.getByRole("button", { name: "生成辅助建议", exact: true }).click();
  await expect.poll(() => submissions.length).toBe(1);
  expect(submissions[0]).toMatchObject({ feature_key: "appointment_assistant", input: { schedule_id: 7, doctor_id: 2, department_id: 1, appointment_date: "2026-10-21" } });
  expect(submissions[0].patient_id ?? null).toBeNull();
  await expect(drawer.getByRole("cell", { name: "10", exact: true })).toBeVisible();
  await expect(drawer.getByText(/候选不锁号/)).toBeVisible();
  await drawer.getByRole("button", { name: "查看号源依据", exact: true }).click();
  await expect(page.getByRole("dialog", { name: "核查引用依据", exact: true })).toContainText("未锁号");
  expect(businessWrites).toEqual([]);
});
