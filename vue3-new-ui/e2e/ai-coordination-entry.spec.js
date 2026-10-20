const { test, expect } = require("@playwright/test");

async function session(page, mode, role = mode === "adr" ? "super_admin" : "doctor") {
  const adr = mode === "adr", key = adr ? "adr_signal" : "referral_mdt", referenceKey = adr ? "reaction_id" : mode === "mdt" ? "mdt_id" : "referral_id", reference = adr ? "9" : mode === "mdt" ? "7" : "8";
  const state = { previews: [], submissions: [], businessWrites: [], reads: [], resolution: null };
  const sourceId = adr ? "adr:9" : mode === "mdt" ? "mdt:7" : "referral:8";
  const context = { missing_data: ["记录未注明对应就诊，不按日期推定归属"], selected_sources: { [referenceKey]: reference } };
  if (adr) context.adr_sources = { scope_note: "不良反应与过敏分别核查，不自动修改过敏史", reports: [{ source_id: sourceId, reaction_id: 9, pharmaceutical_id: 5, pharmaceutical_name: "原上报药品", drug_reference_resolved: true, reported_symptom: "上报症状 <img src=x onerror=alert(1)>", recorded_severity: 99, report_time: "2026-10-20T10:00:00", recorded_state: "legacy_ambiguous", status_text: "历史含义待核实", status_resolution: null, definition_note: "原状态2曾用于处理或排除，含义未核实保持未知", onset_and_exposure_note: "上报时间不是起病时间，因果关系尚未核实" }] };
  else context.consultation_sources = { scope_note: "初步诊断不升级为本次确认诊断，审批通过不等于实际接诊", referrals: mode === "referral" ? [{ source_id: sourceId, referral_id: 8, recorded_status: 1, recorded_status_meaning: "审批通过/接收标记", recorded_type: "legacy-unknown", from_department: { department_id: 1, name: "原转出科室", exists_in_current_directory: true }, to_department: { department_id: 99999, name: null, exists_in_current_directory: false }, recorded_reason: "原记录需要专科评估", reviewed_at: "2026-10-20T10:00:00", definition_note: "审批标记不能证明已到达或完成接诊" }] : [], mdt_cases: mode === "mdt" ? [{ source_id: sourceId, mdt_id: 7, recorded_status: 3, recorded_status_meaning: "已退回", recorded_diagnosis: "原初步诊断 <img src=x onerror=alert(1)>", participating_departments: [{ department_id: 1, name: "原参与科室", exists_in_current_directory: true }], unparsed_department_tokens: 1, recorded_result: "退回病例中的原结果文本", result_on_completed_case: false, definition_note: "未完成或退回病例中的结果不作最终意见" }] : [] };
  const evidence = [{ source_id: sourceId, title: adr ? "ADR原记录" : mode === "mdt" ? "MDT原记录" : "转诊原记录", content: adr ? "状态2含义未知，未提供起病与给药时间" : mode === "mdt" ? "原病例已退回，结果文本尚不能作为最终意见" : "原审批通过标记，无实际接诊记录" }];
  await page.addInitScript(() => localStorage.setItem("hoim-token", "clinical-coordination-test"));
  await page.route("**/api/**", async route => {
    const path = new URL(route.request().url()).pathname, method = route.request().method(); state.reads.push(path);
    let data = [];
    if (path === "/api/userInfo") data = { username: "测试协作用户", permissions: role === "super_admin" ? ["super_admin", "admin"] : [role], avatar: "" };
    if (path === "/api/mdt/getList") data = [{ mdt_id: 7, patient_id: 1, patient_name: "测试患者", diagnosis: "原初步诊断", status: 3, status_text: "已退回", department_names: ["原参与科室"], result: "原结果文本" }];
    if (path === "/api/referral/getList") data = [{ referral_id: 8, patient_id: 1, patient_name: "测试患者", status: 1, status_text: "已接收" }];
    if (path === "/api/adverseReaction/getList") data = [{ reaction_id: 9, patient_id: 1, patient_name: "测试患者", pharmaceutical_name: "原上报药品", symptom: "原症状", status: 2, status_resolution: state.resolution, recorded_state: state.resolution || "legacy_ambiguous", status_text: state.resolution === "excluded" ? "已记录排除ADR" : state.resolution ? "已处理" : "历史含义待核实" }];
    if (path === "/api/ai/features") data = [{ key, number: adr ? 19 : 9, name: adr ? "不良反应信号发现" : "转诊与MDT助手", scope: "patient", engine: adr ? "prediction" : "llm", enabled: true, inputs: ["原记录及明确资料"], deliverables: ["事实、信号和缺口"], source_reference_keys: ["mdt_id", "referral_id", "reaction_id"] }];
    if (path === "/api/ai/patients") data = [{ patient_id: 1, label: "测试患者 · #1" }];
    if (path === "/api/ai/encounters") data = [{ encounter_ref: "current-encounter", label: "当前临床背景" }];
    if (path === "/api/ai/context") { state.previews.push(route.request().postDataJSON()); data = { context, evidence }; }
    if (path === "/api/ai/runs" && method === "POST") { state.submissions.push(route.request().postDataJSON()); data = { run_id: "coordination-run", feature_name: "协作辅助", status: "queued", patient_id: 1 }; }
    if (path === "/api/ai/runs/coordination-run") data = { run_id: "coordination-run", feature_name: "协作辅助", status: "succeeded", patient_id: 1, evidence, result: { summary: "请核对原记录状态和缺失关联", sections: [], warnings: [], missing_data: [] }, ...(adr ? { adr_findings: context.adr_sources } : { consultation_findings: context.consultation_sources }) };
    if (method === "POST" && /^\/api\/(mdt|referral|adverseReaction|allergy)\//.test(path)) {
      const body = route.request().postDataJSON(); state.businessWrites.push({ path, body });
      if (path === "/api/adverseReaction/updateStatus") state.resolution = body.resolution;
    }
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ code: 200, msg: "success", data }) });
  });
  return state;
}

