const { test, expect } = require("@playwright/test");

async function setup(page, mode) {
  const incident = mode === "incident", ratings = mode === "ratings";
  const key = incident ? "incident_rca" : ratings ? "feedback_analysis" : "surgery_scheduling";
  const submissions = [], previews = [], businessWrites = [];
  const context = { scope: "department", source_domain: ratings ? "feedback" : "operations", since: "2026-10-01", until: "2026-10-20", snapshot_time: "2026-10-20T10:00:00+00:00", missing_data: [], truncated_sources: [], scope_note: "仅所选范围原记录，不代表完整事实核验" };
  const evidence = [];
  if (incident) {
    context.scope_note = "仅所选事件原记录，未按日期归属住院";
    context.incident_record = { source_id: "adverse-event:7", event_id: 7, recorded_event_type: "跌倒", recorded_severity: 2, recorded_status: 2, reported_description: "原上报陈述 <img src=x onerror=alert(1)>", report_time: null, definition_note: "上报时间不等于发生时间，闭环不等于根因核实" };
    context.incident_rca_records = [{ source_id: "incident-rca:8", rca_id: 8, recorded_root_cause_text: "原分析待证据核实", recorded_pdca_stage: "A", verification_status: "not_recorded", definition_note: "填写根因文本不证明因果关系" }];
    context.missing_data = ["独立核验和就诊归属未记录"];
    evidence.push({ source_id: "adverse-event:7", title: "原事件上报", content: "事件7的原上报陈述，核验状态未知" }, { source_id: "incident-rca:8", title: "已保存RCA分析", content: "已保存分析不是已核实根因" });
  } else if (ratings) {
    context.feedback_rating_summary = { source_id: "feedback:summary", record_count: 4, distinct_recorded_visit_count: 4, valid_score_record_count: 0, mean_recorded_score: null, withheld_comment_record_count: 3, out_of_range_score_record_count: 1, definition_note: "原评论未读取、未发送，均分不代表全体满意率" };
    context.feedback_rating_series = { source_id: "feedback:series", columns: ["date", "recorded_score", "record_count"], rows: [["2026-10-20", null, 4]], definition_note: "缺失和越界保持未知，不补零" };
    context.missing_data = ["无已审核脱敏原文，不能生成投诉主题"];
    evidence.push({ source_id: "feedback:summary", title: "评分汇总", content: "仅4行原评分，无全体就诊分母" });
  } else {
    context.surgical_schedules = { source_id: "surgery:schedule", columns: ["schedule_id", "recorded_start", "recorded_end"], rows: [["schedule-7", "2026-10-22T10:00:00", null]], planning_window: ["2026-10-21", "2026-10-25"], definition_note: "原起止不等同于已确认预约或切皮时刻" };
    context.surgical_recorded_overlaps = { source_id: "surgery:overlap", columns: ["left_schedule_id", "right_schedule_id", "shared_resource_references"], rows: [["schedule-7", "schedule-8", ["user:4"]]], checked_intervals: 2, uncheckable_or_inactive_schedules: 1, definition_note: "仅已记录区间交叠，无线索不代表可行" };
    context.missing_data = ["缺人员资质、可用性、设备和时长估计，不确认排台可行"];
    evidence.push({ source_id: "surgery:overlap", title: "原时间交叠", content: "排台7与8在原记录中共用user:4" });
  }
  await page.addInitScript(() => localStorage.setItem("hoim-token", "quality-resource-ai-test"));
  await page.route("**/api/**", async route => {
    const path = new URL(route.request().url()).pathname, method = route.request().method();
    let data = [];
    if (path === "/api/userInfo") data = { username: "测试管理员", permissions: ["admin"], avatar: "" };
    if (path === "/api/adverseEvent/getList") data = [{ event_id: 7, patient_id: 1, patient_name: "测试患者", event_type: "跌倒", status: 2 }, { event_id: 9, patient_id: null, event_type: "未关联事件", status: 0 }];
    if (path === "/api/ai/features") data = [{ key, number: incident ? 77 : ratings ? 70 : 65, name: incident ? "不良事件RCA助手" : ratings ? "投诉和满意度分析" : "手术排台优化", scope: incident ? "patient" : "hospital", engine: incident || ratings ? "llm" : "optimizer", enabled: true, inputs: ["所选原记录"], deliverables: ["事实与未知条件"], source_reference_keys: ["adverse_event_id"] }];
    if (path === "/api/ai/patients") data = [{ patient_id: 1, label: "测试患者 · #1" }];
    if (path === "/api/ai/service-options") data = { default_window: ["2026-10-01", "2026-10-20"], default_planning_window: ["2026-10-21", "2026-10-25"], allow_hospital_scope: true, departments: [{ department_id: 1, name: "所选科室" }] };
    if (["/api/ai/context", "/api/ai/operational-context"].includes(path)) { previews.push(route.request().postDataJSON()); data = { context, evidence }; }
    if (path === "/api/ai/runs" && method === "POST") { submissions.push(route.request().postDataJSON()); data = { run_id: "quality-resource-run", status: "queued", feature_name: "辅助分析" }; }
    if (path === "/api/ai/runs/quality-resource-run") data = { run_id: "quality-resource-run", status: "succeeded", feature_name: "辅助分析", result: { summary: "请核查来源与资料缺口", sections: [], warnings: [], missing_data: [] }, evidence, ...(incident ? { incident_findings: context } : { operational_findings: context }) };
    if (method === "POST" && /^\/api\/(surgery|surgeryApplication|surgerySchedule|adverseEvent|rca|analytics)\//.test(path)) businessWrites.push(path);
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ code: 200, msg: "success", data }) });
  });
  return { submissions, previews, businessWrites };
}

