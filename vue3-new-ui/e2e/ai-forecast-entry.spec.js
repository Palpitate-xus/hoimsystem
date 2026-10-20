const { test, expect } = require("@playwright/test");
// Frozen, synthetic-only sources and outputs from the real stdlib kernel, validated by ForecastAnalysis.
// These browser fixtures verify presentation and request binding, not operational effectiveness.
const fixture = require("./fixtures/forecast-synthetic.json");
const [a, b] = fixture.sources, createdSource = fixture.created_source;
const copy = value => JSON.parse(JSON.stringify(value));
const metadata = (source, index = 0) => ({ ...Object.fromEntries(Object.entries(source).filter(([key]) => !["observations", "coverage_status", "coverage_attested_at", "coverage_note_hash", "registration_digest", "unassigned_time_records"].includes(key))), name: index ? "合成零记录来源乙" : "合成线性来源甲", status: "active", revision: 1, day_count: 112, create_time: source.coverage_attested_at, freshness: "not_checked" });
const coverageNote = "合成完整覆盖依据：逐日对照已归档挂号流水，核实每个日期已结束并确认原系统钟点时区。";
async function session(page, options = {}) {
  const metas = fixture.sources.map(metadata), state = { adminReads: [], contexts: [], creates: [], revokes: [], writes: [], runs: [], previewCalls: [], completed: [], adminItems: options.empty ? [] : metas, ...options };
  const details = source => ({ ...metas.find(item => item.series_id === source.series_id), source, current: true, current_error: null, coverage_note: coverageNote, quality: { source_checked: true, notes: ["完整性为超级管理员声明，挂号原记录不等于实际到诊"] } });
  await page.addInitScript(() => localStorage.setItem("hoim-token", "isolated-forecast-browser"));
  await page.route("**/api/**", async route => {
    const req = route.request(), path = new URL(req.url()).pathname, method = req.method(); let data = []; if (path.startsWith("/api/ai/admin/forecast-series")) state.adminReads.push(path);
    if (path === "/api/userInfo") data = { username: "合成运营用户", permissions: options.role ? [options.role] : ["super_admin", "admin"], avatar: "" };
    if (["/api/ai/features", "/api/ai/admin/features"].includes(path)) data = [{ key: "visit_forecast", number: 62, name: "每日挂号记录数预测", category: "operations", priority: "P2", scope: "hospital", engine: "prediction", enabled: true, inputs: ["已确认完整挂号日历史"], deliverables: ["点预测、经验区间、回溯误差"], default_roles: ["super_admin", "admin", "director"], allowed_roles: ["super_admin", "admin", "director"], validation_status: "unreviewed" }];
    if (path === "/api/ai/admin/forecast-series" && method === "GET") data = { items: state.adminItems, truncated: false };
    if (path === "/api/ai/forecast-series") data = { items: metas, truncated: false };
    if (path === "/api/ai/admin/forecast-series/preview") {
      const body = req.postDataJSON(); state.previewCalls.push(body);
      if (state.holdPreview) await new Promise(resolve => { state.releasePreview = resolve; });
      data = { ...a, ...body, expected_digest: "c".repeat(64), observations: a.observations.map(row => ({ date: row.date, observed_count: row.value, value: null })), quality: { all_days_ended: true, zero_is_confirmed: false, coverage_status: "unconfirmed", notes: ["原钟点未转换，无资料日未经确认均为未知"] } };
    }
    if (path === "/api/ai/admin/forecast-series" && method === "POST") {
      const body = req.postDataJSON(); state.creates.push(body);
      if (state.holdCreate) await new Promise(resolve => { state.releaseCreate = resolve; });
      data = { ...metadata(createdSource), source: createdSource, current: true, coverage_note: body.coverage_note, name: body.name, quality: { notes: ["仅超级管理员覆盖声明"] } }; state.adminItems.push({ ...metadata(createdSource), name: body.name });
    }
    const detail = path.match(/^\/api\/ai\/admin\/forecast-series\/([^/]+)$/);
    if (detail && method === "GET") {
      const source = fixture.sources.find(item => item.series_id === detail[1]);
      if (state.holdDetail && source.series_id === a.series_id) await new Promise(resolve => { state.releaseDetail = resolve; });
      data = details(source); if (state.revoked && source.series_id === a.series_id) Object.assign(data, { status: "revoked", revision: 2, current: false, current_error: "来源已撤销", revoked_at: "2026-10-20T02:00:00Z", revoke_reason: "合成原撤销依据" }); state.completed.push(`detail:${source.series_id}`);
    }
    const revoke = path.match(/^\/api\/ai\/admin\/forecast-series\/([^/]+)\/revoke$/);
    if (revoke) { const body = req.postDataJSON(); state.revokes.push({ id: revoke[1], ...body }); if (state.holdRevoke) await new Promise(resolve => { state.releaseRevoke = resolve; }); const source = fixture.sources.find(item => item.series_id === revoke[1]); data = { ...details(source), status: "revoked", revision: 2, current: false, revoked_at: "2026-10-20T02:00:00Z", revoke_reason: body.reason }; state.completed.push(`revoke:${source.series_id}`); }
    if (path === "/api/ai/operational-context") {
      const body = req.postDataJSON(); state.contexts.push(body); const source = fixture.sources.find(item => item.series_id === body.input.forecast_series_id);
      if (state.holdContext && source.series_id === a.series_id) await new Promise(resolve => { state.releaseContext = resolve; });
      data = { context: { source_domain: "registration_forecast", scope: source.scope, forecast_source: source, series_revision: 1, horizon_days: body.input.horizon_days, missing_data: ["覆盖与时区均为管理员声明，不是效果验证"] }, evidence: [{ source_id: source.source_id, title: "冻结挂号来源", content: JSON.stringify(source) }] };
      state.completed.push(`context:${source.series_id}`);
    }
    if (path === "/api/ai/runs" && method === "POST") {
      const body = req.postDataJSON(); state.runs.push(body); const source = fixture.sources.find(item => item.series_id === body.input.forecast_series_id), analysis = copy(fixture.analyses[`${source.series_id}:${body.input.horizon_days}`]);
      if (state.wrongBinding) analysis.source_binding.timezone = "UTC";
      data = { run_id: "synthetic-forecast-run", feature_key: "visit_forecast", feature_name: "每日挂号记录数预测", status: "succeeded", forecast_findings: { forecast_source: source }, evidence: [{ source_id: source.source_id, title: "冻结原始日历史", content: JSON.stringify(source) }], result: { summary: "合成统计输出，不是到诊量或运营效果验证", sections: [], warnings: [], missing_data: [], forecast_analysis: analysis } };
    }
    if (method !== "GET" && !path.includes("forecast-series") && path !== "/api/ai/operational-context" && path !== "/api/ai/runs" && path !== "/api/userInfo") state.writes.push(path);
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ code: 200, msg: "success", data }) });
  });
  return state;
}
async function select(page, name, value, scope = page) { const control = scope.getByRole("combobox", { name, exact: true }); await control.press("ArrowDown"); await page.locator(`#${await control.getAttribute("aria-controls")}`).getByRole("option", { name: value, exact: true }).click(); }
async function management(page) { await page.goto("/#/ai/manage"); await page.getByRole("tab", { name: "挂号预测来源", exact: true }).click(); }
async function newSource(page) {
  await page.getByRole("button", { name: "新建覆盖声明", exact: true }).click();
  const dialog = page.getByRole("dialog", { name: "确认挂号历史覆盖并冻结来源", exact: true });
  await dialog.getByRole("textbox", { name: "预测来源名称", exact: true }).fill("合成新来源");
  await dialog.getByPlaceholder("历史开始日期", { exact: true }).fill(a.date_from); await dialog.getByPlaceholder("历史末日", { exact: true }).fill(a.date_to); await dialog.getByPlaceholder("历史末日", { exact: true }).press("Tab");
  return dialog;
}
async function confirmCheckboxes(dialog) { for (const name of ["我确认整个历史窗口的挂号原记录完整覆盖", "我确认每个日期在声明时区均已结束", "我确认原无时区钟点的时区解释"]) await dialog.getByText(name, { exact: true }).click(); }
async function sourceOption(page, source = a) { const meta = metadata(source, source.series_id === b.series_id ? 1 : 0); await select(page, "冻结预测来源", `${meta.name} · ${source.date_from}至${source.date_to} · ${source.timezone}`); }
async function business(page) { await page.goto("/#/report/operations"); await page.getByRole("button", { name: "AI 运营分析", exact: true }).click(); return page.getByRole("dialog", { name: "AI 运营事实与预测辅助", exact: true }); }

 test("覆盖声明时区与三项确认不预填，原观测0在确认前仍未知，冻结不改启用或模型", async ({ page }) => {
  const state = await session(page, { empty: true }); await management(page); const dialog = await newSource(page);
  await expect(dialog.getByRole("textbox", { name: "原钟点时区解释", exact: true })).toHaveValue("");
  await dialog.getByRole("textbox", { name: "原钟点时区解释", exact: true }).fill("Asia/Shanghai"); await dialog.getByRole("button", { name: "预览原始日计数", exact: true }).click();
  const history = dialog.getByLabel("未确认挂号历史", { exact: true }); await expect(history.locator("tbody tr").first()).toContainText("0"); await expect(history.locator("tbody tr").first()).toContainText("未知（尚未确认覆盖）");
  for (const box of await dialog.getByRole("checkbox").all()) await expect(box).not.toBeChecked();
  await expect(dialog.getByRole("button", { name: "确认声明并冻结来源", exact: true })).toBeDisabled();
  await dialog.getByRole("textbox", { name: "覆盖确认依据", exact: true }).fill("尚不足二十字");
  await confirmCheckboxes(dialog); await expect(dialog.getByRole("button", { name: "确认声明并冻结来源", exact: true })).toBeDisabled();
  await dialog.getByRole("textbox", { name: "覆盖确认依据", exact: true }).fill(coverageNote);
  await dialog.getByRole("button", { name: "确认声明并冻结来源", exact: true }).click(); await expect.poll(() => state.creates.length).toBe(1);
  expect(state.creates[0]).toEqual({ scope: "hospital", department_id: null, date_from: a.date_from, date_to: a.date_to, timezone: "Asia/Shanghai", name: "合成新来源", expected_digest: "c".repeat(64), coverage_note: coverageNote, coverage_confirmed: true, days_ended_confirmed: true, timezone_confirmed: true });
  const detail = page.getByRole("dialog", { name: "冻结挂号预测来源", exact: true }); await expect(detail).toContainText(createdSource.content_hash); await expect(detail.getByLabel("已冻结挂号历史", { exact: true }).locator("tbody tr").first()).toContainText("0"); expect(state.runs).toEqual([]); expect(state.writes).toEqual([]);
});

