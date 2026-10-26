const { selectManagementTab } = require('./fixtures/ai-management-navigation.cjs');
const { test, expect } = require("@playwright/test");

const labels = ["Atelectasis", "Consolidation", "Infiltration", "Pneumothorax", "Edema", "Emphysema", "Fibrosis", "Effusion", "Pneumonia", "Pleural_Thickening", "Cardiomegaly", "Nodule", "Mass", "Hernia", "Lung Lesion", "Fracture", "Lung Opacity", "Enlarged Cardiomediastinum"];
const model = id => `xrv:${String(id).repeat(64)}`;

async function session(page, { holdFirst = false, receiptMismatch = "", configuredMatching = false } = {}) {
  const state = { checks: [], completed: [], writes: [], featureWrites: [], runs: [], release: null };
  const providers = [1, 2].map(id => ({ provider_id: id, revision: 3, name: `本地影像${id === 1 ? "甲" : "乙"}`, model: configuredMatching ? model(id) : "登记的旧模型", kind: "specialist", api_base: "http://localhost:8812", enabled: false, allows_patient_data: false, timeout_seconds: 30, max_output_tokens: 2000, supported_features: ["imaging_detection"], has_api_key: true, validation_report: "隔离界面测试，未进行临床质量验证" }));
  providers.push({ provider_id: 3, revision: 1, name: "普通文本服务", model: "text-only", kind: "chat", api_base: "http://localhost:8812", enabled: false, supported_features: ["imaging_detection"] });
  await page.addInitScript(() => localStorage.setItem("hoim-token", "isolated-image-admin-test"));
  await page.route("**/api/**", async route => {
    const request = route.request(), path = new URL(request.url()).pathname, method = request.method();
    let data = [], checkedId = null;
    if (path === "/api/userInfo") data = { username: "影像模型管理测试", permissions: ["super_admin", "admin"], avatar: "" };
    if (path === "/api/ai/admin/providers") data = providers;
    const match = path.match(/^\/api\/ai\/admin\/providers\/(\d+)\/image-capabilities$/);
    if (match) {
      const id = Number(match[1]); checkedId = id;
      state.checks.push({ id, method, ...request.postDataJSON() });
      if (id === 1 && holdFirst) await new Promise(resolve => { state.release = resolve; });
      data = {
        provider_id: receiptMismatch === "provider" ? 2 : id,
        provider_revision: receiptMismatch === "revision" ? 4 : 3,
        configured_model: receiptMismatch === "model" ? "来自另一保存版本" : providers[id - 1].model,
        compatible: configuredMatching,
        issues: configuredMatching ? [] : ["登记模型与服务实际版本不同", "<img src=x onerror=alert('不应执行')>"],
        scope_note: "仅配置匹配检查，不发送患者资料或像素，不执行推理，不证明医疗质量或完成临床验证。",
        capabilities: {
          schema_version: "4", feature_key: "imaging_detection", model_version: model(id), engine: "torchxrayvision-densenet121",
          engine_versions: { torch: "2.14.1+cpu", numpy: "2.4.4", safetensors: "0.8.0" },
          model_repository: "torchxrayvision/densenet121-res224-all", model_revision: "588eadcc6a744da71f8dce768bc974ec629443f5",
          model_digest: "b".repeat(64), runtime_digest: "c".repeat(64), preprocessing_digest: "d".repeat(64),
          profile: "xrv_stored_range_v1", labels, prompt_handling: "pixels_only", clinical_validation: "not_provided", population_applicability: "not_verified",
          preprocessing: { profile: "xrv_stored_range_v1", input_profile: { format: "dicom_i32le_v1", frames: 1, modalities: ["CR", "DX"], body_part_examined: "CHEST", view_positions: ["PA", "AP"], pixel_representation: "unsigned", bits_allocated: [8, 16], bits_stored_min: 8, bits_stored_max: 16, rescale_slope: 1, rescale_intercept: 0 }, normalization: "(2*(stored.astype(numpy.float32)/((1<<BitsStored)-1))-1)*1024", monochrome1: "maxval-stored before normalization; exactly one inversion", crop: "center square: side=min(rows,columns); x=columns//2-side//2; y=rows//2-side//2", resize: { size: [224, 224], mode: "bilinear", align_corners: false, antialias: true, skip_if_already_224: true }, padding_policy: "preserved_as_original_background", voi_window_policy: "ignored_for_research_input_not_diagnostic_display", image_minmax_normalization: false, rotation: false, training_distribution_equivalence: "not_established", spatial_localization: false },
          max_bytes: 67108864, timeout_seconds: 110,
        },
      };
    }
    if (method === "PUT" && /^\/api\/ai\/admin\/providers\/\d+$/.test(path)) { state.writes.push(request.postDataJSON()); data = {}; }
    if (method !== "GET" && /^\/api\/ai\/admin\/features\//.test(path)) state.featureWrites.push(request.postDataJSON());
    if (method === "POST" && path === "/api/ai/runs") state.runs.push(request.postDataJSON());
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ code: 200, msg: "success", data }) });
    if (checkedId !== null) state.completed.push(checkedId);
  });
  return state;
}

