const { test, expect } = require("@playwright/test");
const { createHash } = require("node:crypto");
const { execFileSync } = require("node:child_process");

const assetId = "11111111-1111-4111-8111-111111111111", encounterRef = "22222222-2222-4222-8222-222222222222";
function wavClip() {
  const body = Buffer.alloc(4044); body.write("RIFF"); body.writeUInt32LE(4036, 4); body.write("WAVEfmt ", 8); body.writeUInt32LE(16, 16); body.writeUInt16LE(1, 20); body.writeUInt16LE(1, 22); body.writeUInt32LE(8000, 24); body.writeUInt32LE(16000, 28); body.writeUInt16LE(2, 32); body.writeUInt16LE(16, 34); body.write("data", 36); body.writeUInt32LE(4000, 40); return body;
}
const raw = wavClip(), hash = createHash("sha256").update(raw).digest("hex"), sourceId = `audio:${assetId}:${hash.slice(0, 12)}`;

async function session(page, { role = "doctor", existing = false, holdUpload = false, microphone = false, processing = false } = {}) {
  const state = { uploads: [], previews: [], submissions: [], withdrawals: [], purges: [], businessWrites: [], reads: [], contentReads: [], exists: existing, status: "ready", revision: 1, releaseUpload: null };
  const metadata = () => ({ asset_id: assetId, patient_id: 1, encounter_ref: encounterRef, content_hash: hash, extension: ".wav", media_type: "audio/wav", byte_size: raw.length, duration_ms: 250, sample_rate: 8000, channels: 1, codec: "pcm_s16le", status: state.status, revision: state.revision, created_by: 2, create_time: "2026-10-20T10:00:00", recorded_at: null });
  const source = { ...metadata(), source_id: sourceId };
  const context = { scope: "recording_transcription", scope_note: "仅所选原音频，不加载无关病史；分段时间不代表临床时刻", audio_source: source, missing_data: ["说话人身份未知"] };
  const evidence = [{ source_id: sourceId, kind: "audio_asset", title: "原录音元数据依据", content: "原录音发生时间未记录，未加载无关病史" }];
  const feature = { number: 21, key: "medical_transcription", name: "医疗语音录入", scope: "patient", engine: "speech", category: "records", enabled: true, validation_status: "validated", inputs: ["原录音及授权"], deliverables: ["原音分段转写与核对"], source_reference_keys: ["audio_asset_id"], default_roles: ["super_admin", "doctor", "director"], allowed_roles: ["super_admin", "doctor", "director"], setup_check: { ready: true, issues: [] } };
  await page.addInitScript(() => {
    localStorage.setItem("hoim-token", "isolated-speech-test"); window.__revokedAudio = []; window.__copiedSpeech = "";
    const revoke = URL.revokeObjectURL.bind(URL); URL.revokeObjectURL = value => { window.__revokedAudio.push(value); revoke(value); };
    Object.defineProperty(navigator, "clipboard", { configurable: true, value: { writeText: async text => { window.__copiedSpeech = text; } } });
  });
  if (microphone) {
    const webm = execFileSync("ffmpeg", ["-v", "error", "-f", "lavfi", "-i", "anullsrc=r=8000:cl=mono", "-t", "0.25", "-c:a", "libopus", "-f", "webm", "pipe:1"]);
    await page.addInitScript(bytes => {
      window.__recordingStarts = 0; window.__stoppedTracks = 0;
      if (!navigator.mediaDevices) Object.defineProperty(navigator, "mediaDevices", { configurable: true, value: {} });
      Object.defineProperty(navigator.mediaDevices, "getUserMedia", { configurable: true, value: async () => ({ getTracks: () => [{ stop: () => { window.__stoppedTracks += 1; } }] }) });
      window.MediaRecorder = class {
        static isTypeSupported(type) { return type.startsWith("audio/webm"); }
        constructor() { this.state = "inactive"; this.mimeType = "audio/webm;codecs=opus"; }
        start() { this.state = "recording"; window.__recordingStarts += 1; }
        stop() { this.state = "inactive"; queueMicrotask(() => { this.ondataavailable?.({ data: new Blob([Uint8Array.from(bytes)], { type: this.mimeType }) }); this.onstop?.(); }); }
      };
    }, [...webm]);
  }
  await page.route("**/api/**", async route => {
    const request = route.request(), url = new URL(request.url()), path = url.pathname, method = request.method(); state.reads.push(path);
    let data = [];
    if (path === "/api/userInfo") data = { username: "语音测试用户", permissions: role === "super_admin" ? ["super_admin", "admin"] : [role], avatar: "" };
    if (["/api/ai/features", "/api/ai/admin/features"].includes(path)) data = [feature];
    if (path === "/api/medicalRecord/getList") data = [{ uuid: "note-1", patient_id: 1, patient_name: "测试患者甲", registration_uuid: encounterRef, status: 0, symptom: "原病历文本", result: "原诊断文本" }];
    if (path === "/api/ai/patients") data = [{ patient_id: 1, label: "测试患者甲 · #1" }, { patient_id: 2, label: "测试患者乙 · #2" }];
    if (path === "/api/ai/encounters") data = [{ encounter_ref: encounterRef, label: "原登记门诊" }];
    if (path === "/api/ai/audio-options") data = { max_bytes: 67108864, max_duration_seconds: 3600, user_quota_bytes: 536870912, used_bytes: 0, processor_available: true, scope_note: "须核对原录音授权，上传不会发起模型调用" };
    if (path === "/api/ai/audio-assets" && method === "POST") {
      state.uploads.push({ body: request.postDataBuffer(), type: request.headers()["content-type"] });
      if (holdUpload) await new Promise(resolve => { state.releaseUpload = resolve; });
      state.exists = true; data = metadata();
    }
    if (path === "/api/ai/audio-assets" && method === "GET") data = { items: state.exists && url.searchParams.get("patient_id") === "1" ? [metadata()] : [], truncated: false };
    if (path === "/api/ai/admin/audio-assets") data = { items: state.exists ? [metadata()] : [], truncated: false };
    if (path === `/api/ai/audio-assets/${assetId}`) data = { ...metadata(), authorization_note: "原授权说明 <img src=x onerror=alert(1)>", withdrawal_note: "原撤回说明", purge_note: "原清除请求" };
    if (path === `/api/ai/audio-assets/${assetId}/content`) { state.contentReads.push({ token: request.headers().accesstoken, query: url.search }); await route.fulfill({ status: 200, contentType: "audio/wav", body: raw }); return; }
    if (path.endsWith(`/${assetId}/withdraw`)) { state.withdrawals.push(request.postDataJSON()); state.status = "withdrawn"; state.revision = 2; data = metadata(); }
    if (path.endsWith(`/${assetId}/purge`)) { state.purges.push(request.postDataJSON()); state.status = "purged"; state.revision = 4; data = metadata(); }
    if (path === "/api/ai/context") { state.previews.push(request.postDataJSON()); data = { context, evidence }; }
    if (path === "/api/ai/runs" && method === "POST") { state.submissions.push(request.postDataJSON()); data = { run_id: "speech-run", status: "queued", feature_name: "医疗语音录入", patient_id: 1 }; }
    if (path === "/api/ai/runs/speech-run") data = { run_id: "speech-run", status: "succeeded", feature_name: "医疗语音录入", patient_id: 1, audio_findings: context, evidence, result: { summary: "隔离协议草稿，未验证识别质量", sections: [], warnings: [], missing_data: [], transcription: { asset_id: assetId, content_hash: hash, speech_detected: true, time_basis: "relative_decoded_audio", language: "zh-CN", segments: [{ start_ms: 0, end_ms: 200, speaker: "speaker_1", speaker_role: "unknown", text: "<img src=x onerror=alert(1)> 模拟转写片段", uncertain: true, uncertainty_note: "术语需听音核对", source_id: sourceId }] } } };
    if (path === "/api/ai/runs/speech-run" && processing) data.result.transcription.processing = { engine: "faster-whisper", engine_version: "1.2.1", model_revision: "a".repeat(40), model_digest: "b".repeat(64), runtime_digest: "c".repeat(64), decoding_options_hash: "d".repeat(64), instructions_digest: "e".repeat(64), decoded_duration_ms: 250, processed_duration_ms: 250, submitted_samples: 4000, sample_rate: 16000, iterator_exhausted: true, vad_filter: true, translation: false, diarization: false, prompt_handling: "acoustic_only", timestamp_policy: "estimated_bounded_to_source" };
    if (method === "POST" && /^\/api\/(medicalRecord|emr|prescriptionManagement|clinicalDiagnosis)\//.test(path)) state.businessWrites.push(path);
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ code: 200, msg: "success", data }) });
  });
  return state;
}