for (const mode of ["mdt", "referral"]) {
  test(`${mode}入口绑定原患者与记录，原结果和审批不会成为确认诊断或实际接诊`, async ({ page }) => {
    const state = await session(page, mode);
    await page.goto(mode === "mdt" ? "/#/doctor/mdt" : "/#/patient/referral");
    await page.getByRole("button", { name: mode === "mdt" ? "AI 会诊准备" : "AI 转诊准备", exact: true }).click();
    const drawer = page.getByRole("dialog", { name: mode === "mdt" ? "AI 所选MDT病例辅助" : "AI 所选转诊记录辅助", exact: true });
    await expect(drawer.getByRole("combobox", { name: "患者", exact: true })).toBeDisabled();
    await drawer.getByRole("button", { name: "查看本次资料", exact: true }).click();
    const preview = page.getByRole("dialog", { name: "本次提供给 AI 的患者资料", exact: true });
    await preview.getByText(mode === "mdt" ? "MDT #7 · 已退回" : "转诊 #8 · 审批通过/接收标记", { exact: true }).click();
    if (mode === "mdt") {
      await expect(preview).toContainText("不作最终意见");
      await expect(preview).toContainText("科室引用有无法解析");
      await expect(preview.locator(".consultation-findings img")).toHaveCount(0);
    } else {
      await expect(preview).toContainText("未核实（原标识 99999）");
      await expect(preview).toContainText("不能证明已到达或完成接诊");
    }
    await preview.getByRole("button", { name: mode === "mdt" ? "查看MDT原始依据" : "查看转诊原始依据", exact: true }).click();
    const source = page.getByRole("dialog", { name: "核查引用依据", exact: true });
    await expect(source).toContainText(mode === "mdt" ? "原病例已退回" : "无实际接诊记录");
    await source.locator("button.el-dialog__headerbtn").click();
    await preview.locator("button.el-dialog__headerbtn").click();
    await drawer.getByRole("button", { name: "生成辅助建议", exact: true }).click();
    await expect.poll(() => state.submissions.length).toBe(1);
    const refs = mode === "mdt" ? { mdt_id: "7" } : { referral_id: "8" };
    expect(state.previews[0].source_refs).toEqual(refs);
    expect(state.submissions[0]).toMatchObject({ patient_id: 1, input: refs });
    expect(state.businessWrites).toEqual([]);
    await expect(drawer.getByLabel("AI任务结果", { exact: true }).locator(".consultation-findings")).toBeVisible();
  });
}

