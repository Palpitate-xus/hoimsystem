const { test, expect } = require("@playwright/test");
const { createHash } = require("node:crypto");

// Synthetic, calibrated bytes exercise transport and review, never a clinical classifier.
const assetId = "33333333-3333-4333-8333-333333333333", encounterRef = "22222222-2222-4222-8222-222222222222";
const standardLeads = ["I", "II", "III", "aVR", "aVL", "aVF", "V1", "V2", "V3", "V4", "V5", "V6"];
function syntheticWaveform({ rate = 500, names = ["I", "MLII"], missing = true } = {}) {
  const count = 1000, raw = Buffer.alloc(count * names.length * 2);
  const values = names.map((_, channel) => Array.from({ length: count }, (_, sample) => {
    const value = missing && sample >= 100 && sample < 140 ? -32768 : Math.round(1000 * Math.sin((sample + channel * 30) / 40));
    raw.writeInt16LE(value, (sample * names.length + channel) * 2); return value;
  }));
  const header = Buffer.from([`fixture ${names.length} ${rate} ${count}`, ...names.map((name, i) => `fixture.dat 16 1000(0)/mV 16 0 ${values[i][0]} ${((values[i].reduce((a, b) => a + b, 0) + 32768) & 65535) - 32768} 0 ${name}`), "# 仅隔离合成信号，原头可能含标识，不提供给模型", ""].join("\n"));
  const digest = value => createHash("sha256").update(value).digest("hex"), headerHash = digest(header), signalHash = digest(raw), hash = digest(JSON.stringify({ format: "wfdb16", header_hash: headerHash, signal_hash: signalHash })), sourceId = `ecg:${assetId}:${hash.slice(0, 12)}`;
  return { rate, count, names, raw, values, header, headerHash, signalHash, hash, sourceId };
}
const defaultWaveform = syntheticWaveform(), { raw, header, signalHash } = defaultWaveform;

