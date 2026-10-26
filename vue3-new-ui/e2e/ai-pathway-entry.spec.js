const { selectManagementTab } = require('./fixtures/ai-management-navigation.cjs');
const { test, expect } = require("@playwright/test");

async function session(page, { role = "super_admin", stale = false } = {}) {
  const state = { reads: [], imports: [], reviews: [], previews: [], submissions: [], businessWrites: [], imported: stale, status: stale ? "retired" : "draft" };
  const rawSteps = '{"inclusion":"原纳入条件","exclusion":"原排除条件","steps":[{"value":0.123456789123456789,"content":"原路径步骤"}]}';
  const path = { pathway_id: 7, name: "院内测试路径", disease_code: "TEST", disease_name: "测试病种", steps: rawSteps, expected_days: 7, status: 0, status_text: "启用", source_revision: 3 };
  const features = [
    { key: "treatment_pathway", number: 5, name: "治疗路径推荐" },
    { key: "response_review", number: 8, name: "疗效复评助手" },
  ].map(item => ({ ...item, category: "cdss", priority: "P0", scope: "patient", engine: "llm", enabled: true, inputs: ["原路径与审核资料"], deliverables: ["方案、原记录及资料缺口"], default_roles: ["super_admin", "doctor", "director"], allowed_roles: ["super_admin", "doctor", "director"], validation_status: "unreviewed", source_reference_keys: ["pathway_id", "pathway_enrollment_id"], setup_check: { ready: false, issues: [] } }));
  const findings = { scope_note: "原计数和入径标记不证明疗效，当前模板不是历史冻结版本", selected_pathway_id: 7, current_templates: [{ source_id: "pathway-template:7", pathway_id: 7, exists_in_current_directory: true, name: path.name, disease_name: "测试病种", disease_code: "TEST", recorded_status: 0, expected_days: 7, explicitly_selected: true, reviewed_knowledge: { document_id: "path-doc", version: "v1" }, definition_note: "元数据不是治疗依据；按审核知识核对完整适用条件" }], enrollments: [{ source_id: "pathway-enrollment:9", enrollment_id: 9, pathway_id: 7, recorded_status: 2, recorded_status_meaning: "变异标记", explicitly_selected: true, encounter_assignment: "current_encounter", completed_items: null, total_items: 5, completion_rate: null, counter_state: "unknown", counter_note: "完成计数未完整记录，不能按0代入", enroll_date: "2026-10-20", variation_type: "原变异类型", variation_reason: "原变异说明 <img src=x onerror=alert(1)>", definition_note: "原入径日期不是治疗开始时间；没有逐项执行记录" }] };
  const evidence = [{ source_id: "pathway-enrollment:9", title: "原入径记录", content: "原完成计数未记录，总计数5，未推定实际执行或疗效" }, { source_id: "pathway-template:7", title: "当前模板元数据", content: "当前路径不是历史入径版本" }];
  const metadata = () => ({ document_id: "path-doc", title: "院内路径 #7：院内测试路径", version: "v1", content_hash: "b".repeat(64), status: state.status, source_kind: "clinical_pathway", source_reference_id: 7, source_state: stale ? "changed" : "current" });
  await page.addInitScript(() => localStorage.setItem("hoim-token", "isolated-pathway-test"));
  await page.route("**/api/**", async route => {
    const url = new URL(route.request().url()), requestPath = url.pathname, method = route.request().method(); state.reads.push(requestPath);
    let data = [];
    if (requestPath === "/api/userInfo") data = { username: "路径测试用户", permissions: role === "super_admin" ? ["super_admin", "admin"] : [role], avatar: "" };
    if (["/api/ai/features", "/api/ai/admin/features"].includes(requestPath)) data = features;
    if (requestPath === "/api/ai/admin/knowledge") data = state.imported ? [metadata()] : [];
    if (requestPath === "/api/ai/admin/knowledge/path-doc") data = { ...metadata(), content: "原路径审核全文：原纳入条件；原排除条件；完整原路径步骤。数字原文0.123456789123456789，保留原值。" };
    if (requestPath === "/api/ai/admin/pathway-sources") data = { items: [{ ...path, source_hash: "a".repeat(64), importable: true, issues: [] }, { pathway_id: 8, name: "空步骤模板", importable: false, issues: ["尚未整理步骤"] }], truncated: false };
    if (requestPath === "/api/ai/admin/pathway-sources/7/import") { state.imports.push(route.request().postDataJSON()); state.imported = true; data = metadata(); }
    if (requestPath === "/api/ai/admin/knowledge/path-doc/review") { const body = route.request().postDataJSON(); state.reviews.push(body); state.status = body.status; data = metadata(); }
    if (requestPath === "/api/ai/patients") data = [{ patient_id: 1, label: "测试患者 · #1" }];
    if (requestPath === "/api/ai/encounters") data = [{ encounter_ref: "path-admission", label: "本次测试住院", kind: "inpatient" }];
    if (requestPath === "/api/ai/pathway-options") data = { items: [{ pathway_id: 7, name: path.name, reviewed_for_current_scope: url.searchParams.get("encounter_ref") === "path-admission" }], scope_note: "选择就诊后重新核对本功能和科室的审核状态" };
    if (requestPath === "/api/ai/context") { state.previews.push(route.request().postDataJSON()); data = { context: { pathway_sources: findings, missing_data: ["缺少实际治疗起止时间"] }, evidence }; }
    if (requestPath === "/api/ai/runs" && method === "POST") { state.submissions.push(route.request().postDataJSON()); data = { run_id: "pathway-run", status: "queued", feature_name: "路径辅助", patient_id: 1 }; }
    if (requestPath === "/api/ai/runs/pathway-run") data = { run_id: "pathway-run", status: "succeeded", feature_name: "路径辅助", patient_id: 1, pathway_findings: findings, evidence, result: { summary: "隔离测试结果，待医生核实", sections: [], warnings: [], missing_data: ["缺少实际治疗起止时间"] } };
    if (requestPath === "/api/clinicalPathway/getList") data = [path];
    if (requestPath === "/api/pathwayEnrollment/getList") data = [{ enrollment_id: 9, pathway_id: 7, pathway_name: path.name, patient_id: 1, patient_name: "测试患者", admission_id: "path-admission", status: 2, status_text: "变异", completed_items: null, total_items: 5, counter_state: "unknown", completion_rate: null, counter_note: "计数不完整" }];
    if (method === "POST" && /^\/api\/(clinicalPathway|pathwayEnrollment)\//.test(requestPath)) { const body = route.request().postDataJSON(); state.businessWrites.push({ path: requestPath, body }); if (requestPath.endsWith("/update")) Object.assign(path, body); }
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ code: 200, msg: "success", data }) });
  });
  return { state, rawSteps };
}