async function authorize(input) {
  await input.getByRole("textbox", { name: "录音授权说明", exact: true }).fill("已核对这份测试录音与所选患者的采集处理授权");
  await input.getByText("我已核对该录音的采集、处理授权及所选患者和就诊", { exact: true }).click();
}

test("门诊上传原录音使用真实multipart，预览与转写绑定同一来源，原音私有读取且关闭即释放", async ({ page }) => {
  const state = await session(page);
  await page.goto("/#/doctor/medicalRecord");
  await page.getByRole("button", { name: "AI 录音转写", exact: true }).click();
  const drawer = page.getByRole("dialog", { name: "AI 原录音与转写复核", exact: true });
  const input = drawer.getByLabel("医疗录音登记与选择", { exact: true });
  await expect(drawer.getByRole("combobox", { name: "患者", exact: true })).toBeDisabled();
  await input.getByText("登记新录音或使用麦克风采集", { exact: true }).click();
  await input.getByLabel("选择授权录音文件", { exact: true }).setInputFiles({ name: "授权原录音.wav", mimeType: "audio/wav", buffer: raw });
  await authorize(input);
  await input.getByRole("button", { name: "登记所选录音", exact: true }).click();
  await expect.poll(() => state.uploads.length).toBe(1);
  expect(state.uploads[0].type).toContain("multipart/form-data; boundary="); expect(state.uploads[0].body.includes(raw)).toBe(true);
  expect(state.uploads[0].body.toString()).toContain(encounterRef); expect(state.submissions).toEqual([]); expect(state.contentReads).toEqual([]);
  await drawer.getByRole("button", { name: "查看本次资料", exact: true }).click();
  const preview = page.getByRole("dialog", { name: "本次提供给 AI 的患者资料", exact: true });
  await preview.getByRole("button", { name: "加载原录音", exact: true }).click();
  await expect.poll(() => state.contentReads.length).toBe(1); expect(state.contentReads[0]).toEqual({ token: "isolated-speech-test", query: "" });
  await expect(preview.locator("audio")).toHaveAttribute("src", /^blob:/);
  await preview.locator("button.el-dialog__headerbtn").click();
  await expect.poll(() => page.evaluate(() => window.__revokedAudio.length)).toBe(1);
  await drawer.getByRole("button", { name: "生成辅助建议", exact: true }).click();
  await expect.poll(() => state.submissions.length).toBe(1);
  expect(state.previews[0]).toMatchObject({ patient_id: 1, encounter_ref: encounterRef, source_refs: { audio_asset_id: assetId } }); expect(state.submissions[0].input.audio_asset_id).toBe(assetId);
  const result = drawer.getByLabel("AI任务结果", { exact: true });
  await expect(result).toContainText("服务未提供完整处理范围报告");
  await expect(result.locator(".speech-findings")).toContainText("角色待核实"); await expect(result.locator(".speech-findings img")).toHaveCount(0);
  await result.getByRole("button", { name: "复制转写草稿", exact: true }).click();
  await expect.poll(() => page.evaluate(() => window.__copiedSpeech)).toContain("模拟转写片段");
  expect(await page.evaluate(() => window.__copiedSpeech)).toContain("speaker_1（角色待核实）"); expect(state.businessWrites).toEqual([]);
});