async function session(page, { role = "doctor", existing = false, holdUpload = false, holdWindow = false, failFirstPurge = false, missingAll = false, localRuntime = false } = {}) {
  const { rate, count, names, raw, values, header, headerHash, signalHash, hash, sourceId } = localRuntime ? syntheticWaveform({ rate: 100, names: standardLeads, missing: false }) : defaultWaveform;
  const runtimeReport = localRuntime ? {
    engine: "ssl-ecg-cnn", engine_versions: { torch: "2.10.0", numpy: "2.4.4", safetensors: "0.7.0" },
    model_repository: "Tumo505/SSL-ECG-Classification-model-card", model_revision: "a".repeat(40),
    model_digest: "b".repeat(64), runtime_digest: "c".repeat(64), preprocessing_digest: "d".repeat(64),
    required_leads: standardLeads, sample_rate_hz: 100, samples_per_lead: 1000,
    labels: ["NORM", "CD", "HYP", "MI", "STTC"], missing_sample_policy: "reject", prompt_handling: "signal_only",
    clinical_validation: "not_provided", population_applicability: "not_verified",
  } : null;
  const state = { uploads: [], previews: [], submissions: [], withdrawals: [], purges: [], businessWrites: [], windows: [], downloads: [], exists: existing, status: "ready", revision: 1, releaseUpload: null, releaseWindow: null };
  const metadata = () => ({
    asset_id: assetId, patient_id: 1, encounter_ref: encounterRef, content_hash: hash, header_hash: headerHash, signal_hash: signalHash, byte_size: raw.length + header.length, header_byte_size: header.length, signal_byte_size: raw.length, status: state.status, revision: state.revision, created_by: 3, create_time: "2026-10-20T10:00:00", recorded_at: null, can_withdraw: role === "super_admin" && state.status === "ready",
    signal_metadata: { format: "wfdb16", sample_rate_hz: String(rate), sample_count: count, duration_ms: count * 1000 / rate, channels: names.length, missing_sample_value: -32768, leads: names.map(name => ({ name, gain: "1000", baseline: 0, unit: "mV", missing_samples: missingAll ? count : localRuntime ? 0 : 40, constant_observed_values: missingAll ? null : false })) },
  });
  const source = { ...metadata(), source_id: sourceId };
  const context = { scope: "raw_ecg_analysis", scope_note: "仅所选原采样和技术参数，不按今天年龄推定采集人群", ecg_source: source, missing_data: ["原采集年龄与适用人群未核实", "原采集时刻未记录"] };
  const evidence = [{ source_id: sourceId, kind: "ecg_asset", title: "原心电元数据依据", content: "已核对原采样哈希，不加载原头注释或其他病史" }];
  const findings = localRuntime ? runtimeReport.labels.map((label, index) => ({ category: "other", label, description: "隔离测试各标签独立原始分数，不提供临床结论或定位", leads: names, location: "recording", start_sample: null, end_sample_exclusive: null, score: [0, 0.1, 0.2, 0.7, 1][index], score_kind: "model_score", source_id: sourceId })) : [
    { category: "other", label: "隔离测试局部候选", description: "<img src=x onerror=alert(1)> 合成候选，无临床含义", leads: ["I"], location: "sample_interval", start_sample: 600, end_sample_exclusive: 800, score: 0, score_kind: "model_score", source_id: sourceId },
    { category: "signal_quality", label: "隔离测试整段候选", description: "未提供局部定位", leads: ["MLII"], location: "recording", start_sample: null, end_sample_exclusive: null, score: null, score_kind: "model_score", source_id: sourceId },
  ];
  const feature = { number: 37, key: "ecg_analysis", name: "心电辅助分析", scope: "patient", engine: "signal", category: "diagnostics", enabled: true, validation_status: "validated", inputs: ["WFDB原始采样及授权"], deliverables: ["待复核候选及原导联定位"], source_reference_keys: ["ecg_asset_id"], default_roles: ["super_admin", "doctor", "director", "lab_technician"], allowed_roles: ["super_admin", "doctor", "director", "lab_technician"], setup_check: { ready: true, issues: [] } };
  await page.addInitScript(() => {
    localStorage.setItem("hoim-token", "isolated-ecg-test"); window.__copiedEcg = "";
    Object.defineProperty(navigator, "clipboard", { configurable: true, value: { writeText: async text => { window.__copiedEcg = text; } } });
  });
  await page.route("**/api/**", async route => {
    const request = route.request(), url = new URL(request.url()), path = url.pathname, method = request.method(); let data = [];
    if (path === "/api/userInfo") data = { username: "心电测试用户", permissions: role === "super_admin" ? ["super_admin", "admin"] : [role], avatar: "" };
    if (["/api/ai/features", "/api/ai/admin/features"].includes(path)) data = [feature];
    if (path === "/api/medicalRecord/getList") data = [{ uuid: "note-1", patient_id: 1, patient_name: "测试患者甲", registration_uuid: encounterRef, status: 0, symptom: "原病历文本", result: "原诊断文本" }];
    if (path === "/api/ai/patients") data = [{ patient_id: 1, label: "测试患者甲 · #1" }, { patient_id: 2, label: "测试患者乙 · #2" }];
    if (path === "/api/ai/encounters") data = [{ encounter_ref: encounterRef, label: "原登记门诊" }];
    if (path === "/api/ai/ecg-options") data = { max_bytes: 33554432, max_duration_seconds: 300, user_quota_bytes: 536870912, used_bytes: 0, scope_note: "原诊疗成员按范围共享，登记不调用模型" };
    if (path === "/api/ai/ecg-assets" && method === "POST") {
      state.uploads.push({ body: request.postDataBuffer(), type: request.headers()["content-type"] });
      if (holdUpload) await new Promise(resolve => { state.releaseUpload = resolve; }); state.exists = true; data = metadata();
    }
    if (path === "/api/ai/ecg-assets" && method === "GET") data = { items: state.exists && url.searchParams.get("patient_id") === "1" ? [metadata()] : [], truncated: false };
    if (path === "/api/ai/admin/ecg-assets") data = { items: state.exists ? [metadata()] : [], truncated: false };
    if (path === `/api/ai/ecg-assets/${assetId}`) data = { ...metadata(), authorization_note: "原来源授权说明 <img src=x onerror=alert(1)>", withdrawal_note: "已核对的原撤回原因", purge_note: "首次清除请求需保留" };
    if (path.endsWith(`/${assetId}/window`)) {
      const start = Number(url.searchParams.get("start_sample")), end = Math.min(count, start + Number(url.searchParams.get("sample_count")));
      state.windows.push({ token: request.headers().accesstoken, query: url.search, start });
      data = { asset_id: assetId, content_hash: hash, revision: state.revision, status: state.status, start_sample: start, end_sample_exclusive: end, sample_rate_hz: String(rate), display_unit: "mV", decimated: false, scope_note: "合成原采样窗口，不是诊断", leads: names.map((name, i) => ({ name, missing_samples_in_window: values[i].slice(start, end).filter(v => v === -32768).length, points: values[i].slice(start, end).map((value, offset) => ({ sample: start + offset, value_mv: value === -32768 ? null : value / 1000, break_before: value === -32768 || values[i][start + offset - 1] === -32768 })) })) };
      if (holdWindow && state.windows.length === 1) await new Promise(resolve => { state.releaseWindow = resolve; });
    }
    if (path.endsWith(`/${assetId}/content`)) { state.downloads.push({ token: request.headers().accesstoken, query: url.search }); await route.fulfill({ status: 200, contentType: "application/octet-stream", body: header }); return; }
    if (path.endsWith(`/${assetId}/withdraw`)) { state.withdrawals.push(request.postDataJSON()); state.status = "withdrawn"; state.revision = 2; data = metadata(); }
    if (path.endsWith(`/${assetId}/purge`)) {
      state.purges.push(request.postDataJSON());
      if (failFirstPurge && state.purges.length === 1) { state.status = "purge_pending"; state.revision = 3; await route.fulfill({ status: 503, contentType: "application/json", body: JSON.stringify({ detail: "模拟存储暂不可用，原清除请求保留" }) }); return; }
      state.status = "purged"; state.revision = 4; data = metadata();
    }
    if (path === "/api/ai/context") { state.previews.push(request.postDataJSON()); data = { context, evidence }; }
    if (path === "/api/ai/runs" && method === "POST") { state.submissions.push(request.postDataJSON()); data = { run_id: "ecg-run", status: "queued", feature_name: "心电辅助分析", patient_id: 1 }; }
    if (path === "/api/ai/runs/ecg-run") data = { run_id: "ecg-run", status: "succeeded", feature_name: "心电辅助分析", patient_id: 1, ecg_findings: context, evidence, result: { summary: "隔离协议草稿，未调用真实心电模型", sections: [], warnings: [], missing_data: [], ecg_analysis: { asset_id: assetId, content_hash: hash, signal_hash: signalHash, time_basis: "relative_samples", processing: { instructions_digest: "a".repeat(64), input_sample_count: count, input_sample_rate_hz: String(rate), input_leads: names, used_leads: names, processed_original_sample_count: count, complete_input: true, missing_sample_handling: localRuntime ? "none_present" : "masked", preprocessing_notes: [localRuntime ? "合成12导联100Hz完整10秒，未做滤波、重采样、填补或裁剪" : "合成信号使用缺失标记，无诊断验证"], ...(localRuntime ? { local_runtime: runtimeReport } : {}) }, findings } } };
    if (method === "POST" && /^\/api\/(medicalRecord|emr|prescriptionManagement|clinicalDiagnosis)\//.test(path)) state.businessWrites.push(path);
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ code: 200, msg: "success", data }) });
  });
  return state;
}

