const { selectManagementTab } = require('./fixtures/ai-management-navigation.cjs');
const { test, expect } = require("@playwright/test");

async function session(page, { initialDraft = false, staleSource = false, holdFirstSource = false } = {}) {
  const state = { writes: [], sourceReads: [], previews: [], submissions: [], draft: initialDraft ? { excerpt_id: "excerpt-1", review_id: 1, version: 1, department_id: 1, status: "draft", revision: 1, source_state: "current", source_hash: "a".repeat(64), redacted_text: "候诊较久，希望了解顺序。", change_note: "已去除直接标识" } : null };
  let releaseFirst;
  const firstGate = new Promise(resolve => { releaseFirst = resolve; });
  const feature = { number: 70, key: "feedback_analysis", name: "投诉和满意度分析", category: "operations", priority: "P1", engine: "llm", scope: "hospital", inputs: ["已审核片段"], deliverables: ["所载主题与依据"], default_roles: ["super_admin", "admin", "director"], allowed_roles: ["super_admin", "admin", "director"], enabled: true, validation_status: "unreviewed", prompt_version: 0, revision: 1, daily_limit: 100 };
  await page.addInitScript(() => localStorage.setItem("hoim-token", "review-curation-ai-test"));
  await page.route("**/api/**", async route => {
    const url = new URL(route.request().url()), path = url.pathname, method = route.request().method();
    let data = [];
    if (path === "/api/userInfo") data = { username: "测试超级管理员", permissions: ["super_admin", "admin"], avatar: "" };
    if (["/api/ai/admin/features", "/api/ai/features"].includes(path)) data = [feature];
    if (path === "/api/ai/admin/review-sources") data = { items: [{ review_id: 1, review_time: "2026-10-20T10:00:00", score: 2, department_id: 1, has_comment: true }, { review_id: 2, review_time: "2026-10-20T11:00:00", score: 3, department_id: 1, has_comment: true }], total: 2, page: 1, window: ["2026-10-01", "2026-10-20"] };
    if (/^\/api\/ai\/admin\/review-sources\/\d+$/.test(path)) {
      const id = Number(path.split("/").at(-1)); state.sourceReads.push(id);
      if (holdFirstSource && id === 1 && state.sourceReads.length === 1) await firstGate;
      data = { review_id: id, source_hash: staleSource || id === 2 ? "b".repeat(64) : "a".repeat(64), raw_comment: id === 1 ? "患者原评价13800138000 <img src=x onerror=alert(1)>" : "第二条原评价，不能被第一条迟到响应覆盖", suggested_redacted_text: id === 1 ? "候诊较久，希望了解顺序。" : "第二条评价的脱敏建议", department_name: "测试科室", department_source: "original_registration", review_time: "2026-10-20T10:00:00", scope_note: "自动建议不能代替逐条脱敏和原意审核" };
    }
    if (path === "/api/ai/admin/review-excerpts" && method === "GET") data = { items: state.draft ? [state.draft] : [], total: state.draft ? 1 : 0, page: 1 };
    if (path === "/api/ai/admin/review-excerpts/excerpt-1") data = state.draft;
    if (path === "/api/ai/admin/review-excerpts" && method === "POST") {
      const body = route.request().postDataJSON(); state.writes.push({ path, body });
      state.draft = { ...body, source_hash: body.expected_source_hash, excerpt_id: "excerpt-1", version: 1, department_id: 1, status: "draft", revision: 1, source_state: "current" }; data = state.draft;
    }
    if (path === "/api/ai/admin/review-excerpts/excerpt-1/review") {
      const body = route.request().postDataJSON(); state.writes.push({ path, body });
      state.draft = { ...state.draft, status: body.status, revision: state.draft.revision + 1, reviewed_at: "2026-10-20T11:00:00" }; data = state.draft;
    }
    if (path === "/api/ai/service-options") data = { default_window: ["2026-10-01", "2026-10-20"], allow_hospital_scope: true, departments: [] };
    if (path === "/api/ai/operational-context" || path === "/api/ai/runs/review-run") {
      const included = state.draft?.status === "published";
      const item = { source_id: "feedback:reviewed-excerpt", excerpt_ref: "excerpt-1", version: 1, text: state.draft?.redacted_text, recorded_review_date: "2026-10-20", recorded_score: 2, definition_note: "人工审核不证明反馈事实或原因已核实" };
      const context = { scope: "hospital", source_domain: "feedback", since: "2026-10-01", until: "2026-10-20", snapshot_time: "2026-10-20T11:00:00Z", scope_note: "所选日期范围内的已审核评价", missing_data: ["全体就诊分母未知"], reviewed_feedback_excerpts: { items: included ? [item] : [], included_excerpt_count: included ? 1 : 0, excluded_changed_source_count: 0, scope_note: "仅当前有效审核版本，不代表全部意见" } };
      const evidence = included ? [{ source_id: item.source_id, title: "已审核脱敏评价片段", content: state.draft.redacted_text + "；原评价未发给模型" }] : [];
      if (path === "/api/ai/operational-context") { state.previews.push(route.request().postDataJSON()); data = { context, evidence }; }
      else data = { run_id: "review-run", feature_name: feature.name, status: "succeeded", operational_findings: context, evidence, result: { summary: "仅一条已审核片段提到候诊问题", sections: [{ title: "所载主题", content: "等待较久，流程原因仍待调查", source_ids: [item.source_id] }], warnings: [], missing_data: [] } };
    }
    if (path === "/api/ai/runs" && method === "POST") { state.submissions.push(route.request().postDataJSON()); data = { run_id: "review-run", feature_name: feature.name, status: "queued" }; }
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ code: 200, msg: "success", data }) });
  });
  return { state, releaseFirst };
}