test("关闭覆盖预览后迟到结果不进入新表单；角色撤销不接受新回执", async ({ page }) => {
  const state = await session(page, { holdPreview: true }); await management(page); let dialog = await newSource(page);
  await dialog.getByRole("textbox", { name: "原钟点时区解释", exact: true }).fill("Asia/Shanghai"); await dialog.getByRole("button", { name: "预览原始日计数", exact: true }).click(); await expect.poll(() => !!state.releasePreview).toBe(true);
  await dialog.getByRole("button", { name: "取消", exact: true }).click(); dialog = await newSource(page); state.releasePreview();
  await expect(dialog.getByLabel("未确认挂号历史", { exact: true })).toHaveCount(0); await expect(dialog.getByRole("button", { name: "确认声明并冻结来源", exact: true })).toBeDisabled();
  await dialog.getByRole("textbox", { name: "原钟点时区解释", exact: true }).fill("UTC"); await dialog.getByRole("button", { name: "预览原始日计数", exact: true }).click(); await expect.poll(() => state.previewCalls.length).toBe(2);
  await page.evaluate(() => document.querySelector("#hoim").__vue_app__.config.globalProperties.$store.commit("user/setPermissions", ["admin"])); state.releasePreview(); await expect(dialog).toBeHidden(); expect(state.creates).toEqual([]);
});