async function uploadPair(input) {
  await input.getByText("登记成对原始心电文件", { exact: true }).click();
  await input.getByLabel("选择心电原头文件", { exact: true }).setInputFiles({ name: "fixture.hea", mimeType: "application/octet-stream", buffer: header });
  await input.getByLabel("选择心电原采样文件", { exact: true }).setInputFiles({ name: "fixture.dat", mimeType: "application/octet-stream", buffer: raw });
  await input.getByRole("textbox", { name: "心电原文件授权核对说明", exact: true }).fill("已核对本次合成信号与所选患者的来源关联和处理授权");
  await input.getByText("我已核对原文件来源、使用授权及所选患者和原就诊关联", { exact: true }).click();
  await input.getByRole("button", { name: "登记成对原心电", exact: true }).click();
}
async function selectSource(scope, page) {
  const select = scope.getByRole("combobox", { name: "待判读原始心电", exact: true }); await expect(select).toBeEnabled(); await select.press("ArrowDown"); await page.getByRole("option", { name: /心电 33333333/ }).click();
}
async function openDoctor(page) {
  await page.goto("/#/doctor/medicalRecord"); await page.getByRole("button", { name: "AI 心电复核", exact: true }).click(); return page.getByRole("dialog", { name: "AI 原始心电与候选复核", exact: true });
}

