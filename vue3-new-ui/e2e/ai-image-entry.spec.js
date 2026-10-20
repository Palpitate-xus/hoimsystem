const { test, expect } = require("@playwright/test");
const { createHash } = require("node:crypto");

const assetId = "44444444-4444-4444-8444-444444444444", orderId = "55555555-5555-4555-8555-555555555555", secondOrder = "66666666-6666-4666-8666-666666666666";
const samples = [-1024, -1, 0, 1, 1023, 2047], pixels = Buffer.alloc(samples.length * 4);
samples.forEach((value, index) => pixels.writeInt32LE(value, index * 4));
const digest = value => createHash("sha256").update(value).digest("hex");

function syntheticDicom() {
  // A real, small Part10 DX file. No real patient data or remote image service.
  const sop = "1.2.840.10008.5.1.4.1.1.1.1", instance = "2.25.123456789012345678901234567890123456";
  function element(group, tag, vr, value) {
    let data;
    if (vr === "US") { data = Buffer.alloc(2); data.writeUInt16LE(value); }
    else if (vr === "UL") { data = Buffer.alloc(4); data.writeUInt32LE(value); }
    else data = Buffer.isBuffer(value) ? value : Buffer.from(value, "ascii");
    if (data.length % 2) data = Buffer.concat([data, Buffer.from([vr === "UI" || vr === "OB" || vr === "OW" ? 0 : 32])]);
    const long = ["OB", "OW"].includes(vr), header = Buffer.alloc(long ? 12 : 8);
    header.writeUInt16LE(group, 0); header.writeUInt16LE(tag, 2); header.write(vr, 4, 2, "ascii");
    if (long) header.writeUInt32LE(data.length, 8); else header.writeUInt16LE(data.length, 6);
    return Buffer.concat([header, data]);
  }
  const meta = Buffer.concat([element(2, 1, "OB", Buffer.from([0, 1])), element(2, 2, "UI", sop), element(2, 3, "UI", instance), element(2, 16, "UI", "1.2.840.10008.1.2.1"), element(2, 18, "UI", "2.25.9876543210123456789")]);
  const raw = Buffer.alloc(samples.length * 2); samples.forEach((value, index) => raw.writeUInt16LE((value & 0x0fff) | 0x5000, index * 2));
  return Buffer.concat([Buffer.alloc(128), Buffer.from("DICM"), element(2, 0, "UL", meta.length), meta,
    element(8, 22, "UI", sop), element(8, 24, "UI", instance), element(8, 96, "CS", "DX"), element(16, 16, "PN", "SYNTHETIC^PRIVATE_NAME"), element(16, 32, "LO", "SYNTHETIC_PRIVATE_ID"),
    element(32, 13, "UI", "2.25.123456789012345678901"), element(32, 14, "UI", "2.25.123456789012345678902"),
    element(40, 2, "US", 1), element(40, 4, "CS", "MONOCHROME2"), element(40, 16, "US", 2), element(40, 17, "US", 3), element(40, 256, "US", 16), element(40, 257, "US", 12), element(40, 258, "US", 11), element(40, 259, "US", 1),
    element(40, 769, "CS", "NO"), element(40, 4176, "DS", "0"), element(40, 4177, "DS", "1024"), element(40, 4178, "DS", "0"), element(40, 4179, "DS", "1"), element(32736, 16, "OW", raw)]);
}
const original = syntheticDicom(), pixelHash = digest(pixels), originalHash = digest(original), contentHash = digest(JSON.stringify({ format: "dicom_i32le_v1", original_hash: originalHash, pixel_hash: pixelHash })), sourceId = `image:${assetId}:${contentHash.slice(0, 12)}`;

