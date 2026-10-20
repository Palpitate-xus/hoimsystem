const { test, expect } = require("@playwright/test");

test("排台行的AI分析绑定住院手术和排台，资料预览与生成使用同一引用", async ({ page }) => {
  const submissions = [], previews = [], businessWrites = [];
  await page.addInitScript(() => localStorage.setItem("hoim-token", "operative-ai-test"));
  await page.route("**/api/**", async route => {
    const path = new URL(route.request().url()).pathname;
    const method = route.request().method();
    let data = [];
    if (path === "/api/userInfo") data = { username: "测试手术医生", permissions: ["doctor"], avatar: "" };
    if (path === "/api/surgeryApplication/getList") data = [{ application_id: "app-test", admission_id: "adm-test", patient_id: 1, surgery_name: "测试手术", status: 2 }];
    if (path === "/api/surgerySchedule/getList") data = [{ schedule_id: "schedule-test", application_id: "app-test", admission_id: "adm-test", patient_id: 1, surgery_name: "测试手术", status: 2 }];
    if (path === "/api/surgery/perioperative/list") data = [{ perioperative_id: "med-test", application_id: "app-test", admission_id: "adm-test", patient_id: 1, status: 1 }];
    if (path === "/api/ai/features") data = [{ key: "perioperative_antibiotics", number: 49, name: "围术期抗菌药分析", scope: "patient", engine: "llm", enabled: true, inputs: ["实际记录时间"], deliverables: ["原有规则结果"], source_reference_keys: ["surgery_application_id", "surgery_schedule_id", "perioperative_id"] }];
    if (path === "/api/ai/patients") data = [{ patient_id: 1, label: "测试患者 · #1" }];
    if (path === "/api/ai/encounters") data = [{ encounter_ref: "adm-test", label: "所选住院", kind: "inpatient" }];
    if (path === "/api/ai/context") { const body = route.request().postDataJSON(); previews.push(body); data = { context: { selected_sources: body.source_refs } }; }
    if (path === "/api/ai/runs" && method === "POST") { submissions.push(route.request().postDataJSON()); data = { run_id: "operative-run", feature_name: "围术期抗菌药分析", status: "queued", patient_id: 1 }; }
    if (method === "POST" && /^\/api\/(surgery|surgeryApplication|surgerySchedule)/.test(path)) businessWrites.push(path);
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ code: 200, msg: "success", data }) });
  });
  await page.goto("/#/inpatient/surgery");
  await page.getByRole("button", { name: "AI 时机分析", exact: true }).click();
  const drawer = page.getByRole("dialog", { name: "AI 围术期时机分析", exact: true });
  await expect(drawer.getByRole("combobox", { name: "患者", exact: true })).toBeDisabled();
  await drawer.getByRole("button", { name: "查看本次资料", exact: true }).click();
  const preview = page.getByRole("dialog", { name: "本次提供给 AI 的患者资料", exact: true });
  await expect(preview).toBeVisible();
  await preview.locator("button.el-dialog__headerbtn").click();
  await expect(preview).not.toBeVisible();
  await drawer.getByRole("button", { name: "生成辅助建议", exact: true }).click();
  await expect.poll(() => submissions.length).toBe(1);
  expect(previews[0].source_refs).toEqual({ surgery_application_id: "app-test", surgery_schedule_id: "schedule-test" });
  expect(submissions[0].input.surgery_schedule_id).toBe("schedule-test");
  expect(submissions[0].patient_id).toBe(1);
  expect(submissions[0].encounter_ref).toBe("adm-test");
  expect(businessWrites).toEqual([]);
});