test("门诊成对原文件以真实multipart登记，预览与模型任务绑定同一原心电，波形私有读取且复制保留候选", async ({ page }, testInfo) => {
  const state = await session(page), drawer = await openDoctor(page), input = drawer.getByLabel("原始心电登记与选择", { exact: true });
  await expect(drawer.getByRole("combobox", { name: "患者", exact: true })).toBeDisabled();
  await expect(drawer.getByRole("button", { name: "生成辅助建议", exact: true })).toBeDisabled(); await uploadPair(input);
  await expect.poll(() => state.uploads.length).toBe(1);
  expect(state.uploads[0].type).toContain("multipart/form-data; boundary="); expect(state.uploads[0].body.includes(raw)).toBe(true); expect(state.uploads[0].body.includes(header)).toBe(true); expect(state.uploads[0].body.toString()).toContain(encounterRef);
  expect(state.submissions).toEqual([]); expect(state.windows).toEqual([]);
  await drawer.getByRole("button", { name: "查看本次资料", exact: true }).click();
  const preview = page.getByRole("dialog", { name: "本次提供给 AI 的患者资料", exact: true }); await expect(preview).toContainText("原采集年龄与适用人群未核实");
  expect(state.windows).toEqual([]); await preview.getByRole("button", { name: "加载原始波形", exact: true }).click();
  const canvas = preview.getByRole("img", { name: "导联 I 原始波形", exact: true }); await expect(canvas).toBeVisible();
  await expect.poll(async () => canvas.evaluate(element => { const bytes = element.getContext("2d").getImageData(0, 0, element.width, element.height).data; let blue = 0; for (let i = 0; i < bytes.length; i += 4) if (bytes[i] < 80 && bytes[i + 1] > 70 && bytes[i + 1] < 150 && bytes[i + 2] > 130) blue++; return blue; })).toBeGreaterThan(100);
  await expect(preview).toContainText("本窗缺失 40 个采样"); await expect(preview).toContainText("MLII");
  expect(state.windows[0].token).toBe("isolated-ecg-test"); expect(state.windows[0].query).not.toMatch(/token|isolated-ecg-test/);
  const downloadEvent = page.waitForEvent("download"); await preview.getByRole("button", { name: "下载原头文件（可能含标识）", exact: true }).click(); const download = await downloadEvent;
  expect(download.suggestedFilename()).toBe(`ecg-${assetId}.hea`); expect(state.downloads[0]).toEqual({ token: "isolated-ecg-test", query: "?part=header" });
  await preview.locator("button.el-dialog__headerbtn").click(); await drawer.getByRole("button", { name: "生成辅助建议", exact: true }).click();
  await expect.poll(() => state.submissions.length).toBe(1);
  expect(state.previews[0]).toMatchObject({ patient_id: 1, encounter_ref: encounterRef, source_refs: { ecg_asset_id: assetId } }); expect(state.submissions[0]).toMatchObject({ encounter_ref: encounterRef, input: { ecg_asset_id: assetId } });
  expect(state.submissions[0].input.record_id).toBeUndefined();
  const result = drawer.getByLabel("AI任务结果", { exact: true }); await expect(result).toContainText("非患病概率"); await expect(result).toContainText("全记录级，未提供局部定位"); await expect(result.locator(".ecg-findings img")).toHaveCount(0); await expect(result.getByLabel("本地心电研究模型运行记录", { exact: true })).toHaveCount(0);
  const localRow = result.getByRole("row").filter({ hasText: "隔离测试局部候选" }); await expect(localRow.getByRole("cell", { name: "0 非患病概率", exact: true })).toBeVisible();
  await localRow.getByRole("button", { name: "查看原波形", exact: true }).click(); await expect(result).toContainText("模型定位导联 I，原样本 600–800");
  const highlightedPixels = label => result.getByRole("img", { name: `导联 ${label} 原始波形`, exact: true }).evaluate(element => { const bytes = element.getContext("2d").getImageData(0, 0, element.width, element.height).data; let yellow = 0; for (let i = 0; i < bytes.length; i += 4) if (bytes[i] > 235 && bytes[i + 1] > 210 && bytes[i + 1] < 247 && bytes[i + 2] < 235) yellow++; return yellow; });
  await expect.poll(() => highlightedPixels("I")).toBeGreaterThan(100); expect(await highlightedPixels("MLII")).toBe(0);
  await result.getByRole("img", { name: "导联 I 原始波形", exact: true }).screenshot({ path: testInfo.outputPath("ecg-waveform.png") });
  await result.getByRole("button", { name: "复制心电候选草稿", exact: true }).click();
  await expect.poll(() => page.evaluate(() => window.__copiedEcg)).toContain("模型原始分数 0（非患病概率）"); const copied = await page.evaluate(() => window.__copiedEcg); expect(copied).toContain("原样本[600, 800)"); expect(copied).toContain("整段候选，不提供精确定位"); expect(copied).toContain(signalHash); expect(state.businessWrites).toEqual([]);
});