test("超级管理员导入原路径快照后逐项查看全文，单独审核发布", async ({ page }) => {
  const { state } = await session(page);
  await page.goto("/#/ai/manage");
  await selectManagementTab(page, '知识审核');
  await page.getByRole("button", { name: "从临床路径导入", exact: true }).click();
  const dialog = page.getByRole("dialog", { name: "导入临床路径待审核快照", exact: true });
  await expect(dialog.getByRole("button", { name: "保存待审核快照", exact: true })).toBeDisabled();
  await dialog.getByRole("combobox", { name: "待导入临床路径", exact: true }).press("ArrowDown");
  await page.getByRole("option", { name: "院内测试路径 · #7", exact: true }).click();
  await dialog.getByRole("button", { name: "保存待审核快照", exact: true }).click();
  const review = page.getByRole("dialog", { name: "院内路径 #7：院内测试路径：知识审核", exact: true });
  await expect(review).toContainText("原排除条件");
  await expect(review).toContainText("0.123456789123456789");
  expect(state.imports).toEqual([{ expected_source_hash: "a".repeat(64), feature_keys: ["treatment_pathway", "response_review"] }]);
  expect(state.reviews).toEqual([]);
  await review.getByRole("button", { name: "确认审核并发布此版本", exact: true }).click();
  await expect.poll(() => state.reviews.length).toBe(1);
  expect(state.reviews[0]).toEqual({ status: "published", content_hash: "b".repeat(64) });
  expect(state.submissions).toEqual([]); expect(state.businessWrites).toEqual([]);
});

test("已停用且来源变更的路径版本不能在管理台重新发布", async ({ page }) => {
  const { state } = await session(page, { stale: true });
  await page.goto("/#/ai/manage");
  await selectManagementTab(page, '知识审核');
  await page.getByRole("button", { name: "查看与审核", exact: true }).click();
  const review = page.getByRole("dialog", { name: "院内路径 #7：院内测试路径：知识审核", exact: true });
  await expect(review).toContainText("须重新导入当前原路径后审核");
  await expect(review.getByRole("button", { name: "确认审核并发布此版本", exact: true })).toBeDisabled();
  expect(state.reviews).toEqual([]);
});

