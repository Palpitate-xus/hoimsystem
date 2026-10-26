const { selectManagementTab } = require('./fixtures/ai-management-navigation.cjs');
const { test, expect } = require("@playwright/test");
const { createHash } = require("node:crypto");

const assetId = "44444444-4444-4444-8444-444444444444", orderId = "55555555-5555-4555-8555-555555555555";
const pixels = Buffer.alloc(24);
[-1024, -1, 0, 1, 1023, 2047].forEach((value, index) => pixels.writeInt32LE(value, index * 4));
const pixelHash = createHash("sha256").update(pixels).digest("hex");

async function session(page, { failFirstPurge = false, withdrawn = false } = {}) {
  const state = { lists: [], details: [], pixels: [], withdrawals: [], purges: [], runs: [], writes: [], status: withdrawn ? "withdrawn" : "ready", revision: withdrawn ? 2 : 1, purgeNote: "" };
  const metadata = () => ({
    asset_id: assetId, patient_id: 1, imaging_order_id: orderId, encounter_ref: null, content_hash: "a".repeat(64), original_hash: "b".repeat(64), pixel_hash: pixelHash, byte_size: 1024, original_byte_size: 1000, pixel_byte_size: 24,
    status: state.status, revision: state.revision, created_by: 3, create_time: "2026-10-20T10:00:00", recorded_at: null, order_status: 0, order_modality: "DR", source_order_hash: "d".repeat(64), can_withdraw: state.status === "ready",
    image_metadata: { format: "dicom_i32le_v1", rows: 2, columns: 3, frames: 1, bits_allocated: 16, bits_stored: 12, high_bit: 11, pixel_representation: 1, photometric_interpretation: "MONOCHROME2", invert_display: false, rescale_slope: 1, rescale_intercept: 0, modality: "DX", body_part_examined: "CHEST", view_position: "PA", burned_in_annotation: "unknown", voi_lut_function: "LINEAR", window_presets: [{ center: 0, width: 1024 }], padding: null, valid_min_stored: -1024, valid_max_stored: 2047, valid_pixel_count: 6, pixel_spacing_mm: null, imager_pixel_spacing_mm: null },
  });
  const source = { ...metadata(), status: "ready", revision: 1, source_id: `image:${assetId}:${"a".repeat(12)}` };
  const findings = { scope: "native_single_image_analysis", scope_note: "任务当时的单帧原像素资料，不代表完整检查", image_source: source, missing_data: ["采集时人群未核实"] };
  const analysis = { asset_id: assetId, content_hash: source.content_hash, original_hash: source.original_hash, pixel_hash: pixelHash, coordinate_space: "source_pixels", processing: { input_rows: 2, input_columns: 3, input_frames: 1, processed_frames: [0], instructions_digest: "f".repeat(64), analysis_region: { x: 1, y: 0, width: 2, height: 2 }, preprocessing_notes: ["冻结的实际裁剪说明"] }, findings: [{ label: "历史整图候选", description: "隔离测试，不是实际医学识别", location: "image", region: null, score: 0, score_kind: "model_score", source_id: source.source_id }] };
  await page.addInitScript(() => localStorage.setItem("hoim-token", "isolated-image-admin-test"));
  await page.route("**/api/**", async route => {
    const request = route.request(), url = new URL(request.url()), path = url.pathname, method = request.method();
    let data = [], total;
    if (path === "/api/userInfo") data = { username: "影像治理测试", permissions: ["super_admin", "admin"], avatar: "" };
    if (path === "/api/ai/admin/image-assets") { state.lists.push(Object.fromEntries(url.searchParams)); data = { items: [metadata()], truncated: false }; }
    if (path === `/api/ai/image-assets/${assetId}`) { state.details.push(assetId); data = { ...metadata(), authorization_note: "原来源核对说明 <img src=x onerror=alert(1)>", withdrawal_note: state.status === "ready" ? "" : "已核对的原撤回原因", purge_note: state.purgeNote }; }
    if (path === `/api/ai/image-assets/${assetId}/pixels`) {
      state.pixels.push({ token: request.headers().accesstoken, query: url.search });
      await route.fulfill({ status: 200, contentType: "application/octet-stream", body: pixels }); return;
    }
    if (path === `/api/ai/image-assets/${assetId}/withdraw`) { state.withdrawals.push(request.postDataJSON()); state.status = "withdrawn"; state.revision = 2; data = metadata(); }
    if (path === `/api/ai/admin/image-assets/${assetId}/purge`) {
      const body = request.postDataJSON(); state.purges.push(body);
      if (!state.purgeNote) state.purgeNote = body.reason;
      if (failFirstPurge && state.purges.length === 1) { state.status = "purge_pending"; state.revision = 3; await route.fulfill({ status: 503, contentType: "application/json", body: JSON.stringify({ detail: "隔离测试存储暂不可用，原请求保留" }) }); return; }
      state.status = "purged"; state.revision = 4; data = metadata();
    }
    if (path === "/api/ai/admin/runs") { data = [{ run_id: "image-frozen-run", feature_key: "imaging_detection", feature_name: "医学影像辅助识别", status: "succeeded", patient_id: 1, requested_by: 3, create_time: "2026-10-20T10:01:00" }]; total = 1; }
    if (path === "/api/ai/admin/runs/image-frozen-run") data = { run_id: "image-frozen-run", feature_key: "imaging_detection", feature_name: "医学影像辅助识别", status: "succeeded", patient_id: 1, requested_by: 3, snapshot_complete: true, image_findings: findings, result: { summary: "冻结候选仅供原任务审计", sections: [], warnings: [], missing_data: [], image_analysis: analysis }, evidence: [] };
    if (path === "/api/ai/runs" && method === "POST") state.runs.push(request.postDataJSON());
    if (method !== "GET" && /^\/api\/(imaging|medicalRecord|prescription|inpatient|admission|lab)(\/|$)/.test(path)) state.writes.push(path);
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ code: 200, msg: "success", data, ...(total == null ? {} : { total }) }) });
  });
  return state;
}