async function session(page, { existing = false, holdUpload = false, allPadding = false } = {}) {
  const state = { uploads: [], previews: [], submissions: [], pixelReads: [], businessWrites: [], exists: existing, releaseUpload: null };
  const metadata = () => ({
    asset_id: assetId, patient_id: 1, imaging_order_id: orderId, encounter_ref: null, content_hash: contentHash, original_hash: originalHash, pixel_hash: pixelHash, byte_size: original.length + pixels.length, original_byte_size: original.length, pixel_byte_size: pixels.length, status: "ready", revision: 1, created_by: 3, create_time: "2026-10-20T10:00:00", recorded_at: null, order_status: 0, order_modality: "DR", source_order_hash: "d".repeat(64), can_withdraw: false,
    image_metadata: { format: "dicom_i32le_v1", rows: 2, columns: 3, frames: 1, bits_allocated: 16, bits_stored: 12, high_bit: 11, pixel_representation: 1, photometric_interpretation: "MONOCHROME2", invert_display: false, rescale_slope: 1, rescale_intercept: 0, modality: "DX", body_part_examined: "CHEST", view_position: "PA", burned_in_annotation: "NO", voi_lut_function: "LINEAR", window_presets: [{ center: 0, width: 1024 }], padding: allPadding ? { value: -2048, range_limit: 2047 } : null, valid_min_stored: allPadding ? null : -1024, valid_max_stored: allPadding ? null : 2047, valid_pixel_count: allPadding ? 0 : 6, pixel_spacing_mm: null, imager_pixel_spacing_mm: null },
  });
  const source = { ...metadata(), source_id: sourceId }, context = { scope: "native_single_image_analysis", scope_note: "仅所选单帧原像素，不代表完整检查；不按今天年龄推定采集人群", image_source: source, missing_data: ["采集时人群与适用范围未核实", "原采集时刻未核实"] };
  const evidence = [{ source_id: sourceId, kind: "image_asset", title: "原像素元数据依据", content: "固定原像素哈希，不包含原DICOM患者标签或其他病史" }];
  const analysis = { asset_id: assetId, content_hash: contentHash, original_hash: originalHash, pixel_hash: pixelHash, coordinate_space: "source_pixels", processing: { input_rows: 2, input_columns: 3, input_frames: 1, processed_frames: [0], instructions_digest: "f".repeat(64), analysis_region: { x: 1, y: 0, width: 2, height: 2 }, preprocessing_notes: ["模拟实际裁剪，不能声称分析了裁剪外区域"] }, findings: [{ label: "隔离测试图像级候选", description: "<img src=x onerror=alert(1)> 仅合成协议测试，无临床含义", location: "image", region: null, score: 0, score_kind: "model_score", source_id: sourceId }] };
  const feature = { number: 36, key: "imaging_detection", name: "医学影像辅助识别", scope: "patient", engine: "vision", category: "diagnostics", enabled: true, validation_status: "validated", inputs: ["DICOM原像素及真实申请"], deliverables: ["待复核候选与实际处理区域"], source_reference_keys: ["image_asset_id", "imaging_order_id"], default_roles: ["super_admin", "doctor", "director", "lab_technician"], allowed_roles: ["doctor"], setup_check: { ready: true, issues: [] } };
  await page.addInitScript(() => {
    localStorage.setItem("hoim-token", "isolated-image-test"); window.__copiedImage = "";
    Object.defineProperty(navigator, "clipboard", { configurable: true, value: { writeText: async text => { window.__copiedImage = text; } } });
  });
  await page.route("**/api/**", async route => {
    const request = route.request(), url = new URL(request.url()), path = url.pathname, method = request.method(); let data = [];
    if (path === "/api/userInfo") data = { username: "影像入口测试", permissions: ["doctor"], avatar: "" };
    if (path === "/api/ai/features") data = [feature];
    if (path === "/api/imaging/order/list") data = [{ imaging_order_id: orderId, patient_id: 1, patient_name: "测试患者甲", modality: "DR", body_part: "合成胸部", status: 0, status_text: "待检查", accession_no: "SYNTH-ORDER", viewer_url: "https://example.invalid/viewer-only", report: { report_id: "report-not-a-pixel", findings: "报告不是原图" } }];
    if (path === "/api/ai/patients") data = [{ patient_id: 1, label: "测试患者甲 · #1" }, { patient_id: 2, label: "测试患者乙 · #2" }];
    if (path === "/api/ai/encounters") data = [];
    if (path === "/api/ai/image-options") data = { max_bytes: 67108864, max_pixels: 16777216, user_quota_bytes: 1073741824, used_bytes: 0, scope_note: "当前诊疗成员核对原图，登记与复核不调用模型" };
    if (path === "/api/ai/image-orders") { const patient = Number(url.searchParams.get("patient_id")); data = { items: [{ imaging_order_id: patient === 1 ? orderId : secondOrder, patient_id: patient, modality: "DR", body_part: "合成胸部", accession_no: patient === 1 ? "SYNTH-ORDER" : "SYNTH-SECOND", status: 0 }], truncated: false, scope_note: "申请未保存就诊关联，不按日期推定" }; }
    if (path === "/api/ai/image-assets" && method === "POST") {
      state.uploads.push({ type: request.headers()["content-type"], body: request.postDataBuffer() });
      if (holdUpload) await new Promise(resolve => { state.releaseUpload = resolve; }); state.exists = true; data = metadata();
    }
    if (path === "/api/ai/image-assets" && method === "GET") data = { items: state.exists && url.searchParams.get("patient_id") === "1" && url.searchParams.get("imaging_order_id") === orderId ? [metadata()] : [], truncated: false };
    if (path === `/api/ai/image-assets/${assetId}`) data = metadata();
    if (path === `/api/ai/image-assets/${assetId}/pixels`) { state.pixelReads.push({ token: request.headers().accesstoken, query: url.search }); await route.fulfill({ status: 200, contentType: "application/octet-stream", body: pixels }); return; }
    if (path === "/api/ai/context") { state.previews.push(request.postDataJSON()); data = { context, evidence }; }
    if (path === "/api/ai/runs" && method === "POST") { state.submissions.push(request.postDataJSON()); data = { run_id: "image-run", feature_name: feature.name, status: "queued", patient_id: 1 }; }
    if (path === "/api/ai/runs/image-run") data = { run_id: "image-run", feature_name: feature.name, status: "succeeded", patient_id: 1, image_findings: context, evidence, result: { summary: "隔离候选草稿，未调用真实医学模型", sections: [], warnings: [], missing_data: [], image_analysis: analysis } };
    if (method !== "GET" && /^\/api\/(imaging|medicalRecord|prescription|inpatient|admission|lab)(\/|$)/.test(path)) state.businessWrites.push(path);
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ code: 200, msg: "success", data }) });
  });
  return state;
}