test("ADR入口固定上报引用，历史状态和未知严重度独立展示，AI不写入处理结果", async ({ page }) => {
  const state = await session(page, "adr");
  await page.goto("/#/pharmacy/adverseReaction");
  await page.getByRole("button", { name: "AI ADR资料分析", exact: true }).click();
  const drawer = page.getByRole("dialog", { name: "AI 所选ADR记录与信号辅助", exact: true });
  await drawer.getByText("联调与预览选项", { exact: true }).click();
  await drawer.getByPlaceholder("可选：专用适配器的结构化输入 JSON，由服务契约规定", { exact: true }).fill('{"reaction_id":"99999"}');
  await drawer.getByRole("button", { name: "查看本次资料", exact: true }).click();
  const preview = page.getByRole("dialog", { name: "本次提供给 AI 的患者资料", exact: true });
  await preview.getByText("ADR #9 · 历史含义待核实", { exact: true }).click();
  await expect(preview).toContainText("未知（原码 99）");
  await expect(preview).toContainText("不根据上报时间推断");
  await expect(preview.locator(".adr-findings img")).toHaveCount(0);
  await preview.getByRole("button", { name: "查看ADR原始依据", exact: true }).click();
  const source = page.getByRole("dialog", { name: "核查引用依据", exact: true });
  await expect(source).toContainText("未提供起病与给药时间");
  await source.locator("button.el-dialog__headerbtn").click();
  await preview.locator("button.el-dialog__headerbtn").click();
  await drawer.getByRole("button", { name: "生成辅助建议", exact: true }).click();
  await expect.poll(() => state.submissions.length).toBe(1);
  expect(state.previews[0].source_refs).toEqual({ reaction_id: "9" });
  expect(state.submissions[0].input.reaction_id).toBe("9");
  expect(state.businessWrites).toEqual([]);
});

test("普通管理员核实历史ADR结果需明确说明，人工操作不发起AI调用", async ({ page }) => {
  const state = await session(page, "adr", "admin");
  await page.goto("/#/pharmacy/adverseReaction");
  await expect(page.getByRole("button", { name: "AI ADR资料分析", exact: true })).toHaveCount(0);
  await page.getByRole("button", { name: "核实历史结果", exact: true }).click();
  const dialog = page.getByRole("dialog", { name: "ADR处理结果核实", exact: true });
  await expect(dialog.getByRole("button", { name: "保存处理结果", exact: true })).toBeDisabled();
  await dialog.getByRole("combobox", { name: "明确处理结果", exact: true }).press("ArrowDown");
  await page.getByRole("option", { name: "已排除ADR", exact: true }).click();
  await dialog.getByRole("textbox", { name: "核实依据或说明", exact: true }).fill("根据原评估记录核实为已排除");
  await dialog.getByRole("button", { name: "保存处理结果", exact: true }).click();
  await expect(dialog).not.toBeVisible();
  await expect(page.getByRole("cell", { name: "已记录排除ADR", exact: true })).toBeVisible();
  expect(state.businessWrites).toEqual([{ path: "/api/adverseReaction/updateStatus", body: { reaction_id: 9, status: 2, resolution: "excluded", note: "根据原评估记录核实为已排除" } }]);
  expect(state.submissions).toEqual([]);
});

test("患者端不开放内部转诊工作页或加载其病例列表", async ({ page }) => {
  const state = await session(page, "referral", "patient");
  await page.goto("/#/patient/referral");
  await page.waitForLoadState("networkidle");
  await expect(page.getByRole("button", { name: "AI 转诊准备", exact: true })).toHaveCount(0);
  expect(state.reads).not.toContain("/api/referral/getList");
  expect(state.previews).toEqual([]);
});