test("排台入口分别绑定历史及计划区间，独立展示缺失时间和原资源交叠", async ({ page }) => {
  const { submissions, previews, businessWrites } = await setup(page, "surgery");
  await page.goto("/#/inpatient/surgery");
  await page.getByRole("button", { name: "AI 排台分析", exact: true }).click();
  const drawer = page.getByRole("dialog", { name: "AI 手术排台资料与资源分析", exact: true });
  await expect(drawer.getByLabel("排台计划日期")).toBeVisible();
  await drawer.getByRole("button", { name: "查看本次运营资料", exact: true }).click();
  const preview = page.getByRole("dialog", { name: "本次提供给 AI 的运营资料", exact: true });
  await preview.getByText("计划区间排台原记录", { exact: true }).click();
  await expect(preview.getByRole("cell", { name: "未知", exact: true })).toBeVisible();
  await preview.getByText("原时间同资源交叠线索", { exact: true }).click();
  await expect(preview).toContainText("没有线索不代表排台可行");
  await preview.getByRole("button", { name: "查看原时间同资源交叠线索依据", exact: true }).click();
  const source = page.getByRole("dialog", { name: "核查引用依据", exact: true });
  await expect(source).toContainText("共用user:4");
  await source.locator("button.el-dialog__headerbtn").click();
  await preview.locator("button.el-dialog__headerbtn").click();
  await drawer.getByRole("button", { name: "生成辅助建议", exact: true }).click();
  await expect.poll(() => submissions.length).toBe(1);
  expect(previews[0].input).toEqual(submissions[0].input);
  expect(submissions[0].input).toMatchObject({ date_from: "2026-10-01", date_to: "2026-10-20", planning_date_from: "2026-10-21", planning_date_to: "2026-10-25" });
  expect(businessWrites).toEqual([]);
});

test("普通管理员不进入完整RCA来源，也不回退已替换的通用事件任务", async ({ page }) => {
  const { submissions, previews, businessWrites } = await setup(page, "incident");
  const aiCalls = [];
  page.on("request", request => { if (new URL(request.url()).pathname.startsWith("/api/ai/")) aiCalls.push(request.url()); });
  await page.goto("/#/system/adverseEvent");
  await expect(page.getByRole("cell", { name: "测试患者", exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "AI 事件复盘", exact: true })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "完整RCA来源与调查草稿", exact: true })).toHaveCount(0);
  await expect(page.getByRole("dialog", { name: "本事件完整RCA来源与调查草稿", exact: true })).toHaveCount(0);
  expect(aiCalls).toEqual([]);
  expect(submissions).toEqual([]);
  expect(previews).toEqual([]);
  expect(businessWrites).toEqual([]);
});

test("运营页旧评价配置要求完整原件模式，不创建通用评价任务", async ({ page }) => {
  const { submissions, previews, businessWrites } = await setup(page, "ratings");
  await page.goto("/#/report/operations");
  await page.getByRole("button", { name: "AI 评价证据分析", exact: true }).click();
  const drawer = page.getByRole("dialog", { name: "AI 完整评价证据分析", exact: true });
  await expect(drawer.getByText("请由超级管理员配置完整评价证据分析模式。", { exact: true })).toBeVisible();
  await expect(drawer.getByRole("button", { name: "生成辅助建议", exact: true })).toHaveCount(0);
  expect(submissions).toEqual([]);
  expect(previews).toEqual([]);
  expect(businessWrites).toEqual([]);
});