async function openCheck(page, name = "本地影像甲") {
  await page.getByRole("row").filter({ hasText: name }).getByRole("button", { name: "检查本地影像服务", exact: true }).click();
}

test("超管仅获取影像服务实际能力和研究预处理，明确填表保存后才更新配置", async ({ page }) => {
  const state = await session(page);
  await page.goto("/#/ai/manage"); await selectManagementTab(page, '模型服务');
  await expect(page.getByRole("row").filter({ hasText: "普通文本服务" }).getByRole("button", { name: "检查本地影像服务", exact: true })).toHaveCount(0);
  await openCheck(page);
  const report = page.getByRole("dialog", { name: "本地影像服务核对", exact: true });
  for (const text of [model(1), "torchxrayvision/densenet121-res224-all", "588eadcc6a744da71f8dce768bc974ec629443f5", "torch 2.14.1+cpu", "v4 · imaging_detection", "xrv_stored_range_v1", labels.join("、"), "pixels_only：仅原始像素参与分类", "not_verified：未核实", "not_provided：未提供临床验证", "不应用DICOM VOI显示窗、不自动minmax或旋转", "不声称与原训练数据预处理等价", "单图分类原始分数，不提供病灶框", "不发送患者资料或原始像素"]) await expect(report).toContainText(text);
  for (const digest of ["b", "c", "d"]) await expect(report).toContainText(digest.repeat(64));
  await expect(report).toContainText("<img src=x onerror=alert('不应执行')>"); await expect(report.locator("img")).toHaveCount(0);
  expect(state.checks).toEqual([{ id: 1, method: "POST", expected_revision: 3 }]);
  expect(state.writes).toEqual([]); expect(state.featureWrites).toEqual([]); expect(state.runs).toEqual([]);
  await report.getByRole("button", { name: "填写实际模型，待保存", exact: true }).click();
  const edit = page.getByRole("dialog", { name: "编辑模型服务", exact: true });
  await expect(edit.locator(".el-form-item").filter({ hasText: "模型标识" }).getByRole("textbox")).toHaveValue(model(1));
  await expect(edit.locator(".el-form-item").filter({ hasText: "超时秒数" }).getByRole("spinbutton")).toHaveValue("120");
  await expect(edit.locator(".el-form-item").filter({ hasText: "适配器验证报告" }).getByRole("textbox")).toHaveValue("隔离界面测试，未进行临床质量验证");
  expect(state.writes).toEqual([]);
  await edit.getByRole("button", { name: "保存服务", exact: true }).click();
  await expect.poll(() => state.writes.length).toBe(1);
  expect(state.writes[0]).toMatchObject({ model: model(1), expected_revision: 3, enabled: false, allows_patient_data: false, validation_report: "隔离界面测试，未进行临床质量验证" });
  expect(state.featureWrites).toEqual([]); expect(state.runs).toEqual([]);
});

