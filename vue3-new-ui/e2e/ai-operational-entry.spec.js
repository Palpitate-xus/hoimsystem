const { test, expect } = require("@playwright/test");

async function setup(page, inventory) {
  const previews = [], submissions = [], businessWrites = [];
  const key = inventory ? "inventory_optimization" : "operations_qa";
  const context = {
    scope: inventory ? "hospital" : "department", source_domain: inventory ? "inventory" : "operations", department_ids: inventory ? null : [1], since: "2026-10-01", until: "2026-10-20", truncated_sources: [],
    scope_note: "原始业务资料有范围和口径，未知值不补零", missing_data: [inventory ? "未取得已验证需求预测，不编造采购量" : "全院日统计未按科室拆分，使用所属科室原始汇总"],
  };
  if (inventory) context.supply_inventory = {
    source_id: "stock:source", scope_note: "药品目录未记录库存计数单位，不补写成盒或片", batch_note: "批次及目录库存可能不一致", drugs: [{ drug_id: 5, name: "测试库存品种", catalog_stock: 8, all_batch_stock_sum: 7, stock_count_unit: null, catalog_matches_batch_sum: false }], consumables: [],
    drug_ledger_daily: { definition_note: "原出库数量与库存差额符号分别保留" }, consumable_trace_daily: { definition_note: "追溯记录不是完整库存变更账" }, purchase_note: "实收未知不按计划数量代入",
  };
  else context.ward_capacity = { source_id: "bed:source", definition_note: "空闲状态计数不等于已确认可收治名额", wards: [{ ward_id: 1, name: "测试病区", configured_bed_count: 99, loaded_bed_record_count: 2, recorded_free_beds_in_active_ward: 1, configured_count_matches_loaded: false }] };
  const evidence = [{ source_id: inventory ? "stock:source" : "bed:source", title: inventory ? "所选品种库存原记录" : "当前病区与床位状态", content: inventory ? "药品5：目录8，批次7，单位未记录" : "配置99，加载2，原空闲状态1" }];
  await page.addInitScript(() => localStorage.setItem("hoim-token", "operational-ai-test"));
  await page.route("**/api/**", async route => {
    const path = new URL(route.request().url()).pathname;
    const method = route.request().method();
    let data = [];
    if (path === "/api/userInfo") data = { username: "测试运营用户", permissions: [inventory ? "pharmacist" : "admin"], avatar: "" };
    if (path === "/api/pharmaceuticalManagement/lowStock") data = [{ id: 5, name: "测试库存品种", stock: 8, threshold: 10 }];
    if (path === "/api/ai/features") data = [{ key, number: inventory ? 67 : 61, name: inventory ? "临期积压与采购分析" : "医院数据问答", scope: "hospital", engine: inventory ? "optimizer" : "llm", enabled: true, inputs: ["授权原始业务资料"], deliverables: ["口径和差异核实"] }];
    if (path === "/api/ai/service-options") data = { default_window: ["2026-10-01", "2026-10-20"], departments: [{ department_id: 1, name: "测试运营科室" }], allow_hospital_scope: !inventory, inventory_scope_available: true, inventory_drugs: [{ item_id: 5, name: "测试库存品种" }], inventory_consumables: [], truncated: false };
    if (path === "/api/ai/operational-context") { previews.push(route.request().postDataJSON()); data = { context, evidence }; }
    if (path === "/api/ai/runs" && method === "POST") { submissions.push(route.request().postDataJSON()); data = { run_id: "operational-test-run", feature_name: "运营辅助", status: "queued" }; }
    if (path === "/api/ai/runs/operational-test-run") data = { run_id: "operational-test-run", feature_name: "运营辅助", status: "succeeded", result: { summary: "请复核原始数据差异", sections: [], warnings: [], missing_data: [] }, operational_findings: context, evidence };
    if (method === "POST" && /^\/api\/(analytics|pharmaceuticalManagement|purchase|ward|bed)\//.test(path)) businessWrites.push(path);
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ code: 200, msg: "success", data }) });
  });
  return { previews, submissions, businessWrites };
}

test("运营分析预览与提交使用同一日期科室，床位差异来自原始资料", async ({ page }) => {
  const { previews, submissions, businessWrites } = await setup(page, false);
  await page.goto("/#/report/operations");
  await page.getByRole("button", { name: "AI 运营分析", exact: true }).click();
  const drawer = page.getByRole("dialog", { name: "AI 运营事实与预测辅助", exact: true });
  await drawer.getByRole("combobox", { name: "运营科室范围", exact: true }).press("ArrowDown");
  await page.getByRole("option", { name: "测试运营科室", exact: true }).click();
  await drawer.getByRole("button", { name: "查看本次运营资料", exact: true }).click();
  const preview = page.getByRole("dialog", { name: "本次提供给 AI 的运营资料", exact: true });
  await expect(preview.getByRole("cell", { name: "不一致，待核实", exact: true })).toBeVisible();
  await expect(preview).toContainText("不等于已确认可收治名额");
  await preview.getByRole("button", { name: "查看床位状态依据", exact: true }).click();
  const source = page.getByRole("dialog", { name: "核查引用依据", exact: true });
  await expect(source).toContainText("配置99，加载2");
  await source.locator("button.el-dialog__headerbtn").click();
  await preview.locator("button.el-dialog__headerbtn").click();
  await drawer.getByRole("button", { name: "生成辅助建议", exact: true }).click();
  await expect.poll(() => submissions.length).toBe(1);
  expect(previews[0].input).toEqual(submissions[0].input);
  expect(submissions[0].input).toMatchObject({ date_from: "2026-10-01", date_to: "2026-10-20", department_id: 1 });
  await expect(drawer.getByRole("cell", { name: "不一致，待核实", exact: true })).toBeVisible();
  expect(businessWrites).toEqual([]);
});

test("库存行分析绑定明确药品，原始库存与未知单位独立展示且不生成采购单", async ({ page }) => {
  const { previews, submissions, businessWrites } = await setup(page, true);
  await page.goto("/#/pharmacy/stockAlert");
  await page.getByRole("button", { name: "AI 品种分析", exact: true }).click();
  const drawer = page.getByRole("dialog", { name: "AI 所选药品库存分析", exact: true });
  await drawer.getByRole("button", { name: "查看本次运营资料", exact: true }).click();
  const preview = page.getByRole("dialog", { name: "本次提供给 AI 的运营资料", exact: true });
  await expect(preview.getByRole("cell", { name: "未记录", exact: true })).toBeVisible();
  await expect(preview).toContainText("不编造采购量");
  await preview.locator("button.el-dialog__headerbtn").click();
  await drawer.getByRole("button", { name: "生成辅助建议", exact: true }).click();
  await expect.poll(() => submissions.length).toBe(1);
  expect(previews[0].input).toEqual(submissions[0].input);
  expect(submissions[0].input.drug_ids).toEqual([5]);
  expect(submissions[0].input.department_id).toBeUndefined();
  await expect(drawer.getByRole("cell", { name: "不一致，待核实", exact: true })).toBeVisible();
  await drawer.getByRole("button", { name: "查看库存与原始流水依据", exact: true }).click();
  await expect(page.getByRole("dialog", { name: "核查引用依据", exact: true })).toContainText("目录8，批次7");
  expect(businessWrites).toEqual([]);
});