test("本地识别报告展示实际处理范围和未区分说话人，完整处理不标作准确率", async ({ page }) => {
  const state = await session(page, { existing: true, processing: true });
  await page.goto("/#/doctor/medicalRecord");
  await page.getByRole("button", { name: "AI 录音转写", exact: true }).click();
  const drawer = page.getByRole("dialog", { name: "AI 原录音与转写复核", exact: true });
  const recording = drawer.getByRole("combobox", { name: "待转写原录音", exact: true });
  await expect(recording).toBeEnabled(); await recording.press("ArrowDown");
  await page.getByRole("option", { name: /录音 11111111/ }).click();
  await drawer.getByRole("button", { name: "生成辅助建议", exact: true }).click();
  const result = drawer.getByLabel("AI任务结果", { exact: true });
  await expect(result).toContainText("服务报告已处理 0.250 秒输入");
  await expect(result).toContainText("本次未区分说话人");
  await expect(result).toContainText("处理范围报告不保证逐字完整或识别准确");
  await expect(result).toContainText("可能漏检语音");
  await result.getByText("查看识别版本", { exact: true }).click();
  await expect(result).toContainText("faster-whisper 1.2.1");
  expect(state.uploads).toEqual([]); expect(state.businessWrites).toEqual([]);
});

test("麦克风采集须主动授权，切换患者立即停止并丢弃未登记录音", async ({ page }) => {
  const state = await session(page, { microphone: true });
  await page.goto("/#/ai/workbench");
  const patient = page.getByRole("combobox", { name: "患者", exact: true });
  await patient.press("ArrowDown"); await page.getByRole("option", { name: "测试患者甲 · #1", exact: true }).click();
  const input = page.getByLabel("医疗录音登记与选择", { exact: true });
  await input.getByText("登记新录音或使用麦克风采集", { exact: true }).click();
  await expect(input.getByRole("button", { name: "开始录音", exact: true })).toBeDisabled(); expect(await page.evaluate(() => window.__recordingStarts)).toBe(0);
  await authorize(input); await input.getByRole("button", { name: "开始录音", exact: true }).click();
  await expect(input.getByRole("button", { name: "停止录音", exact: true })).toBeVisible();
  await patient.press("ArrowDown"); await page.getByRole("option", { name: "测试患者乙 · #2", exact: true }).click();
  await expect.poll(() => page.evaluate(() => window.__stoppedTracks)).toBeGreaterThan(0);
  await expect(input.getByRole("button", { name: "停止录音", exact: true })).toHaveCount(0);
  await expect(input.getByRole("button", { name: "登记所选录音", exact: true })).toBeDisabled(); expect(state.uploads).toEqual([]); expect(state.submissions).toEqual([]);
});