test("本地研究模型展示真实运行记录和五类独立原始分数，保留未验证人群及临床范围", async ({ page }) => {
  const state = await session(page, { existing: true, localRuntime: true }), drawer = await openDoctor(page);
  await selectSource(drawer, page); await drawer.getByRole("button", { name: "生成辅助建议", exact: true }).click();
  const result = drawer.getByLabel("AI任务结果", { exact: true }), runtime = result.getByLabel("本地心电研究模型运行记录", { exact: true });
  await expect(runtime).toContainText("ssl-ecg-cnn");
  await expect(runtime).toContainText("torch 2.10.0");
  await expect(runtime).toContainText("Tumo505/SSL-ECG-Classification-model-card");
  await expect(runtime).toContainText("a".repeat(40));
  for (const digest of ["b", "c", "d"]) await expect(runtime).toContainText(digest.repeat(64));
  await expect(runtime).toContainText(`原始 ${standardLeads.join("、")} 导联；100 Hz，每导联 1000 个样本，10 秒`);
  await expect(runtime).toContainText("reject：拒绝缺失样本；不滤波、不重采样、不填补或补零、不裁剪原始输入");
  await expect(runtime).toContainText("signal_only：仅对所选原始信号分类");
  await expect(runtime).toContainText("not_verified：未核实采集时人群及本模型适用性");
  await expect(runtime).toContainText("not_provided：未提供临床验证，不代表已验证的临床准确性");
  await expect(runtime).toContainText("未设置诊断阈值，不能据此判定正常或确诊");
  const labels = ["NORM", "CD", "HYP", "MI", "STTC"], scores = [0, 0.1, 0.2, 0.7, 1];
  for (const [index, label] of labels.entries()) {
    const row = result.getByRole("row").filter({ has: page.getByRole("cell", { name: label, exact: true }) });
    await expect(row.getByRole("cell", { name: `${scores[index]} 非患病概率`, exact: true })).toBeVisible();
    await expect(row).toContainText("全记录级，未提供局部定位");
  }
  expect(state.submissions).toHaveLength(1); expect(state.windows).toEqual([]); expect(state.businessWrites).toEqual([]);
});

test("上传中切换患者清空文件与授权，迟到登记回执不会给新患者绑定或发起推理", async ({ page }) => {
  const state = await session(page, { holdUpload: true }); await page.goto("/#/ai/workbench"); const patient = page.getByRole("combobox", { name: "患者", exact: true }); await patient.press("ArrowDown"); await page.getByRole("option", { name: "测试患者甲 · #1", exact: true }).click();
  const input = page.getByLabel("原始心电登记与选择", { exact: true }); await uploadPair(input); await expect.poll(() => !!state.releaseUpload).toBe(true);
  await patient.press("ArrowDown"); await page.getByRole("option", { name: "测试患者乙 · #2", exact: true }).click(); state.releaseUpload();
  await expect(page.getByText("登记已完成，当前患者或就诊已切换；请返回原患者核对心电目录", { exact: true })).toBeVisible();
  await expect(input.getByRole("textbox", { name: "心电原文件授权核对说明", exact: true })).toHaveValue(""); await expect(input.getByLabel("选择心电原采样文件", { exact: true })).toHaveJSProperty("value", "");
  await expect(input.getByRole("button", { name: "登记成对原心电", exact: true })).toBeDisabled(); await expect(page.getByRole("button", { name: "生成辅助建议", exact: true })).toBeDisabled(); expect(state.submissions).toEqual([]); expect(state.windows).toEqual([]);
});

