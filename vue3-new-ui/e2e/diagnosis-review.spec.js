const { test, expect } = require("@playwright/test");

test("诊断复核要求明确勾选确认范围，并保存医生检查过的原文版本", async ({ page }) => {
  const writes = [];
  await page.addInitScript(() => localStorage.setItem("hoim-token", "diagnosis-review-test"));
  await page.route("**/api/**", async route => {
    const path = new URL(route.request().url()).pathname;
    let data = [];
    if (path === "/api/userInfo") data = { username: "责任医生", permissions: ["doctor"], avatar: "" };
    if (path === "/api/medicalRecord/getList") data = [{ uuid: "diagnosis-source-test", patient_id: 1, patient_name: "测试患者", symptom: "已记录症状", result: "医生已核实的诊断原文", status: 1 }];
    if (path === "/api/clinicalDiagnosis/review" && route.request().method() === "GET") data = { source_kind: "outpatient", source_id: "diagnosis-source-test", source_hash: "a".repeat(64), diagnosis_text: "医生已核实的诊断原文", signed: true, certainty: "unknown", revision: 0, history: [] };
    if (path === "/api/clinicalDiagnosis/review" && route.request().method() === "POST") writes.push({ path, body: route.request().postDataJSON() });
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ code: 200, msg: "success", data }) });
  });
  await page.goto("/#/doctor/medicalRecord");
  await page.getByRole("button", { name: "诊断复核", exact: true }).click();
  const dialog = page.getByRole("dialog", { name: "责任医生诊断复核", exact: true });
  await expect(dialog).toContainText("医生已核实的诊断原文");
  await dialog.getByRole("combobox", { name: "本次复核状态", exact: true }).press("ArrowDown");
  await page.getByRole("option", { name: "已明确", exact: true }).click();
  await dialog.getByPlaceholder("记录核实依据、仍待确认的信息或状态变化原因").fill("已逐项核实诊断资料，确认当前记录内容");
  await expect(dialog.getByRole("button", { name: "记录复核", exact: true })).toBeDisabled();
  await dialog.getByText("我已逐项核对上述诊断字段，确认其中全部诊断均已明确", { exact: true }).click();
  await expect(dialog.getByRole("checkbox")).toBeChecked();
  await dialog.getByRole("button", { name: "记录复核", exact: true }).click();
  await expect.poll(() => writes.length).toBe(1);
  expect(writes[0].path).toBe("/api/clinicalDiagnosis/review");
  expect(writes[0].body).toMatchObject({ source_kind: "outpatient", source_id: "diagnosis-source-test", source_hash: "a".repeat(64), expected_revision: 0, certainty: "confirmed" });
  await expect(dialog).not.toBeVisible();
});