test("超管按患者过滤原图，核对授权时不自动读取像素，显式加载保留私有鉴权", async ({ page }) => {
  const state = await session(page);
  await page.goto("/#/ai/manage"); await selectManagementTab(page, '影像原文件');
  const governance = page.getByLabel("AI影像原文件治理", { exact: true });
  await governance.getByRole("spinbutton", { name: "影像治理患者ID", exact: true }).fill("1");
  await governance.getByRole("button", { name: "查询影像原文件", exact: true }).click();
  await expect.poll(() => state.lists.some(query => query.patient_id === "1")).toBe(true);
  await governance.getByRole("button", { name: "核对授权与原像素", exact: true }).click();
  const detail = page.getByRole("dialog", { name: "原始影像登记与授权核对", exact: true });
  await expect(detail).toContainText("原来源核对说明 <img src=x onerror=alert(1)>");
  await expect(detail).toContainText(orderId); await expect(detail).toContainText("未记录，不按日期推定");
  await expect(detail.locator("img")).toHaveCount(0); expect(state.pixels).toEqual([]);
  await detail.getByRole("button", { name: "加载原始影像像素", exact: true }).click();
  await expect(detail.getByRole("img", { name: "原始行列灰阶影像", exact: true })).toBeVisible();
  await expect(detail).toContainText("标签不证明像素已匿名化");
  expect(state.pixels).toEqual([{ token: "isolated-image-admin-test", query: "" }]);
  expect(state.runs).toEqual([]); expect(state.writes).toEqual([]);
});

test("超管按版本撤回原图，清除失败恢复时保留首次原因且不调用模型", async ({ page }) => {
  const state = await session(page, { failFirstPurge: true });
  await page.goto("/#/ai/manage"); await selectManagementTab(page, '影像原文件');
  await page.getByRole("button", { name: "撤回", exact: true }).click();
  let box = page.locator(".el-message-box:visible"); await box.locator("input").fill("已核对登记人与患者的原图撤回请求"); await box.getByRole("button", { name: "撤回原影像", exact: true }).click();
  await expect.poll(() => state.withdrawals.length).toBe(1); expect(state.withdrawals[0]).toEqual({ expected_revision: 1, reason: "已核对登记人与患者的原图撤回请求" });
  await page.getByRole("button", { name: "清除原文件", exact: true }).click();
  box = page.locator(".el-message-box:visible"); await box.locator("input").fill("首次清除当前存储原DICOM与派生像素的请求"); await box.getByRole("button", { name: "清除原文件", exact: true }).click();
  await expect(page.getByRole("button", { name: "继续清除", exact: true })).toBeVisible(); expect(state.purges[0].expected_revision).toBe(2);
  await page.getByRole("button", { name: "核对授权与原像素", exact: true }).click();
  const detail = page.getByRole("dialog", { name: "原始影像登记与授权核对", exact: true });
  await expect(detail).toContainText("首次清除当前存储原DICOM与派生像素的请求");
  await expect(detail.getByRole("button", { name: "加载原始影像像素", exact: true })).toHaveCount(0); await detail.getByRole("button", { name: "关闭", exact: true }).click();
  await page.getByRole("button", { name: "继续清除", exact: true }).click();
  box = page.locator(".el-message-box:visible"); await box.locator("input").fill("恢复同一清除请求并保留首次原因"); await box.getByRole("button", { name: "清除原文件", exact: true }).click();
  await expect(page.getByRole("cell", { name: "原文件已清除", exact: true })).toBeVisible();
  expect(state.purges[1].expected_revision).toBe(3); expect(state.purgeNote).toBe("首次清除当前存储原DICOM与派生像素的请求");
  expect(state.runs).toEqual([]); expect(state.pixels).toEqual([]); expect(state.writes).toEqual([]);
});

test("超管查看冻结任务原版本与实际裁剪，当前原图已撤回不替换历史候选", async ({ page }) => {
  const state = await session(page, { withdrawn: true });
  await page.goto("/#/ai/manage"); await selectManagementTab(page, '任务与反馈');
  await page.getByRole("button", { name: "执行溯源", exact: true }).click();
  const trace = page.getByRole("dialog", { name: "AI 任务执行溯源", exact: true });
  await expect(trace).toContainText("任务当时原版本 1"); await expect(trace).toContainText("原坐标 x=1，y=0，宽2，高2");
  await expect(trace).toContainText("图像级，未提供病灶定位");
  await expect(trace.getByRole("row").filter({ hasText: "历史整图候选" }).getByRole("cell", { name: "0 非患病概率", exact: true })).toBeVisible();
  expect(state.revision).toBe(2); expect(state.pixels).toEqual([]); expect(state.runs).toEqual([]); expect(state.writes).toEqual([]);
});