test("迟到冻结响应不覆盖新声明，撤销响应不覆盖另一个冻结来源", async ({ page }) => {
  const state = await session(page, { holdCreate: true, holdRevoke: true }); await management(page); const dialog = await newSource(page);
  await dialog.getByRole("textbox", { name: "原钟点时区解释", exact: true }).fill("Asia/Shanghai"); await dialog.getByRole("button", { name: "预览原始日计数", exact: true }).click(); await dialog.getByRole("textbox", { name: "覆盖确认依据", exact: true }).fill(coverageNote); await confirmCheckboxes(dialog);
  await dialog.getByRole("button", { name: "确认声明并冻结来源", exact: true }).click(); await expect.poll(() => !!state.releaseCreate).toBe(true); await dialog.getByRole("button", { name: "取消", exact: true }).click();
  const next = await newSource(page); await next.getByRole("textbox", { name: "预测来源名称", exact: true }).fill("下一份未提交声明"); state.releaseCreate(); await expect(next.getByRole("textbox", { name: "预测来源名称", exact: true })).toHaveValue("下一份未提交声明"); await next.getByRole("button", { name: "取消", exact: true }).click();
  await page.getByRole("row").filter({ hasText: "合成线性来源甲" }).getByRole("button", { name: "查看冻结来源", exact: true }).click(); let detail = page.getByRole("dialog", { name: "冻结挂号预测来源", exact: true });
  await detail.getByRole("textbox", { name: "预测来源撤销依据", exact: true }).fill("合成撤销依据"); await detail.getByRole("button", { name: "撤销此来源", exact: true }).click(); await expect.poll(() => !!state.releaseRevoke).toBe(true); await detail.getByRole("button", { name: "关闭", exact: true }).click();
  await page.getByRole("row").filter({ hasText: "合成零记录来源乙" }).getByRole("button", { name: "查看冻结来源", exact: true }).click(); detail = page.getByRole("dialog", { name: "冻结挂号预测来源", exact: true }); await expect(detail).toContainText(b.content_hash); state.releaseRevoke(); await expect.poll(() => state.completed.includes(`revoke:${a.series_id}`)).toBe(true); await expect(detail).toContainText(b.content_hash); await expect(detail).not.toContainText(a.content_hash); expect(state.revokes[0]).toEqual({ id: a.series_id, expected_revision: 1, reason: "合成撤销依据" });
});

