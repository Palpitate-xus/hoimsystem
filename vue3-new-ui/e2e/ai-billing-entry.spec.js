const { test, expect } = require("@playwright/test");

test("住院费用 AI 核对绑定当前住院并展示原始账目提示，不触发结算或退费", async ({ page }) => {
  const submissions = [], businessWrites = [];
  await page.addInitScript(() => localStorage.setItem("hoim-token", "billing-ai-test"));
  await page.route("**/api/**", async route => {
    const path = new URL(route.request().url()).pathname;
    const method = route.request().method();
    let data = [];
    if (path === "/api/userInfo") data = { username: "测试费用管理人员", permissions: ["admin"], avatar: "" };
    if (path === "/api/admission/getInpatientList") data = [{ admission_id: "adm-bill", patient_id: 1, patient_name: "测试费用患者", bed_no: "01" }];
    if (path === "/api/inpatientCharge/getList") data = [{ charge_id: "charge-test", item_name: "测试已退费项目", status: 2, status_text: "已退费", total_amount: "10.00" }];
    if (path === "/api/inpatientCharge/getDailyBill") data = { total_amount: 0, deposit_amount: 0, balance: 0, unsettled_amount: 0, daily_list: [] };
    if (path === "/api/ai/features") data = [{ key: "charge_reconciliation", number: 69, name: "收费与漏记账核对", scope: "patient", engine: "llm", enabled: true, inputs: ["账目", "执行"], deliverables: ["待核实事项"], source_reference_keys: ["inpatient_charge_id"] }];
    if (path === "/api/ai/patients") data = [{ patient_id: 1, label: "测试费用患者 · #1" }];
    if (path === "/api/ai/encounters") data = [{ encounter_ref: "adm-bill", label: "当前费用住院", kind: "inpatient" }];
    if (path === "/api/ai/runs" && method === "POST") { submissions.push(route.request().postDataJSON()); data = { run_id: "billing-run", feature_name: "收费核对", status: "queued", patient_id: 1 }; }
    if (path === "/api/ai/runs/billing-run") data = {
      run_id: "billing-run", feature_name: "收费核对", status: "succeeded", patient_id: 1,
      result: { summary: "请核对保存状态", sections: [], warnings: [], missing_data: [] },
      tool_findings: { billing_reconciliation: { scope_note: "原始账目核对不能直接认定漏收费", checks: [{ charge_id: "charge-test", item_name: "测试已退费项目", charge_status: 2, quantity: "1", unit_price: "10.00", stored_amount: "10.00", findings: ["已记录退费，不列为补费候选"], source_ids: ["charge:test"] }], executed_without_charge_link: [], truncated_sources: [] } },
      evidence: [{ source_id: "charge:test", title: "住院原始收费记录", content: "原始状态：2，保存金额：10.00" }],
    };
    if (method === "POST" && path.startsWith("/api/inpatientCharge/")) businessWrites.push(path);
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ code: 200, msg: "success", data }) });
  });
  await page.goto("/#/inpatient/inpatientCharge");
  await page.getByRole("cell", { name: "测试费用患者", exact: true }).click();
  await page.getByRole("button", { name: "AI 收费核对", exact: true }).click();
  const drawer = page.getByRole("dialog", { name: "AI 住院账目与执行核对", exact: true });
  await expect(drawer.getByRole("combobox", { name: "患者", exact: true })).toBeDisabled();
  await drawer.getByRole("button", { name: "生成辅助建议", exact: true }).click();
  await expect.poll(() => submissions.length).toBe(1);
  expect(submissions[0]).toMatchObject({ patient_id: 1, encounter_ref: "adm-bill", feature_key: "charge_reconciliation" });
  await expect(drawer.getByText("已记录退费，不列为补费候选", { exact: true })).toBeVisible();
  await drawer.getByRole("button", { name: "住院原始收费记录", exact: true }).click();
  await expect(page.getByRole("dialog", { name: "核查引用依据", exact: true })).toContainText("原始状态：2");
  expect(businessWrites).toEqual([]);
});
