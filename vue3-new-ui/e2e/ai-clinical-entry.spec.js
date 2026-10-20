const { test, expect } = require("@playwright/test");

test("从医生病历行打开AI时绑定原患者和病历，关闭后保留原业务", async ({ page }) => {
  const submissions = [];
  const previews = [];
  await page.addInitScript(() => localStorage.setItem("hoim-token", "inline-ai-test"));
  await page.route("**/api/**", async route => {
    const path = new URL(route.request().url()).pathname;
    let data = [];
    if (path === "/api/userInfo") data = { username: "测试医生", permissions: ["doctor"], avatar: "" };
    if (path === "/api/medicalRecord/getList") data = [{ uuid: "record-01", patient_id: 1, patient_name: "测试患者", symptom: "已记录的症状", result: "已记录的诊断", status: 0 }];
    if (path === "/api/ai/features") data = [{ key: "record_quality", number: 26, name: "病历语义质控", scope: "patient", engine: "llm", enabled: true, inputs: ["原始病历"], deliverables: ["问题定位"] }];
    if (path === "/api/ai/patients") data = [{ patient_id: 1, label: "测试患者 · #1" }];
    if (path === "/api/ai/context") { previews.push(Object.fromEntries(new URL(route.request().url()).searchParams)); data = { context: { selected_sources: { record_id: "record-01" } } }; }
    if (path === "/api/ai/runs" && route.request().method() === "POST") {
      submissions.push(route.request().postDataJSON());
      data = { run_id: "inline-run", feature_name: "病历语义质控", status: "queued", patient_id: 1 };
    }
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ code: 200, msg: "success", data }) });
  });
  await page.goto("/#/doctor/medicalRecord");
  await page.getByRole("button", { name: "AI 辅助", exact: true }).click();
  const drawer = page.getByRole("dialog");
  await expect(drawer).toContainText("AI 病历与诊疗辅助");
  await expect(drawer.getByRole("combobox", { name: "患者", exact: true })).toBeDisabled();
  await drawer.getByRole("button", { name: "查看本次资料", exact: true }).click();
  await expect.poll(() => previews.length).toBe(1);
  expect(previews[0].record_id).toBe("record-01");
  const preview = page.getByRole("dialog", { name: "本次提供给 AI 的患者资料", exact: true });
  await expect(preview).toBeVisible();
  await preview.locator("button.el-dialog__headerbtn").click();
  await expect(preview).not.toBeVisible();
  await drawer.getByRole("button", { name: "生成辅助建议", exact: true }).click();
  await expect.poll(() => submissions.length).toBe(1);
  expect(submissions[0].patient_id).toBe(1);
  expect(submissions[0].input.record_id).toBe("record-01");
  await page.keyboard.press("Escape");
  await expect(drawer).not.toBeVisible();
  await expect(page.getByRole("button", { name: "签名", exact: true })).toBeVisible();
});