test("预测限定7/14天与冻结来源，超级管理员补充JSON也不能覆盖数值口径", async ({ page }) => {
  const state = await session(page); const drawer = await business(page); await sourceOption(page);
  await expect(drawer.getByRole("button", { name: "生成辅助建议", exact: true })).toBeEnabled(); await expect(drawer).toContainText("自历史末日次日起算：2024-04-22");
  await drawer.getByText("联调与预览选项", { exact: true }).click(); await drawer.getByPlaceholder("可选：专用适配器的结构化输入 JSON，由服务契约规定", { exact: true }).fill(JSON.stringify({ forecast_series_id: b.series_id, horizon_days: 100, timezone: "UTC", observations: [{ value: 99999 }], target: "clinical_risk" }));
  await select(page, "外推跨度", "14天"); await expect(drawer.getByRole("button", { name: "生成辅助建议", exact: true })).toBeEnabled(); await drawer.getByRole("button", { name: "查看本次运营资料", exact: true }).click();
  const preview = page.getByRole("dialog", { name: "本次提供给 AI 的运营资料", exact: true }); await expect(preview).toContainText(a.source_id); await preview.getByText("查看原始冻结历史", { exact: true }).click(); await expect(preview.getByLabel("原始冻结历史", { exact: true }).locator("tbody tr").first()).toContainText("0"); await preview.locator(".el-dialog__headerbtn").click();
  await drawer.getByRole("button", { name: "生成辅助建议", exact: true }).click(); await expect.poll(() => state.runs.length).toBe(1);
  expect(state.runs[0].input).toEqual({ forecast_series_id: a.series_id, horizon_days: 14, question: "" }); expect(state.contexts.at(-1).input).toEqual(state.runs[0].input);
  const output = drawer.getByLabel("AI任务结果", { exact: true }); await expect(output).toContainText("392 个"); await expect(output).toContainText("41 个不同目标日期"); await expect(output).toContainText("并非当时可得数据回放"); await expect(output).toContainText("不保证未来90%覆盖"); await expect(output).toContainText("94.5"); const expectedWape = (fixture.analyses[`${a.series_id}:14`].backtest.primary_metrics.wape * 100).toFixed(2) + "%"; await expect(output.getByLabel("回测算法与误差分母", { exact: true })).toContainText(expectedWape); expect(state.writes).toEqual([]);
});