test("上传后切换患者，迟到回执不绑定新患者且不会自动转写", async ({ page }) => {
  const state = await session(page, { holdUpload: true });
  await page.goto("/#/ai/workbench");
  const patient = page.getByRole("combobox", { name: "患者", exact: true });
  await patient.press("ArrowDown"); await page.getByRole("option", { name: "测试患者甲 · #1", exact: true }).click();
  const input = page.getByLabel("医疗录音登记与选择", { exact: true });
  await input.getByText("登记新录音或使用麦克风采集", { exact: true }).click();
  await input.getByLabel("选择授权录音文件", { exact: true }).setInputFiles({ name: "test.wav", mimeType: "audio/wav", buffer: raw }); await authorize(input);
  await input.getByRole("button", { name: "登记所选录音", exact: true }).click(); await expect.poll(() => !!state.releaseUpload).toBe(true);
  await patient.press("ArrowDown"); await page.getByRole("option", { name: "测试患者乙 · #2", exact: true }).click();
  state.releaseUpload();
  await expect(page.getByText("登记请求已完成，当前患者已切换；请返回原患者核对录音目录", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "生成辅助建议", exact: true })).toBeDisabled(); expect(state.submissions).toEqual([]);
});

test("超级管理员查看原授权、按版本撤回与清除录音，全程不调用模型", async ({ page }) => {
  const state = await session(page, { role: "super_admin", existing: true });
  await page.goto("/#/ai/manage"); await page.getByRole("tab", { name: "录音治理", exact: true }).click();
  await page.getByRole("button", { name: "查看授权与原音", exact: true }).click();
  const detail = page.getByRole("dialog", { name: "原录音登记与授权核对", exact: true });
  await expect(detail).toContainText("原授权说明 <img src=x onerror=alert(1)>"); await expect(detail.locator("img")).toHaveCount(0);
  await detail.getByRole("button", { name: "关闭", exact: true }).click();
  await page.getByRole("button", { name: "撤回", exact: true }).click();
  let box = page.locator(".el-message-box:visible"); await box.locator("input").fill("已核实本次测试录音的明确撤回请求"); await box.getByRole("button", { name: "撤回录音", exact: true }).click();
  await expect.poll(() => state.withdrawals.length).toBe(1); expect(state.withdrawals[0].expected_revision).toBe(1);
  await page.getByRole("button", { name: "清除原文件", exact: true }).click();
  box = page.locator(".el-message-box:visible"); await box.locator("input").fill("按核实的清除请求移除当前存储原文件"); await box.getByRole("button", { name: "清除原文件", exact: true }).click();
  await expect.poll(() => state.purges.length).toBe(1); expect(state.purges[0].expected_revision).toBe(2);
  await expect(page.getByRole("cell", { name: "原文件已清除", exact: true })).toBeVisible(); expect(state.submissions).toEqual([]); expect(state.contentReads).toEqual([]);
});