async function upload(input) {
  await input.getByText("登记单帧DICOM原始影像", { exact: true }).click();
  await input.getByLabel("选择原始DICOM文件", { exact: true }).setInputFiles({ name: "synthetic-private-source.dcm", mimeType: "application/dicom", buffer: original });
  await input.getByRole("textbox", { name: "原影像来源与授权核对说明", exact: true }).fill("已核对本次合成DICOM与所选患者和原申请的来源关联及处理授权");
  await input.getByText("我已核对来源、使用授权、患者与原影像申请及所选就诊的关联", { exact: true }).click();
  await input.getByRole("button", { name: "登记原始影像", exact: true }).click();
}

async function openBusiness(page) {
  await page.goto("/#/lab/imaging"); await page.getByRole("button", { name: "AI 原影像复核", exact: true }).click();
  return page.getByRole("dialog", { name: "影像辅助识别与原像素复核", exact: true });
}

test("真实影像申请入口上传原DICOM，预览及任务绑定同一像素并保留零分与真实裁剪", async ({ page }, testInfo) => {
  const state = await session(page), drawer = await openBusiness(page), input = drawer.getByLabel("原始影像登记与选择", { exact: true });
  await expect(drawer.getByRole("combobox", { name: "患者", exact: true })).toBeDisabled();
  await expect(input.getByRole("combobox", { name: "原始影像申请", exact: true })).toBeDisabled();
  await expect(drawer.getByRole("button", { name: "生成辅助建议", exact: true })).toBeDisabled();
  await upload(input); await expect.poll(() => state.uploads.length).toBe(1);
  expect(state.uploads[0].type).toContain("multipart/form-data; boundary="); expect(state.uploads[0].body.includes(original)).toBe(true);
  expect(state.uploads[0].body.toString()).toContain(orderId); expect(state.uploads[0].body.toString()).not.toContain('name="encounter_ref"');
  expect(state.submissions).toEqual([]); expect(state.pixelReads).toEqual([]);
  await drawer.getByRole("button", { name: "查看本次资料", exact: true }).click();
  const preview = page.getByRole("dialog", { name: "本次提供给 AI 的患者资料", exact: true });
  await expect(preview).toContainText("采集时人群与适用范围未核实"); expect(state.pixelReads).toEqual([]);
  await preview.getByRole("button", { name: "加载原始影像像素", exact: true }).click();
  const canvas = preview.getByRole("img", { name: "原始行列灰阶影像", exact: true });
  await expect(canvas).toHaveAttribute("data-source-asset-id", assetId);
  await expect.poll(async () => canvas.evaluate(element => { const data = element.getContext("2d").getImageData(0, 0, element.width, element.height).data; let gray = 0; for (let i = 0; i < data.length; i += 4) if (data[i] > 0 && data[i] < 255 && data[i] === data[i + 1] && data[i] === data[i + 2]) gray++; return gray; })).toBeGreaterThan(100);
  expect(state.pixelReads).toEqual([{ token: "isolated-image-test", query: "" }]);
  await canvas.screenshot({ path: testInfo.outputPath("synthetic-source-image.png") });
  await preview.locator("button.el-dialog__headerbtn").click();
  await drawer.getByRole("button", { name: "生成辅助建议", exact: true }).click();
  await expect.poll(() => state.submissions.length).toBe(1);
  expect(state.previews[0]).toMatchObject({ patient_id: 1, source_refs: { image_asset_id: assetId, imaging_order_id: orderId } });
  expect(state.submissions[0]).toMatchObject({ patient_id: 1, input: { image_asset_id: assetId, imaging_order_id: orderId } });
  for (const key of ["imaging_report_id", "report_id", "viewer_url", "record_id"]) expect(state.submissions[0].input[key]).toBeUndefined();
  const result = drawer.getByLabel("AI任务结果", { exact: true });
  await expect(result).toContainText("实际分析范围：原坐标 x=1，y=0，宽2，高2"); await expect(result).toContainText("图像级，未提供病灶定位");
  await expect(result.getByRole("row").filter({ hasText: "隔离测试图像级候选" }).getByRole("cell", { name: "0 非患病概率", exact: true })).toBeVisible();
  await expect(result).toContainText("<img src=x onerror=alert(1)>"); await expect(result.locator(".image-findings img")).toHaveCount(0);
  await result.getByRole("button", { name: "复制影像候选草稿", exact: true }).click();
  await expect.poll(() => page.evaluate(() => window.__copiedImage)).toContain("模型原始分数 0（非患病概率）");
  const copied = await page.evaluate(() => window.__copiedImage); expect(copied).toContain(pixelHash); expect(copied).toContain("图像级，未提供病灶定位"); expect(copied).toContain('"x":1');
  expect(state.businessWrites).toEqual([]);
});

