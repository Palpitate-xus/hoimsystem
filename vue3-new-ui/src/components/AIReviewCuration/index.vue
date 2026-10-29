<template>
  <section class="review-curation">
    <p>逐条整理并审核脱敏稿后，当前有效版本才能进入反馈分析。审核包含身份线索和原意保留，反馈事实及原因仍需调查。</p>
    <div class="page-toolbar">
      <el-input-number v-model="reviewFilter" :min="1" :precision="0" aria-label="原评价标识筛选" placeholder="可选：原评价标识" controls-position="right" />
      <el-date-picker v-model="sourceDates" :disabled="!!reviewFilter" type="daterange" value-format="YYYY-MM-DD" start-placeholder="评价开始日期" end-placeholder="评价结束日期" />
      <el-button :loading="sourceLoading" @click="search">查询评价</el-button>
    </div>
    <h4>原评价目录</h4>
    <p>目录不展示评论；填写标识时忽略日期范围，可查历史评价。打开原文会记录读取审计。</p>
    <el-table :data="sources" v-loading="sourceLoading" empty-text="当前范围没有关联可核实的评价">
      <el-table-column prop="review_id" label="评价标识" width="100" /><el-table-column prop="review_time" label="原评价时间" min-width="170" />
      <el-table-column label="原评分" width="90"><template #default="{ row }">{{ row.score ?? '未知' }}</template></el-table-column>
      <el-table-column label="科室标识" width="100"><template #default="{ row }">{{ row.department_id ?? '未核实' }}</template></el-table-column>
      <el-table-column label="评论" width="110"><template #default="{ row }">{{ row.has_comment ? '有原文待整理' : '无原文' }}</template></el-table-column>
      <el-table-column label="操作" width="150"><template #default="{ row }"><el-button size="small" :disabled="!row.has_comment || !row.department_id" @click="openSource(row.review_id)">整理脱敏稿</el-button></template></el-table-column>
    </el-table>
    <el-pagination v-model:current-page="sourcePage" :page-size="30" :total="sourceTotal" layout="total, prev, pager, next" class="pagination-wrapper" @current-change="loadSources" />
    <h4>脱敏版本与审核</h4>
    <div class="page-toolbar"><el-select v-model="statusFilter" clearable placeholder="全部审核状态" aria-label="脱敏稿审核状态筛选" @change="searchExcerpts"><el-option v-for="(label, value) in statuses" :key="value" :label="label" :value="value" /></el-select><el-button :loading="excerptLoading" @click="loadExcerpts">刷新版本</el-button></div>
    <el-table :data="excerpts" v-loading="excerptLoading" empty-text="当前范围尚无脱敏版本">
      <el-table-column prop="review_id" label="原评价" width="100" /><el-table-column label="版本" width="85"><template #default="{ row }">v{{ row.version }}</template></el-table-column>
      <el-table-column label="状态" width="110"><template #default="{ row }">{{ statuses[row.status] || row.status }}</template></el-table-column>
      <el-table-column label="来源核对" min-width="140"><template #default="{ row }">{{ sourceStates[row.source_state] || '待核对' }}</template></el-table-column>
      <el-table-column prop="reviewed_at" label="审核时间" min-width="170" />
      <el-table-column label="操作" width="150"><template #default="{ row }"><el-button size="small" @click="openExcerpt(row.excerpt_id)">查看并审核</el-button></template></el-table-column>
    </el-table>
    <el-pagination v-model:current-page="excerptPage" :page-size="30" :total="excerptTotal" layout="total, prev, pager, next" class="pagination-wrapper" @current-change="loadExcerpts" />

    <el-dialog v-model="sourceDialog" title="原评价与脱敏草稿" width="760px" append-to-body>
      <div v-loading="sourceDetailLoading">
        <template v-if="sourceDetail">
          <p>原评价 #{{ sourceDetail.review_id }} · {{ sourceDetail.department_name }} · {{ sourceDetail.review_time || '时间未记录' }}</p>
          <p v-if="noticeText(sourceDetail.scope_note)">{{ noticeText(sourceDetail.scope_note) }}</p><p v-if="sourceDetail.department_source === 'current_doctor'">此评价未关联挂号，科室采用医生当前档案。</p>
          <h4>仅供本次审核的原评论</h4><p class="private-comment recorded-text">{{ sourceDetail.raw_comment || '无原文' }}</p>
          <el-form :disabled="saving" label-position="top">
            <el-form-item label="脱敏摘录或整理文本"><el-input v-model="draftText" type="textarea" :rows="6" maxlength="1000" show-word-limit placeholder="检查所有身份和间接线索，保留原意；自动建议仍需人工逐条审核" /></el-form-item>
            <el-form-item label="整理说明"><el-input v-model="changeNote" maxlength="1000" placeholder="说明移除了哪些类型的线索、是否保留原意" /></el-form-item>
          </el-form>
        </template>
        <p v-else>尚未取得原评价资料。</p>
      </div>
      <template #footer><el-button @click="sourceDialog = false">关闭</el-button><el-button type="primary" :loading="saving" :disabled="!sourceDetail || draftText.trim().length < 3 || changeNote.trim().length < 3" @click="saveDraft">保存为待审核版本</el-button></template>
    </el-dialog>

    <el-dialog v-model="excerptDialog" title="脱敏版本审核" width="760px" append-to-body>
      <div v-loading="excerptDetailLoading">
        <template v-if="excerptDetail">
          <p>原评价 #{{ excerptDetail.review_id }} · v{{ excerptDetail.version }} · {{ statuses[excerptDetail.status] }}</p>
          <p>来源核对：{{ sourceStates[excerptDetail.source_state] || '待核对' }}。{{ excerptDetail.source_state === 'current' ? '当前稿件仍对应原评价及科室。' : '此版本不能发布，请重新读取原评价并整理新稿。' }}</p>
          <h4>本版本文本</h4><p class="recorded-text">{{ excerptDetail.redacted_text }}</p><p>整理说明：{{ excerptDetail.change_note }}</p>
          <el-button :loading="excerptSourceLoading" :disabled="excerptDetail.source_state === 'unavailable'" @click="loadExcerptSource">读取原评价核对</el-button>
          <template v-if="excerptSource"><h4>仅供本次审核的原评价</h4><p class="private-comment recorded-text">{{ excerptSource.raw_comment || '无原文' }}</p><p>{{ comparableSource ? '当前原评价仍与成稿时一致，请逐项核对原意和识别线索。' : '原评价与成稿时版本已不一致，此稿不能发布，请另存新版本。' }}</p></template>
          <p v-if="excerptDetail.reviewed_at">已记录审核时间：{{ excerptDetail.reviewed_at }}。</p>
          <el-form label-position="top" :disabled="saving">
            <el-form-item v-if="excerptDetail.status === 'draft'" label="发布审核确认"><div class="review-checks"><p v-if="!comparableSource">先读取对应原评价，再核对并确认。</p><el-checkbox v-model="privacyChecked" :disabled="!comparableSource">已逐条检查身份、联系方式及间接识别线索</el-checkbox><el-checkbox v-model="faithfulnessChecked" :disabled="!comparableSource">已对照原评价核查原意，没有新增事实或责任判断</el-checkbox></div></el-form-item>
            <el-form-item v-if="['draft', 'published'].includes(excerptDetail.status)" label="本次审核或停用说明"><el-input v-model="reviewNote" type="textarea" :rows="3" maxlength="1000" /></el-form-item>
          </el-form>
          <p>发布新版本会停用同一原评价的旧发布版本。停用或来源失效后，后续调用不再使用，普通用户旧结果不再开放；冻结审计仍供超级管理员追查。</p>
        </template>
        <p v-else>尚未取得版本资料。</p>
      </div>
      <template #footer>
        <el-button @click="excerptDialog = false">关闭</el-button>
        <el-button v-if="excerptDetail" :disabled="saving || excerptDetail.source_state === 'unavailable'" @click="openSourceFromExcerpt">按原评价另存新版本</el-button>
        <el-button v-if="excerptDetail?.status === 'draft'" :disabled="reviewNote.trim().length < 3" :loading="saving" @click="decide('rejected')">驳回稿件</el-button>
        <el-button v-if="['draft', 'published'].includes(excerptDetail?.status)" :disabled="reviewNote.trim().length < 3" :loading="saving" @click="decide('retired')">停用版本</el-button>
        <el-button v-if="excerptDetail?.status === 'draft'" type="primary" :disabled="excerptDetail.source_state !== 'current' || !comparableSource || !privacyChecked || !faithfulnessChecked || reviewNote.trim().length < 3" :loading="saving" @click="decide('published')">审核通过并发布</el-button>
      </template>
    </el-dialog>
  </section>