test("零历史的WAPE和MASE不可计算，真实0预测与196/34回测分母保留", async ({ page }) => {
  const state = await session(page, { role: "admin" }); const drawer = await business(page); await sourceOption(page, b); await drawer.getByRole("button", { name: "生成辅助建议", exact: true }).click(); await expect.poll(() => state.runs.length).toBe(1);
  const output = drawer.getByLabel("AI任务结果", { exact: true }); await expect(output).toContainText("196 个"); await expect(output).toContainText("34 个不同目标日期"); const metrics = output.getByLabel("回测算法与误差分母", { exact: true }); await expect(metrics).toContainText("不可计算（实际量合计为0）"); await expect(metrics).toContainText("未知（存在零原点尺度）"); await expect(metrics).not.toContainText("0.00%"); await expect(output.getByLabel("每日点预测与经验区间", { exact: true }).locator("tbody tr").first()).toContainText("0"); expect(state.creates).toEqual([]); expect(state.writes).toEqual([]);
});

test("切换来源后迟到原资料不恢复旧选择，角色变动清除旧来源", async ({ page }) => {
  const state = await session(page, { holdContext: true }); const drawer = await business(page); await sourceOption(page); await expect.poll(() => !!state.releaseContext).toBe(true); await sourceOption(page, b); await expect(drawer.getByRole("button", { name: "生成辅助建议", exact: true })).toBeEnabled(); state.releaseContext(); await expect.poll(() => state.completed.includes(`context:${a.series_id}`)).toBe(true); await expect(drawer).toContainText(b.source_id); await expect(drawer).not.toContainText(a.source_id);
  await page.evaluate(() => document.querySelector("#hoim").__vue_app__.config.globalProperties.$store.commit("user/setPermissions", ["patient"])); await expect(drawer).not.toContainText(b.content_hash); await expect(drawer.getByRole("button", { name: "生成辅助建议", exact: true })).toBeDisabled(); expect(state.runs).toEqual([]);
});

test("错误预测clock绑定不替换原依据标识或显示预测数值", async ({ page }) => {
  const state = await session(page, { wrongBinding: true }); const drawer = await business(page); await sourceOption(page); await drawer.getByRole("button", { name: "生成辅助建议", exact: true }).click(); await expect.poll(() => state.runs.length).toBe(1);
  const output = drawer.getByLabel("AI任务结果", { exact: true }); await expect(output).toContainText("预测与原来源绑定不一致"); await expect(output).toContainText("原钟点时区解释 Asia/Shanghai"); await expect(output.getByLabel("每日点预测与经验区间", { exact: true })).toHaveCount(0); await output.getByRole("button", { name: "核对冻结挂号来源依据", exact: true }).click(); await expect(page.getByRole("dialog", { name: "核查引用依据", exact: true })).toContainText(a.source_id);
});

test("普通管理员无法访问来源治理接口", async ({ page }) => { const state = await session(page, { role: "admin" }); await page.goto("/#/ai/manage"); await expect(page).toHaveURL(/#\/404/); expect(state.previewCalls).toEqual([]); expect(state.creates).toEqual([]); expect(state.revokes).toEqual([]); expect(state.adminReads).toEqual([]); });


test("关闭旧来源详情后迟到响应不替换新详情，已撤销来源没有恢复入口", async ({ page }) => {
  const state = await session(page, { holdDetail: true }); await management(page);
  await page.getByRole("row").filter({ hasText: "合成线性来源甲" }).getByRole("button", { name: "查看冻结来源", exact: true }).click();
  const detail = page.getByRole("dialog", { name: "冻结挂号预测来源", exact: true }); await expect.poll(() => !!state.releaseDetail).toBe(true); await detail.getByRole("button", { name: "关闭", exact: true }).click();
  await page.getByRole("row").filter({ hasText: "合成零记录来源乙" }).getByRole("button", { name: "查看冻结来源", exact: true }).click(); await expect(detail).toContainText(b.content_hash); state.releaseDetail(); await expect.poll(() => state.completed.includes(`detail:${a.series_id}`)).toBe(true); await expect(detail).not.toContainText(a.content_hash); await detail.getByRole("button", { name: "关闭", exact: true }).click();
  state.holdDetail = false; state.revoked = true;
  await page.getByRole("row").filter({ hasText: "合成线性来源甲" }).getByRole("button", { name: "查看冻结来源", exact: true }).click(); await expect(detail).toContainText("此来源不能恢复"); await expect(detail.getByRole("button", { name: "撤销此来源", exact: true })).toHaveCount(0); await expect(detail.getByRole("button", { name: "恢复", exact: true })).toHaveCount(0); expect(state.revokes).toEqual([]);
});