test("定位只标原导联，较早的局部读取回执不能覆盖随后选择的整段候选窗口", async ({ page }) => {
  const state = await session(page, { existing: true, holdWindow: true }), drawer = await openDoctor(page); await selectSource(drawer, page); await drawer.getByRole("button", { name: "生成辅助建议", exact: true }).click();
  const result = drawer.getByLabel("AI任务结果", { exact: true }), first = result.getByRole("row").filter({ hasText: "隔离测试局部候选" }), second = result.getByRole("row").filter({ hasText: "隔离测试整段候选" });
  await first.getByRole("button", { name: "查看原波形", exact: true }).click(); await expect.poll(() => !!state.releaseWindow).toBe(true); expect(state.windows[0].start).toBe(350);
  await second.getByRole("button", { name: "查看原波形", exact: true }).click(); await expect(result).toContainText("已读取原样本 0–1000"); state.releaseWindow();
  await expect.poll(() => state.windows.length).toBe(2); await expect(result).not.toContainText("已读取原样本 350–1000"); await expect(result).not.toContainText("模型定位导联 I，原样本"); expect(state.uploads).toEqual([]); expect(state.businessWrites).toEqual([]);
});

test("诊疗团队可选他人登记原心电但不能撤回，全缺失原记录只能复核不能生成", async ({ page }) => {
  const state = await session(page, { existing: true, missingAll: true }), drawer = await openDoctor(page); await selectSource(drawer, page);
  await expect(drawer).toContainText("全部采样均为缺失标记"); await expect(drawer.getByRole("button", { name: "撤回所选原心电", exact: true })).toHaveCount(0); await expect(drawer.getByRole("button", { name: "生成辅助建议", exact: true })).toBeDisabled();
  await drawer.getByRole("button", { name: "查看所选原波形", exact: true }).click(); await expect(page.getByRole("dialog", { name: "所选原始心电波形", exact: true })).toBeVisible(); expect(state.submissions).toEqual([]); expect(state.windows).toEqual([]);
});

test("超管核对授权文本，按版本撤回并在清除失败后继续，保持原清除请求且不调用模型", async ({ page }) => {
  const state = await session(page, { role: "super_admin", existing: true, failFirstPurge: true }); await page.goto("/#/ai/manage"); await page.getByRole("tab", { name: "心电原文件", exact: true }).click(); await page.getByRole("button", { name: "核对授权与原波形", exact: true }).click();
  const detail = page.getByRole("dialog", { name: "原始心电登记与授权核对", exact: true }); await expect(detail).toContainText("原来源授权说明 <img src=x onerror=alert(1)>"); await expect(detail.locator("img")).toHaveCount(0); expect(state.windows).toEqual([]); await detail.getByRole("button", { name: "关闭", exact: true }).click();
  await page.getByRole("button", { name: "撤回", exact: true }).click(); let box = page.locator(".el-message-box:visible"); await box.locator("input").fill("已核对本次合成信号原登记人的撤回请求"); await box.getByRole("button", { name: "撤回原心电", exact: true }).click();
  await expect.poll(() => state.withdrawals.length).toBe(1); expect(state.withdrawals[0].expected_revision).toBe(1);
  await page.getByRole("button", { name: "清除原文件", exact: true }).click(); box = page.locator(".el-message-box:visible"); await box.locator("input").fill("首次清除请求已核对原始资料与授权"); await box.getByRole("button", { name: "清除原文件", exact: true }).click();
  await expect(page.getByRole("button", { name: "继续清除", exact: true })).toBeVisible(); expect(state.purges[0].expected_revision).toBe(2);
  await page.getByRole("button", { name: "核对授权与原波形", exact: true }).click(); await expect(detail).toContainText("首次清除请求需保留"); await expect(detail.getByRole("button", { name: "加载原始波形", exact: true })).toHaveCount(0); await detail.getByRole("button", { name: "关闭", exact: true }).click();
  await page.getByRole("button", { name: "继续清除", exact: true }).click(); box = page.locator(".el-message-box:visible"); await box.locator("input").fill("再次执行同一原清除请求并核对当前状态"); await box.getByRole("button", { name: "清除原文件", exact: true }).click();
  await expect(page.getByRole("cell", { name: "原文件已清除", exact: true })).toBeVisible(); expect(state.purges[1].expected_revision).toBe(3); expect(state.submissions).toEqual([]); expect(state.windows).toEqual([]); expect(state.businessWrites).toEqual([]);
});
