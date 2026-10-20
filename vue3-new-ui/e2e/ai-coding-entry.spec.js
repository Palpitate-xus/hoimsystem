const { test, expect } = require("@playwright/test");

test("病案编码辅助绑定所选首页并展示字典原始候选，生成不会绑定编码", async ({ page }) => {
  const submissions = [], previews = [], businessWrites = [];
  await page.addInitScript(() => localStorage.setItem("hoim-token", "coding-ai-test"));
  await page.route("**/api/**", async route => {
    const path = new URL(route.request().url()).pathname;
    const method = route.request().method();
    let data = [];
    if (path === "/api/userInfo") data = { username: "测试编码人员", permissions: ["doctor"], avatar: "" };
    if (path === "/api/homeIcd/uncoded") data = [{ home_id: "home-test", patient_id: 1, admission_id: "adm-test", patient_name: "测试患者", discharge_diagnosis: "测试已记录诊断", status_text: "已提交" }];
    if (path === "/api/homeIcd/statistics") data = { total_homes: 1, coded_homes: 0, coverage_rate: 0, top_primary_diagnosis: [] };
    if (path === "/api/ai/features") data = [{ key: "icd_candidates", number: 27, name: "编码候选辅助", scope: "patient", engine: "llm", enabled: true, inputs: ["病案首页"], deliverables: ["有效字典候选"], source_reference_keys: ["home_id"] }];
    if (path === "/api/ai/patients") data = [{ patient_id: 1, label: "测试患者 · #1" }];
    if (path === "/api/ai/encounters") data = [{ encounter_ref: "adm-test", label: "所选住院", kind: "inpatient" }];
    if (path === "/api/ai/context") { previews.push(route.request().postDataJSON()); data = { context: { medical_record_homes: [{ home_id: "home-test" }] } }; }
    if (path === "/api/ai/runs" && method === "POST") { submissions.push(route.request().postDataJSON()); data = { run_id: "coding-run", feature_name: "编码候选辅助", status: "queued", patient_id: 1 }; }
    if (path === "/api/ai/runs/coding-run") data = {
      run_id: "coding-run", feature_name: "编码候选辅助", status: "succeeded", patient_id: 1,
      result: { summary: "请编码人员核对原始条目", sections: [], warnings: [], missing_data: [] },
      tool_findings: { icd_candidates: { candidates: [{ kind: "diagnosis", code: "TEST.1", name: "院内字典原始名称", source_id: "icd:test" }], scope_note: "仅院内当前有效字典的文字匹配候选", truncated: false } },
      evidence: [{ source_id: "icd:test", title: "院内有效编码字典条目", content: "TEST.1 院内字典原始名称 状态：有效" }],
    };
    if (method === "POST" && path.startsWith("/api/homeIcd/")) businessWrites.push(path);
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ code: 200, msg: "success", data }) });
  });
  await page.goto("/#/inpatient/homeIcdWorkbench");
  await page.getByRole("button", { name: "AI 编码辅助", exact: true }).click();
  const drawer = page.getByRole("dialog", { name: "AI 字典候选与编码证据", exact: true });
  await drawer.getByRole("textbox", { name: "编码检索词", exact: true }).fill("测试已记录诊断");
  await drawer.getByRole("button", { name: "查看本次资料", exact: true }).click();
  const preview = page.getByRole("dialog", { name: "本次提供给 AI 的患者资料", exact: true });
  await expect(preview).toBeVisible();
  await preview.locator("button.el-dialog__headerbtn").click();
  await drawer.getByRole("button", { name: "生成辅助建议", exact: true }).click();
  await expect.poll(() => submissions.length).toBe(1);
  expect(previews[0].source_refs).toEqual({ home_id: "home-test" });
  expect(submissions[0]).toMatchObject({ patient_id: 1, encounter_ref: "adm-test", input: { home_id: "home-test", icd_query: "测试已记录诊断" } });
  await expect(drawer.getByRole("cell", { name: "TEST.1", exact: true })).toBeVisible();
  await drawer.getByRole("button", { name: "查看字典依据", exact: true }).click();
  const evidence = page.getByRole("dialog", { name: "核查引用依据", exact: true });
  await expect(evidence).toContainText("状态：有效");
  expect(businessWrites).toEqual([]);
});
