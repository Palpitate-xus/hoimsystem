<template>
  <section v-loading="loading" aria-label="AI心电原文件治理">
    <p>核对原患者、原就诊、来源授权和校准声明。当前诊疗成员按范围共享；撤回阻止后续模型使用，清除只删除当前存储原文件，冻结任务与审计仍保留。</p>
    <div class="page-toolbar"><el-input-number v-model="patientFilter" :min="1" placeholder="患者ID（可选）" aria-label="心电治理患者ID" /><el-select v-model="statusFilter" clearable placeholder="全部状态" aria-label="心电治理状态"><el-option v-for="(label, value) in statuses" :key="value" :value="value" :label="label" /></el-select><el-button @click="refresh">查询心电原文件</el-button></div>
    <el-table :data="items" empty-text="当前范围没有已登记原始心电">
      <el-table-column prop="asset_id" label="原记录标识" min-width="240" /><el-table-column prop="patient_id" label="患者ID" width="85" /><el-table-column prop="created_by" label="登记用户ID" width="100" />
      <el-table-column label="原采样资料" min-width="190"><template #default="{ row }">{{ row.signal_metadata.channels }}导联 · {{ row.signal_metadata.sample_rate_hz }}Hz<br />{{ row.signal_metadata.sample_count }}个原样本/导联</template></el-table-column>
      <el-table-column label="状态" width="115"><template #default="{ row }">{{ statuses[row.status] }}</template></el-table-column>
      <el-table-column label="操作" min-width="230"><template #default="{ row }"><el-button size="small" @click="inspect(row)">核对授权与原波形</el-button><el-button v-if="row.status === 'ready'" size="small" type="warning" @click="withdraw(row)">撤回</el-button><el-button v-if="['withdrawn', 'purge_pending'].includes(row.status)" size="small" type="danger" @click="purge(row)">{{ row.status === 'purge_pending' ? '继续清除' : '清除原文件' }}</el-button></template></el-table-column>
    </el-table>
    <p v-if="truncated">仅显示最近100项，目录已截断，请按患者和状态缩小范围。</p>
    <el-dialog v-model="visible" title="原始心电登记与授权核对" width="min(1050px, 95vw)">
      <div v-loading="detailLoading"><template v-if="visible && detail">
        <p>原记录 {{ detail.asset_id }} · 患者 #{{ detail.patient_id }} · 版本{{ detail.revision }} · {{ statuses[detail.status] }}</p>
        <p>原就诊 {{ detail.encounter_ref || '未记录，不按日期推定' }}；原采集时刻 {{ detail.recorded_at || '未记录' }}；登记时刻 {{ detail.create_time }}。</p>
        <p class="recorded-text">原文件组合哈希：{{ detail.content_hash }}</p>
        <h4>登记人的来源与授权核对说明</h4><p class="recorded-text">{{ detail.authorization_note }}</p>
        <template v-if="detail.withdrawal_note"><h4>撤回原因</h4><p class="recorded-text">{{ detail.withdrawal_note }}</p></template>
        <template v-if="detail.purge_note"><h4>原清除请求原因</h4><p class="recorded-text">{{ detail.purge_note }}</p></template>
        <ai-ecg-viewer v-if="['ready', 'withdrawn'].includes(detail.status)" :key="`${detail.asset_id}:${detail.revision}`" :source="detail" allow-download /><p v-else>原文件已进入清除流程，不能读取波形或下载。</p>
      </template></div>
      <template #footer><el-button @click="visible = false">关闭</el-button></template>
    </el-dialog>
  </section>
</template>
<script setup>
import { onActivated, onBeforeUnmount, onDeactivated, onMounted, ref, watch } from "vue";
import { ElMessage, ElMessageBox } from "element-plus";
import { getAIAdminEcgAssets, getAIEcgAsset, purgeAIEcg, withdrawAIEcg } from "@/api/ai";
import AiEcgViewer from "@/components/AIEcgViewer/index.vue";
const loading = ref(false), items = ref([]), patientFilter = ref(null), statusFilter = ref(""), truncated = ref(false), visible = ref(false), detail = ref(null), detailLoading = ref(false);
const statuses = { ready: "可读取原文件", withdrawn: "已撤回", purge_pending: "清除中", purged: "原文件已清除" };
let listVersion = 0, detailVersion = 0, inactive = false;
watch(visible, value => { if (!value) { detailVersion += 1; detail.value = null; detailLoading.value = false; } });
async function refresh() { const version = ++listVersion; loading.value = true; try { const response = await getAIAdminEcgAssets({ patient_id: patientFilter.value || undefined, status: statusFilter.value || undefined }); if (version === listVersion) { items.value = response.data?.items || []; truncated.value = !!response.data?.truncated; } } finally { if (version === listVersion) loading.value = false; } }
async function inspect(row) { const version = ++detailVersion; detail.value = null; visible.value = true; detailLoading.value = true; try { const response = await getAIEcgAsset(row.asset_id); if (version === detailVersion && visible.value) detail.value = response.data; } finally { if (version === detailVersion) detailLoading.value = false; } }
const reasonOptions = { inputValidator: value => value?.trim().length >= 5 || "请填写至少5字的原因" };
async function withdraw(row) {
  try { const { value } = await ElMessageBox.prompt("撤回将阻止后续模型使用和普通用户旧结果读取；不能收回已发出的请求或下载。请填写原因", "撤回原始心电", { ...reasonOptions, confirmButtonText: "撤回原心电" }); detailVersion += 1; await withdrawAIEcg(row.asset_id, { expected_revision: row.revision, reason: value.trim() }); visible.value = false; await refresh(); ElMessage.success("原心电已撤回"); }
  catch (error) { if (error !== "cancel" && error !== "close") throw error; }
}
async function purge(row) {
  try { const { value } = await ElMessageBox.prompt("将删除当前存储的原头文件与采样文件；冻结任务文字、元数据和审计保留。请核对原清除请求并填写原因", row.status === "purge_pending" ? "继续清除心电原文件" : "清除心电原文件", { ...reasonOptions, confirmButtonText: "清除原文件", type: "warning" }); detailVersion += 1; await purgeAIEcg(row.asset_id, { expected_revision: row.revision, reason: value.trim() }); visible.value = false; await refresh(); ElMessage.success("当前存储心电原文件已清除"); }
  catch (error) { if (error !== "cancel" && error !== "close") { await refresh(); throw error; } }
}
function invalidate() { listVersion += 1; detailVersion += 1; visible.value = false; detail.value = null; items.value = []; }
onMounted(refresh); onActivated(() => { if (inactive) { inactive = false; refresh(); } }); onDeactivated(() => { inactive = true; invalidate(); }); onBeforeUnmount(invalidate);
</script>
<style scoped>
.recorded-text { white-space: pre-wrap; overflow-wrap: anywhere; line-height: 1.7; }
</style>