test("上传期间切换患者清除文件与授权，迟到原图不会绑定新患者或触发推理", async ({ page }) => {
  const state = await session(page, { holdUpload: true });
  await page.goto("/#/ai/workbench");
  const patient = page.getByRole("combobox", { name: "患者", exact: true }); await patient.press("ArrowDown"); await page.getByRole("option", { name: "测试患者甲 · #1", exact: true }).click();
  const input = page.getByLabel("原始影像登记与选择", { exact: true });
  await input.getByRole("combobox", { name: "原始影像申请", exact: true }).press("ArrowDown"); await page.getByRole("option", { name: /SYNTH-ORDER/ }).click();
  await upload(input); await expect.poll(() => !!state.releaseUpload).toBe(true);
  await patient.press("ArrowDown"); await page.getByRole("option", { name: "测试患者乙 · #2", exact: true }).click(); state.releaseUpload();
  await expect(page.getByText("原图登记已完成，当前患者、申请或就诊已切换；请返回原范围核对目录", { exact: true })).toBeVisible();
  await expect(input.getByRole("textbox", { name: "原影像来源与授权核对说明", exact: true })).toHaveValue("");
  await expect(input.getByLabel("选择原始DICOM文件", { exact: true })).toHaveJSProperty("value", "");
  await expect(input.getByRole("button", { name: "登记原始影像", exact: true })).toBeDisabled();
  await expect(page.getByRole("button", { name: "生成辅助建议", exact: true })).toBeDisabled();
  expect(state.submissions).toEqual([]); expect(state.pixelReads).toEqual([]); expect(state.businessWrites).toEqual([]);
});

test("诊疗团队可选他人登记原图但不能撤回，全填充值原图只复核不生成", async ({ page }) => {
  const state = await session(page, { existing: true, allPadding: true }), drawer = await openBusiness(page), input = drawer.getByLabel("原始影像登记与选择", { exact: true });
  const source = input.getByRole("combobox", { name: "待复核原始影像", exact: true }); await expect(source).toBeEnabled(); await source.press("ArrowDown"); await page.getByRole("option", { name: /原图 44444444/ }).click();
  await expect(input).toContainText("原图全部为填充值");
  await expect(input.getByRole("button", { name: "撤回所选原始影像", exact: true })).toHaveCount(0);
  await expect(drawer.getByRole("button", { name: "生成辅助建议", exact: true })).toBeDisabled();
  await input.getByRole("button", { name: "查看所选原始影像", exact: true }).click();
  await expect(page.getByRole("dialog", { name: "所选单帧原始影像", exact: true })).toBeVisible();
  expect(state.submissions).toEqual([]); expect(state.pixelReads).toEqual([]);
});