test("关闭旧影像服务检查后迟到回执不能覆盖新服务或填表目标", async ({ page }) => {
  const state = await session(page, { holdFirst: true });
  await page.goto("/#/ai/manage"); await selectManagementTab(page, '模型服务');
  await openCheck(page); await expect.poll(() => !!state.release).toBe(true);
  let report = page.getByRole("dialog", { name: "本地影像服务核对", exact: true });
  await report.getByRole("button", { name: "关闭", exact: true }).click();
  await openCheck(page, "本地影像乙"); report = page.getByRole("dialog", { name: "本地影像服务核对", exact: true });
  await expect(report).toContainText(model(2)); state.release(); await expect.poll(() => state.completed.includes(1)).toBe(true);
  await expect(report).not.toContainText(model(1));
  await report.getByRole("button", { name: "填写实际模型，待保存", exact: true }).click();
  const edit = page.getByRole("dialog", { name: "编辑模型服务", exact: true });
  await expect(edit.locator(".el-form-item").filter({ hasText: "服务名称" }).getByRole("textbox")).toHaveValue("本地影像乙");
  await expect(edit.locator(".el-form-item").filter({ hasText: "模型标识" }).getByRole("textbox")).toHaveValue(model(2));
  expect(state.writes).toEqual([]); expect(state.featureWrites).toEqual([]); expect(state.runs).toEqual([]);
});

for (const receiptMismatch of ["provider", "revision", "model"]) {
  test(`影像服务回执的${receiptMismatch}不匹配时不得填入待保存模型`, async ({ page }) => {
    const state = await session(page, { receiptMismatch });
    await page.goto("/#/ai/manage"); await selectManagementTab(page, '模型服务'); await openCheck(page);
    await expect(page.getByText("影像服务核对回执与已保存配置不一致，请刷新后重新检查", { exact: true })).toBeVisible();
    const report = page.getByRole("dialog", { name: "本地影像服务核对", exact: true });
    await expect(report.getByRole("button", { name: "填写实际模型，待保存", exact: true })).toHaveCount(0);
    expect(state.writes).toEqual([]); expect(state.featureWrites).toEqual([]); expect(state.runs).toEqual([]);
  });
}

test("影像模型标识匹配只说明配置一致，保留未验证状态并不修改任何开关", async ({ page }) => {
  const state = await session(page, { configuredMatching: true });
  await page.goto("/#/ai/manage"); await selectManagementTab(page, '模型服务'); await openCheck(page);
  const report = page.getByRole("dialog", { name: "本地影像服务核对", exact: true });
  await expect(report).toContainText("服务声明与登记配置匹配；临床质量仍待验证");
  await expect(report).toContainText("未提供临床验证"); await expect(report).toContainText("不声称与原训练数据预处理等价");
  await expect(report.getByRole("button", { name: "填写实际模型，待保存", exact: true })).toHaveCount(0);
  expect(state.writes).toEqual([]); expect(state.featureWrites).toEqual([]); expect(state.runs).toEqual([]);
});

test("等待影像能力回执时失去超管角色会清理旧报告且不接受迟到结果", async ({ page }) => {
  const state = await session(page, { holdFirst: true });
  await page.goto("/#/ai/manage"); await selectManagementTab(page, '模型服务'); await openCheck(page); await expect.poll(() => !!state.release).toBe(true);
  await page.evaluate(() => document.querySelector('#hoim').__vue_app__.config.globalProperties.$store.commit('user/setPermissions', ['admin']));
  await expect(page.getByRole("dialog", { name: "本地影像服务核对", exact: true })).toBeHidden();
  state.release(); await expect.poll(() => state.completed.includes(1)).toBe(true);
  await expect(page.getByRole("button", { name: "检查本地影像服务", exact: true })).toHaveCount(0);
  expect(state.writes).toEqual([]); expect(state.featureWrites).toEqual([]); expect(state.runs).toEqual([]);
});
