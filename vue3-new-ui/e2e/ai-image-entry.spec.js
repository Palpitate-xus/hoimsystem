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
  await expect(result.getByRole("row").filter({ hasText: "隔离测试图像级候选" }).getByRole("cell", { name: "0", exact: true })).toBeVisible();
  await expect(result).toContainText("<img src=x onerror=alert(1)>"); await expect(result.locator(".image-findings img")).toHaveCount(0);
  await result.getByRole("button", { name: "复制影像候选草稿", exact: true }).click();
  await expect.poll(() => page.evaluate(() => window.__copiedImage)).toContain("模型原始分数 0");
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

test("本地胸片研究结果保留18原始标签、实际裁剪与padding计数，显示窗不改变冻结分数", async ({ page }) => {
  const state = await session(page, { existing: true });
  const labels = ["Atelectasis", "Consolidation", "Infiltration", "Pneumothorax", "Edema", "Emphysema", "Fibrosis", "Effusion", "Pneumonia", "Pleural_Thickening", "Cardiomegaly", "Nodule", "Mass", "Hernia", "Lung Lesion", "Fracture", "Lung Opacity", "Enlarged Cardiomediastinum"];
  // This separate synthetic source is unsigned and explicitly CHEST/PA, so its
  // declared input is within the fixed local research model's actual profile.
  const values = [0, 1023, 1024, 1025, 2047, 3071], rawPixels = Buffer.alloc(24), rawStored = Buffer.alloc(12);
  values.forEach((value, i) => { rawPixels.writeInt32LE(value, i * 4); rawStored.writeUInt16LE(value, i * 2); });
  function el(group, tag, vr, value) {
    let data;
    if (vr === "US") { data = Buffer.alloc(2); data.writeUInt16LE(value); }
    else if (vr === "UL") { data = Buffer.alloc(4); data.writeUInt32LE(value); }
    else data = Buffer.isBuffer(value) ? value : Buffer.from(value, "ascii");
    if (data.length % 2) data = Buffer.concat([data, Buffer.from([vr === "UI" || ["OW", "OB"].includes(vr) ? 0 : 32])]);
    const long = ["OB", "OW"].includes(vr), header = Buffer.alloc(long ? 12 : 8);
    header.writeUInt16LE(group); header.writeUInt16LE(tag, 2); header.write(vr, 4, 2, "ascii");
    if (long) header.writeUInt32LE(data.length, 8); else header.writeUInt16LE(data.length, 6);
    return Buffer.concat([header, data]);
  }
  const sop = "1.2.840.10008.5.1.4.1.1.1.1", instance = "2.25.111222333444555666777888999";
  const fileMeta = Buffer.concat([el(2, 1, "OB", Buffer.from([0, 1])), el(2, 2, "UI", sop), el(2, 3, "UI", instance), el(2, 16, "UI", "1.2.840.10008.1.2.1"), el(2, 18, "UI", "2.25.9876543210123456789")]);
  const sourceFile = Buffer.concat([Buffer.alloc(128), Buffer.from("DICM"), el(2, 0, "UL", fileMeta.length), fileMeta,
    el(8, 22, "UI", sop), el(8, 24, "UI", instance), el(8, 96, "CS", "DX"), el(24, 21, "CS", "CHEST"), el(24, 20737, "CS", "PA"),
    el(32, 13, "UI", "2.25.111222333444555666777"), el(32, 14, "UI", "2.25.111222333444555666778"),
    el(40, 2, "US", 1), el(40, 4, "CS", "MONOCHROME2"), el(40, 16, "US", 2), el(40, 17, "US", 3), el(40, 256, "US", 16), el(40, 257, "US", 12), el(40, 258, "US", 11), el(40, 259, "US", 0), el(40, 288, "US", 0),
    el(40, 769, "CS", "NO"), el(40, 4176, "DS", "2048"), el(40, 4177, "DS", "4096"), el(40, 4178, "DS", "0"), el(40, 4179, "DS", "1"), el(32736, 16, "OW", rawStored)]);
  const pHash = digest(rawPixels), oHash = digest(sourceFile), combined = digest(JSON.stringify({ format: "dicom_i32le_v1", original_hash: oHash, pixel_hash: pHash })), sourceReference = `image:${assetId}:${combined.slice(0, 12)}`;
  const source = { asset_id: assetId, patient_id: 1, imaging_order_id: orderId, encounter_ref: null, content_hash: combined, original_hash: oHash, pixel_hash: pHash, byte_size: sourceFile.length + rawPixels.length, original_byte_size: sourceFile.length, pixel_byte_size: rawPixels.length, status: "ready", revision: 1, recorded_at: null, order_status: 0, can_withdraw: false, source_id: sourceReference,
    image_metadata: { format: "dicom_i32le_v1", rows: 2, columns: 3, frames: 1, bits_allocated: 16, bits_stored: 12, high_bit: 11, pixel_representation: 0, photometric_interpretation: "MONOCHROME2", invert_display: false, rescale_slope: 1, rescale_intercept: 0, modality: "DX", body_part_examined: "CHEST", view_position: "PA", burned_in_annotation: "NO", voi_lut_function: "LINEAR", window_presets: [{ center: 2048, width: 4096 }], padding: { value: 0, range_limit: 0 }, valid_min_stored: 1023, valid_max_stored: 3071, valid_pixel_count: 5, pixel_spacing_mm: null, imager_pixel_spacing_mm: null } };
  Object.assign(source.image_metadata, { transfer_syntax_uid: "1.2.840.10008.1.2.1", sop_class_uid: sop, rescale_declared: true, rescale_type: "unknown", presentation_lut_shape: "not_declared", presentation_intent_type: "not_declared", image_laterality: "unknown", coordinate_space: "source_pixels", orientation: "stored_row_column_unmodified", study_uid_hash: digest("2.25.111222333444555666777"), series_uid_hash: digest("2.25.111222333444555666778"), instance_uid_hash: digest(instance) });
  const preprocessing = { profile: "xrv_stored_range_v1", input_profile: { format: "dicom_i32le_v1", modalities: ["CR", "DX"], body_part_examined: "CHEST", view_positions: ["PA", "AP"], frames: 1, pixel_representation: "unsigned", bits_allocated: [8, 16], bits_stored_min: 8, bits_stored_max: 16, rescale_slope: 1, rescale_intercept: 0, presentation_intent_type: ["FOR PRESENTATION", "not_declared"], population_applicability: "not_verified", clinical_validation: "not_provided" }, source_code_revision: "17726dd8f5e756eec3e5ae958281a289b05b1dae", normalization: "(2*(stored.astype(numpy.float32)/((1<<BitsStored)-1))-1)*1024", normalization_range: [-1024, 1024], monochrome1: "maxval-stored before normalization; exactly one inversion", crop: "center square: side=min(rows,columns); x=columns//2-side//2; y=rows//2-side//2", resize: { size: [224, 224], mode: "bilinear", align_corners: false, antialias: true, skip_if_already_224: true }, padding_policy: "preserved_as_original_background", constant_valid_crop_policy: "reject", voi_window_policy: "ignored_for_research_input_not_diagnostic_display", modality_lut: "unsupported; identity rescale only", histogram_equalization: false, image_minmax_normalization: false, rotation: false, flipping: false, imputation: false, training_distribution_equivalence: "not_established", spatial_localization: false };
  const runtime = { engine: "torchxrayvision-densenet121", engine_versions: { torch: "2.14.1+cpu", numpy: "2.4.4", safetensors: "0.8.0" }, model_repository: "torchxrayvision/densenet121-res224-all", model_revision: "588eadcc6a744da71f8dce768bc974ec629443f5", model_digest: "b".repeat(64), runtime_digest: "c".repeat(64), preprocessing_digest: "d".repeat(64), profile: "xrv_stored_range_v1", preprocessing, labels, prompt_handling: "pixels_only", clinical_validation: "not_provided", population_applicability: "not_verified" };
  const context = { scope: "native_single_image_analysis", scope_note: "隔离显示测试，未调用实际模型", image_source: source, missing_data: ["采集时人群及临床适用性未核实"] };
  const evidence = [{ source_id: sourceReference, kind: "image_asset", title: "合成原图依据", content: "合成技术参数，无临床结论" }];
  const findings = labels.map((label, index) => ({ label, description: "隔离页面测试的独立模型分数，无临床含义", location: "image", region: null, score: index === 0 ? 0 : index / 18, score_kind: "model_score", source_id: sourceReference }));
  const localPreprocessing = { normalization_maxval: 4095, input_pixel_count: 6, cropped_pixel_count: 4, discarded_pixel_count: 2, padding_pixels_in_input: 1, padding_pixels_in_crop: 1, valid_pixels_in_crop: 3, prepared_shape: [1, 1, 224, 224], prepared_min: -1024, prepared_max: Math.fround(Math.fround(Math.fround(2047 / 4095) * 2 - 1) * 1024) };
  await page.route("**/api/ai/**", async route => {
    const request = route.request(), path = new URL(request.url()).pathname; let data;
    if (path === "/api/ai/image-assets" && request.method() === "GET") data = { items: [source], truncated: false };
    else if (path === `/api/ai/image-assets/${assetId}`) data = source;
    else if (path === `/api/ai/image-assets/${assetId}/pixels`) { state.pixelReads.push({ token: request.headers().accesstoken, query: new URL(request.url()).search }); await route.fulfill({ status: 200, contentType: "application/octet-stream", body: rawPixels }); return; }
    else if (path === "/api/ai/context") { state.previews.push(request.postDataJSON()); data = { context, evidence }; }
    else if (path === "/api/ai/runs/image-run") data = { run_id: "image-run", feature_name: "医学影像辅助识别", status: "succeeded", patient_id: 1, image_findings: context, evidence, result: { summary: "仅隔离浏览器显示测试，未进行实际影像推理", sections: [], warnings: [], missing_data: [], image_analysis: { asset_id: assetId, content_hash: combined, original_hash: oHash, pixel_hash: pHash, coordinate_space: "source_pixels", processing: { input_rows: 2, input_columns: 3, input_frames: 1, processed_frames: [0], instructions_digest: "a".repeat(64), analysis_region: { x: 0, y: 0, width: 2, height: 2 }, preprocessing_notes: ["原存储范围研究输入，裁剪外未分析"], local_runtime: runtime, local_preprocessing: localPreprocessing }, findings } } };
    else { await route.fallback(); return; }
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ code: 200, msg: "success", data }) });
  });
  const directoryReady = page.waitForResponse(response => {
    const url = new URL(response.url());
    return response.request().method() === "GET" && url.pathname === "/api/ai/image-assets" && url.searchParams.get("patient_id") === "1" && url.searchParams.get("imaging_order_id") === orderId;
  });
  const drawer = await openBusiness(page), input = drawer.getByLabel("原始影像登记与选择", { exact: true });
  const directory = await directoryReady;
  expect(directory.status()).toBe(200);
  expect((await directory.json()).data.items).toMatchObject([{ asset_id: assetId, patient_id: 1, imaging_order_id: orderId, pixel_hash: pHash, content_hash: combined }]);
  const sourceSelect = input.getByRole("combobox", { name: "待复核原始影像", exact: true });
  await expect(sourceSelect).toBeVisible(); await expect(sourceSelect).toBeEnabled();
  await sourceSelect.press("ArrowDown"); await expect(sourceSelect).toHaveAttribute("aria-expanded", "true");
  await page.getByRole("option", { name: /原图 44444444/ }).click();
  await drawer.getByRole("button", { name: "生成辅助建议", exact: true }).click();
  const result = drawer.getByLabel("AI任务结果", { exact: true }), report = result.getByLabel("本地影像研究模型运行记录", { exact: true });
  for (const value of ["torchxrayvision-densenet121", "torch 2.14.1+cpu", "torchxrayvision/densenet121-res224-all", "588eadcc6a744da71f8dce768bc974ec629443f5", "xrv_stored_range_v1", labels.join("、"), "4095（由原BitsStored确定）", "实际裁剪 4 个；裁剪外舍弃 2 个，未分析", "原输入 1 个；实际裁剪内 1 个", "1×1×224×224", "pixels_only：仅所选原像素参与分类", "not_verified：未核实", "not_provided：尚无验证记录", "模型按固定研究配置处理像素", "下方查看器使用DICOM显示窗"]) await expect(report).toContainText(value);
  for (const digest of ["b", "c", "d"]) await expect(report).toContainText(digest.repeat(64));
  await expect(result).toContainText("原坐标 x=0，y=0，宽2，高2");
  await expect(result.getByRole("row").filter({ has: page.getByRole("cell", { name: "Atelectasis", exact: true }) }).getByRole("cell", { name: "0", exact: true })).toBeVisible();
  expect(state.pixelReads).toEqual([]); await result.getByRole("button", { name: "加载原始影像像素", exact: true }).click();
  await expect(result.getByRole("img", { name: "原始行列灰阶影像", exact: true })).toBeVisible();
  await result.getByLabel("影像窗宽WW", { exact: true }).fill("2048"); await result.getByLabel("影像窗宽WW", { exact: true }).blur();
  await expect(result).toContainText("当前为人工调整的显示窗");
  await expect(result.getByRole("row").filter({ has: page.getByRole("cell", { name: "Atelectasis", exact: true }) }).getByRole("cell", { name: "0", exact: true })).toBeVisible();
  expect(state.submissions).toHaveLength(1); expect(state.pixelReads).toEqual([{ token: "isolated-image-test", query: "" }]); expect(state.businessWrites).toEqual([]);
});