</template>

<script setup>
import { noticeText, noticeList } from "@/utils/noticeText.cjs";
import { computed, onActivated, onBeforeUnmount, onDeactivated, ref, watch } from "vue";
import { ElMessage } from "element-plus";
import { createAIReviewExcerpt, getAIReviewExcerpt, getAIReviewExcerpts, getAIReviewSource, getAIReviewSources, reviewAIReviewExcerpt } from "@/api/ai";
const props = defineProps({ active: { type: Boolean, default: false } });
const statuses = { draft: "待审核", published: "已发布", rejected: "已驳回", retired: "已停用" };
const sourceStates = { current: "与原评价一致", stale: "原评价或关联已变化", unavailable: "原关联无法核实", artifact_changed: "版本文本校验已失效" };
const reviewFilter = ref(null), sourceDates = ref([]), statusFilter = ref("");
const sources = ref([]), excerpts = ref([]), sourceTotal = ref(0), excerptTotal = ref(0), sourcePage = ref(1), excerptPage = ref(1);
const sourceLoading = ref(false), excerptLoading = ref(false), saving = ref(false), sourceDetailLoading = ref(false), excerptDetailLoading = ref(false);
const sourceDialog = ref(false), excerptDialog = ref(false), sourceDetail = ref(null), excerptDetail = ref(null);
const draftText = ref(""), changeNote = ref(""), reviewNote = ref(""), privacyChecked = ref(false), faithfulnessChecked = ref(false);
const excerptSource = ref(null), excerptSourceLoading = ref(false);
const comparableSource = computed(() => !!excerptSource.value && excerptSource.value.source_hash === excerptDetail.value?.source_hash);
let sourceListVersion = 0, excerptListVersion = 0, sourceVersion = 0, excerptVersion = 0, live = true;
async function loadSources() {
  if (!props.active || !live) return;
  const version = ++sourceListVersion; sourceLoading.value = true;
  try {
    const response = await getAIReviewSources({ review_id: reviewFilter.value || undefined, date_from: reviewFilter.value ? undefined : sourceDates.value?.[0], date_to: reviewFilter.value ? undefined : sourceDates.value?.[1], page: sourcePage.value, page_size: 30 });
    if (version !== sourceListVersion || !live || !props.active) return;
    const data = response.data || {}; sources.value = data.items || []; sourceTotal.value = data.total || 0;
    if (!sourceDates.value?.length && !reviewFilter.value && data.window) sourceDates.value = data.window;
  } finally { if (version === sourceListVersion) sourceLoading.value = false; }
}
async function loadExcerpts() {
  if (!props.active || !live) return;
  const version = ++excerptListVersion; excerptLoading.value = true;
  try {
    const response = await getAIReviewExcerpts({ review_id: reviewFilter.value || undefined, status: statusFilter.value || undefined, page: excerptPage.value, page_size: 30 });
    if (version !== excerptListVersion || !live || !props.active) return;
    excerpts.value = response.data?.items || []; excerptTotal.value = response.data?.total || 0;
  } finally { if (version === excerptListVersion) excerptLoading.value = false; }
}
async function refresh() { await Promise.all([loadSources(), loadExcerpts()]); }
function search() { sourcePage.value = 1; excerptPage.value = 1; refresh(); }
function searchExcerpts() { excerptPage.value = 1; loadExcerpts(); }
async function openSource(id) {
  const version = ++sourceVersion; sourceDetail.value = null; draftText.value = ""; changeNote.value = ""; sourceDialog.value = true; sourceDetailLoading.value = true;
  try {
    const response = await getAIReviewSource(id);
    if (version !== sourceVersion || !sourceDialog.value || !live || !props.active) return;
    sourceDetail.value = response.data; draftText.value = response.data.suggested_redacted_text || "";
  } finally { if (version === sourceVersion) sourceDetailLoading.value = false; }
}
async function openExcerpt(id) {
  const version = ++excerptVersion; excerptDetail.value = null; excerptSource.value = null; excerptSourceLoading.value = false; privacyChecked.value = false; faithfulnessChecked.value = false; reviewNote.value = ""; excerptDialog.value = true; excerptDetailLoading.value = true;
  try {
    const response = await getAIReviewExcerpt(id);
    if (version !== excerptVersion || !excerptDialog.value || !live || !props.active) return;
    excerptDetail.value = response.data;
  } finally { if (version === excerptVersion) excerptDetailLoading.value = false; }
}
async function loadExcerptSource() {
  if (!excerptDetail.value) return;
  const version = excerptVersion, id = excerptDetail.value.excerpt_id; excerptSource.value = null; excerptSourceLoading.value = true; privacyChecked.value = false; faithfulnessChecked.value = false;
  try {
    const response = await getAIReviewSource(excerptDetail.value.review_id);
    if (version !== excerptVersion || !excerptDialog.value || id !== excerptDetail.value?.excerpt_id || !live || !props.active) return;
    excerptSource.value = response.data;
  } finally { if (version === excerptVersion) excerptSourceLoading.value = false; }
}
async function saveDraft() {
  if (!sourceDetail.value) return;
  const version = sourceVersion, source = sourceDetail.value; saving.value = true;
  try {
    await createAIReviewExcerpt({ review_id: source.review_id, expected_source_hash: source.source_hash, redacted_text: draftText.value, change_note: changeNote.value });
    if (version === sourceVersion && live && props.active) { sourceDialog.value = false; ElMessage.success("已保存待审核版本，尚未发布给AI使用"); }
    await loadExcerpts();
  } finally { saving.value = false; }
}
async function decide(status) {
  if (!excerptDetail.value) return;
  const version = excerptVersion, item = excerptDetail.value; saving.value = true;
  try {
    const response = await reviewAIReviewExcerpt(item.excerpt_id, { expected_revision: item.revision, status, privacy_checked: privacyChecked.value, faithfulness_checked: faithfulnessChecked.value, review_note: reviewNote.value });
    if (version === excerptVersion && live && props.active) { excerptDetail.value = { ...response.data, source_state: item.source_state }; privacyChecked.value = false; faithfulnessChecked.value = false; reviewNote.value = ""; ElMessage.success(status === "published" ? "审核版本已发布" : "审核状态已更新"); }
    await loadExcerpts();
  } finally { saving.value = false; }
}
function openSourceFromExcerpt() { const id = excerptDetail.value.review_id; excerptDialog.value = false; openSource(id); }
function clearPrivate() { sourceVersion += 1; excerptVersion += 1; sourceListVersion += 1; excerptListVersion += 1; sourceDialog.value = false; excerptDialog.value = false; sourceDetail.value = null; excerptDetail.value = null; excerptSource.value = null; excerptSourceLoading.value = false; draftText.value = ""; changeNote.value = ""; reviewNote.value = ""; privacyChecked.value = false; faithfulnessChecked.value = false; sourceLoading.value = false; excerptLoading.value = false; sourceDetailLoading.value = false; excerptDetailLoading.value = false; }
watch(sourceDialog, value => { if (!value) { sourceVersion += 1; sourceDetail.value = null; draftText.value = ""; changeNote.value = ""; } });
watch(excerptDialog, value => { if (!value) { excerptVersion += 1; excerptDetail.value = null; excerptSource.value = null; excerptSourceLoading.value = false; reviewNote.value = ""; privacyChecked.value = false; faithfulnessChecked.value = false; } });
watch(() => props.active, value => { if (value && live) refresh(); else clearPrivate(); }, { immediate: true });
onDeactivated(() => { live = false; clearPrivate(); });
onActivated(() => { if (!live) { live = true; if (props.active) refresh(); } });
onBeforeUnmount(() => { live = false; clearPrivate(); });
</script>

<style scoped>
.review-curation { line-height: 1.7; }
.recorded-text { white-space: pre-wrap; overflow-wrap: anywhere; max-height: 32vh; overflow: auto; }
.private-comment { padding: 12px; background: #f5f7fa; }
.review-checks { display: flex; flex-direction: column; }
</style>