async function openTab(page) {
  await page.goto("/#/ai/manage");
  await selectManagementTab(page, '反馈脱敏审核');
}

test("超级管理员整理、对照审核、发布及停用片段，业务分析另须完整原件", async ({ page }) => {
  const { state } = await session(page);
  await openTab(page);
  await page.getByRole("button", { name: "整理脱敏稿", exact: true }).first().click();
  const draft = page.getByRole("dialog", { name: "原评价与脱敏草稿", exact: true });
  await expect(draft).toContainText("13800138000 <img src=x onerror=alert(1)>");
  await expect(draft.locator("img")).toHaveCount(0);
  await expect(draft.getByRole("textbox", { name: "脱敏摘录或整理文本", exact: true })).toHaveValue("候诊较久，希望了解顺序。");
  await draft.getByRole("textbox", { name: "整理说明", exact: true }).fill("移除联系方式，保留候诊问题");
  await draft.getByRole("button", { name: "保存为待审核版本", exact: true }).click();
  await expect(draft).not.toBeVisible();
  expect(state.writes[0].body).toMatchObject({ review_id: 1, expected_source_hash: "a".repeat(64) });
  await page.getByRole("button", { name: "查看并审核", exact: true }).click();
  const review = page.getByRole("dialog", { name: "脱敏版本审核", exact: true });
  const publish = review.getByRole("button", { name: "审核通过并发布", exact: true });
  await expect(publish).toBeDisabled();
  await review.getByRole("button", { name: "读取原评价核对", exact: true }).click();
  await expect(review).toContainText("当前原评价仍与成稿时一致");
  await review.locator("label.el-checkbox").filter({ hasText: "已逐条检查身份" }).click();
  await expect(publish).toBeDisabled();
  await review.locator("label.el-checkbox").filter({ hasText: "已对照原评价核查原意" }).click();
  await review.getByRole("textbox", { name: "本次审核或停用说明", exact: true }).fill("核对原评价并确认脱敏和原意");
  await publish.click();
  await expect(review).toContainText("已发布");
  expect(state.writes[1].body).toMatchObject({ expected_revision: 1, privacy_checked: true, faithfulness_checked: true, status: "published" });
  await review.getByRole("button", { name: "关闭", exact: true }).click();
  await page.goto("/#/report/operations");
  await page.getByRole("button", { name: "AI 评价证据分析", exact: true }).click();
  const drawer = page.getByRole("dialog", { name: "AI 完整评价证据分析", exact: true });
  await expect(drawer.getByText("请由超级管理员配置完整评价证据分析模式。", { exact: true })).toBeVisible();
  await expect(drawer.getByRole("button", { name: "生成辅助建议", exact: true })).toHaveCount(0);
  expect(state.previews).toEqual([]);
  expect(state.submissions).toEqual([]);
  await drawer.locator("button.el-drawer__close-btn").click();
  await page.goto("/#/ai/manage");
  await selectManagementTab(page, '反馈脱敏审核');
  await page.getByRole("button", { name: "查看并审核", exact: true }).click();
  await review.getByRole("textbox", { name: "本次审核或停用说明", exact: true }).fill("人工复查后停用此片段");
  await review.getByRole("button", { name: "停用版本", exact: true }).click();
  await expect(review).toContainText("已停用");
  expect(state.writes[2].body).toMatchObject({ expected_revision: 2, status: "retired" });
});

test("切换原评价后迟到的旧原文不覆盖新稿，保存仍绑定新来源", async ({ page }) => {
  const { state, releaseFirst } = await session(page, { holdFirstSource: true });
  try {
    await openTab(page);
    await page.getByRole("button", { name: "整理脱敏稿", exact: true }).first().click();
    await expect.poll(() => state.sourceReads.length).toBe(1);
    const draft = page.getByRole("dialog", { name: "原评价与脱敏草稿", exact: true });
    await draft.getByRole("button", { name: "关闭", exact: true }).click();
    await page.getByRole("button", { name: "整理脱敏稿", exact: true }).nth(1).click();
    await expect(draft).toContainText("第二条原评价");
    releaseFirst();
    await expect(draft.getByRole("textbox", { name: "脱敏摘录或整理文本", exact: true })).toHaveValue("第二条评价的脱敏建议");
    await expect(draft).not.toContainText("13800138000");
    await draft.getByRole("textbox", { name: "整理说明", exact: true }).fill("第二条原评价脱敏说明");
    await draft.getByRole("button", { name: "保存为待审核版本", exact: true }).click();
    await expect.poll(() => state.writes.length).toBe(1);
    expect(state.writes[0].body).toMatchObject({ review_id: 2, expected_source_hash: "b".repeat(64), redacted_text: "第二条评价的脱敏建议" });
  } finally { releaseFirst(); }
});

test("原评价在成稿后变化，核对界面保持发布禁用并要求另存版本", async ({ page }) => {
  const { state } = await session(page, { initialDraft: true, staleSource: true });
  await openTab(page);
  await page.getByRole("button", { name: "查看并审核", exact: true }).click();
  const review = page.getByRole("dialog", { name: "脱敏版本审核", exact: true });
  await review.getByRole("button", { name: "读取原评价核对", exact: true }).click();
  await expect(review).toContainText("原评价与成稿时版本已不一致");
  await expect(review.getByRole("button", { name: "审核通过并发布", exact: true })).toBeDisabled();
  await expect(review.getByRole("checkbox").first()).toBeDisabled();
  await review.getByRole("button", { name: "按原评价另存新版本", exact: true }).click();
  const draft = page.getByRole("dialog", { name: "原评价与脱敏草稿", exact: true });
  await expect(draft).toContainText("原评价 #1");
  expect(state.writes).toEqual([]);
});
