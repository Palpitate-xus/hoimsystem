<template>
  <section v-loading="loading" aria-label="AI录音治理">
    <p>核对原患者、就诊、登记人与授权说明。撤回阻止后续使用；清除删除当前存储原文件，保留来源哈希、任务文字和审计元数据。</p>
    <div class="page-toolbar"><el-input-number v-model="patientFilter" :min="1" placeholder="患者ID（可选）" aria-label="录音治理患者ID" /><el-select v-model="statusFilter" clearable placeholder="全部状态" aria-label="录音治理状态"><el-option v-for="(label, value) in statuses" :key="value" :value="value" :label="label" /></el-select><el-button @click="refresh">查询录音</el-button></div>
    <el-table :data="items" empty-text="当前范围没有登记录音">
      <el-table-column prop="asset_id" label="录音标识" min-width="250" /><el-table-column prop="patient_id" label="患者ID" width="85" /><el-table-column prop="created_by" label="登记用户ID" width="100" />
      <el-table-column label="解码秒数" width="95"><template #default="{ row }">{{ (row.duration_ms / 1000).toFixed(2) }}</template></el-table-column>
      <el-table-column label="状态" width="115"><template #default="{ row }">{{ statuses[row.status] }}</template></el-table-column>
      <el-table-column label="操作" min-width="220"><template #default="{ row }"><el-button size="small" @click="inspect(row)">查看授权与原音</el-button><el-button v-if="row.status === 'ready'" size="small" type="warning" @click="withdraw(row)">撤回</el-button><el-button v-if="['withdrawn', 'purge_pending'].includes(row.status)" size="small" type="danger" @click="purge(row)">{{ row.status === 'purge_pending' ? '继续清除' : '清除原文件' }}</el-button></template></el-table-column>
    </el-table>
    <p v-if="truncated">目录已截断，仅显示最近100项，可按患者和状态缩小范围。</p>
    <el-dialog v-model="visible" title="原录音登记与授权核对" width="780px">
      <template v-if="detail && visible"><p>录音 {{ detail.asset_id }} · 患者 #{{ detail.patient_id }} · 原版本 {{ detail.revision }} · {{ statuses[detail.status] }}</p><p>原就诊：{{ detail.encounter_ref || '未记录，不按日期补关联' }}</p><p>原录音时间：{{ detail.recorded_at || '未记录' }}；登记时间：{{ detail.create_time }}。</p><p>原文件哈希：{{ detail.content_hash }}</p><h4>登记人的授权核对说明</h4><p class="recorded-text">{{ detail.authorization_note }}</p><h4 v-if="detail.withdrawal_note">撤回原因</h4><p class="recorded-text">{{ detail.withdrawal_note }}</p><h4 v-if="detail.purge_note">原清除请求原因</h4><p class="recorded-text">{{ detail.purge_note }}</p><ai-audio-player v-if="['ready', 'withdrawn'].includes(detail.status)" :key="`${detail.asset_id}:${detail.revision}`" :asset-id="detail.asset_id" :extension="detail.extension" /><p v-else>原文件已进入清除流程，不能播放或下载。</p></template>
      <template #footer><el-button @click="visible = false">关闭</el-button></template>
    </el-dialog>
  </section>
</template>
<script setup>
import { onBeforeUnmount, onMounted, ref } from "vue";
import { ElMessage, ElMessageBox } from "element-plus";
import { getAIAdminAudioAssets, getAIAudioAsset, purgeAIAudio, withdrawAIAudio } from "@/api/ai";
import AiAudioPlayer from "@/components/AIAudioPlayer/index.vue";
const loading = ref(false), items = ref([]), patientFilter = ref(null), statusFilter = ref(""), truncated = ref(false), visible = ref(false), detail = ref(null);
const statuses = { ready: "可用", withdrawn: "已撤回", purge_pending: "清除中", purged: "原文件已清除" };
let listVersion = 0, detailVersion = 0;
async function refresh() { const version = ++listVersion; loading.value = true; try { const response = await getAIAdminAudioAssets({ patient_id: patientFilter.value || undefined, status: statusFilter.value || undefined }); if (version === listVersion) { items.value = response.data?.items || []; truncated.value = !!response.data?.truncated; } } finally { if (version === listVersion) loading.value = false; } }
async function inspect(row) { const version = ++detailVersion; const response = await getAIAudioAsset(row.asset_id); if (version === detailVersion) { detail.value = response.data; visible.value = true; } }
const reasonOptions = { inputValidator: value => value?.trim().length >= 5 || "请填写至少5字的原因" };
async function withdraw(row) {
  try { const { value } = await ElMessageBox.prompt("撤回阻止后续使用，但无法收回已发出的请求或已读取资料。请填写原因", "撤回原录音", { ...reasonOptions, confirmButtonText: "撤回录音" }); detailVersion += 1; await withdrawAIAudio(row.asset_id, { expected_revision: row.revision, reason: value.trim() }); visible.value = false; await refresh(); ElMessage.success("录音已撤回"); }
  catch (error) { if (error !== "cancel" && error !== "close") throw error; }
}
async function purge(row) {
  try { const { value } = await ElMessageBox.prompt("将删除当前存储中的原录音文件；审计与来源哈希保留。请核对原清除请求并填写原因", row.status === "purge_pending" ? "继续清除原文件" : "清除录音原文件", { ...reasonOptions, confirmButtonText: "清除原文件", type: "warning" }); detailVersion += 1; await purgeAIAudio(row.asset_id, { expected_revision: row.revision, reason: value.trim() }); visible.value = false; await refresh(); ElMessage.success("当前存储原文件已清除"); }
  catch (error) { if (error !== "cancel" && error !== "close") { await refresh(); throw error; } }
}
onMounted(refresh); onBeforeUnmount(() => { listVersion += 1; detailVersion += 1; });
</script>
<style scoped>
.recorded-text { white-space: pre-wrap; overflow-wrap: anywhere; line-height: 1.7; }
</style>