test("原入径行固定患者、住院和路径引用，未知计数不显示为0%，AI仅产生待复核结果", async ({ page }) => {
  const { state } = await session(page);
  await page.goto("/#/inpatient/opsExtension");
  await page.getByRole("tab", { name: "临床路径执行", exact: true }).click();
  await expect(page.getByText("进度未知", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "AI 路径复评", exact: true }).click();
  const drawer = page.getByRole("dialog", { name: "AI 原入径记录与疗效复评", exact: true });
  await expect(drawer.getByRole("combobox", { name: "患者", exact: true })).toBeDisabled();
  await expect(drawer.getByRole("combobox", { name: "本次就诊", exact: true })).toBeDisabled();
  await drawer.getByText("联调与预览选项", { exact: true }).click();
  await drawer.getByPlaceholder("可选：专用适配器的结构化输入 JSON，由服务契约规定", { exact: true }).fill('{"pathway_id":"999","pathway_enrollment_id":"999"}');
  await drawer.getByRole("button", { name: "查看本次资料", exact: true }).click();
  const preview = page.getByRole("dialog", { name: "本次提供给 AI 的患者资料", exact: true });
  const findings = preview.locator(".pathway-findings");
  await findings.getByText("入径 #9 · 变异标记 · 本次所选", { exact: true }).click();
  await expect(findings).toContainText("未记录 / 5；比例未知");
  await expect(findings.locator("img")).toHaveCount(0);
  await findings.getByRole("button", { name: "查看原入径记录依据", exact: true }).click();
  const source = page.getByRole("dialog", { name: "核查引用依据", exact: true });
  await expect(source).toContainText("未推定实际执行或疗效");
  await source.locator("button.el-dialog__headerbtn").click();
  await preview.locator("button.el-dialog__headerbtn").click();
  await drawer.getByRole("button", { name: "生成辅助建议", exact: true }).click();
  await expect.poll(() => state.submissions.length).toBe(1);
  expect(state.previews[0]).toMatchObject({ patient_id: 1, encounter_ref: "path-admission", source_refs: { pathway_id: "7", pathway_enrollment_id: "9" } });
  expect(state.submissions[0]).toMatchObject({ patient_id: 1, encounter_ref: "path-admission", input: { pathway_id: "7", pathway_enrollment_id: "9" } });
  await expect(drawer.getByLabel("AI任务结果", { exact: true }).locator(".pathway-findings")).toBeVisible();
  expect(state.businessWrites).toEqual([]);
});

test("工作台选择当前就诊的已审核路径，资料预览和提交使用同一选择", async ({ page }) => {
  const { state } = await session(page, { role: "doctor" });
  await page.goto("/#/ai/workbench");
  const encounter = page.getByRole("combobox", { name: "本次就诊", exact: true });
  await encounter.press("ArrowDown"); await page.getByRole("option", { name: "本次测试住院", exact: true }).click();
  const path = page.getByRole("combobox", { name: "待比选院内路径", exact: true });
  await expect(path).toBeEnabled(); await path.press("ArrowDown");
  await page.getByRole("option", { name: "院内测试路径 · #7", exact: true }).click();
  await page.getByRole("button", { name: "查看本次资料", exact: true }).click();
  const preview = page.getByRole("dialog", { name: "本次提供给 AI 的患者资料", exact: true });
  await expect(preview.locator(".pathway-findings")).toBeVisible();
  await preview.locator("button.el-dialog__headerbtn").click();
  await page.getByRole("button", { name: "生成辅助建议", exact: true }).click();
  await expect.poll(() => state.submissions.length).toBe(1);
  expect(state.previews[0].source_refs).toEqual({ pathway_id: "7" }); expect(state.submissions[0].input.pathway_id).toBe("7");
  expect(state.businessWrites).toEqual([]);
});

test("临床路径编辑保留原JSON精度，正确提交启停编码、路径主键和原版本", async ({ page }) => {
  const { state, rawSteps } = await session(page, { role: "doctor" });
  await page.goto("/#/doctor/clinicalPathway");
  await page.getByRole("button", { name: "编辑", exact: true }).click();
  const edit = page.getByRole("dialog", { name: "编辑临床路径", exact: true });
  await expect(edit.getByRole("radio", { name: "启用", exact: true })).toBeChecked();
  await expect(edit.getByRole("textbox", { name: "路径步骤JSON", exact: true })).toHaveValue(rawSteps);
  await edit.getByText("停用", { exact: true }).click();
  await edit.getByRole("button", { name: "确定", exact: true }).click();
  await expect.poll(() => state.businessWrites.length).toBe(1);
  expect(state.businessWrites[0]).toMatchObject({ path: "/api/clinicalPathway/update", body: { pathway_id: 7, steps: rawSteps, status: 1, expected_source_revision: 3 } });
  expect(state.businessWrites[0].body).not.toHaveProperty("id");
  await page.getByRole("button", { name: "删除", exact: true }).click();
  await page.getByRole("button", { name: "确定", exact: true }).click();
  await expect.poll(() => state.businessWrites.length).toBe(2);
  expect(state.businessWrites[1]).toEqual({ path: "/api/clinicalPathway/delete", body: { pathway_id: 7 } });
  expect(state.submissions).toEqual([]);
});
