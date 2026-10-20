<template>
  <section v-loading="loading" class="ecg-input" aria-label="原始心电登记与选择">
    <h4>明确选择本患者的原始心电</h4>
    <el-select :model-value="modelValue || null" :disabled="locked || uploading || loading" clearable filterable aria-label="待判读原始心电" placeholder="选择已登记的成对WFDB记录" style="width: 100%" @update:model-value="$emit('update:modelValue', $event || '')">
      <el-option v-for="item in assets" :key="item.asset_id" :value="item.asset_id" :disabled="item.status !== 'ready'" :label="`心电 ${item.asset_id.slice(0,8)} · ${item.signal_metadata.channels}导联 · ${(item.signal_metadata.duration_ms / 1000).toFixed(3)}秒 · ${statuses[item.status]}`" />
    </el-select>
    <p>{{ options.scope_note || '原文件按当前患者及原就诊诊疗范围共享；上传与预览不调用模型。' }}</p>
    <template v-if="selected">
      <p>原就诊：{{ selected.encounter_ref || '未记录，不按日期推定' }}；采集时间：{{ selected.recorded_at || '未记录，不以登记时间代替' }}。原导联：{{ selected.signal_metadata.leads.map(lead => lead.name).join('、') }}。</p>
      <p v-if="!hasSamples" class="data-gap">全部采样均为缺失标记，可核查原记录，不能创建候选判读任务。</p>
      <el-button :disabled="uploading" @click="viewVisible = true">查看所选原波形</el-button><el-button v-if="selected.can_withdraw" type="warning" :disabled="uploading" @click="withdraw">撤回所选原心电</el-button>
    </template>
    <p v-if="truncated">只显示近期50项，可选择明确原就诊缩小范围，不能据此断言没有其他心电记录。</p>
    <p v-if="locked">本次固定原始记录，登记其他文件请从未绑定原记录的工作台进入。</p>
    <el-collapse v-if="!locked"><el-collapse-item title="登记成对原始心电文件">
      <p>当前支持单文件16位小端WFDB，需有明确导联、采样率、样本数、增益/基线/单位和校验字段；不接受报告截图、URL、压缩包或用文字代替原信号。</p>
      <div class="file-row"><label>原头文件（.hea） <input ref="headerInput" type="file" accept=".hea" aria-label="选择心电原头文件" :disabled="uploading" @change="choose('header', $event)" /></label></div>
      <div class="file-row"><label>原采样文件（.dat） <input ref="signalInput" type="file" accept=".dat" aria-label="选择心电原采样文件" :disabled="uploading" @change="choose('signal', $event)" /></label></div>
      <p>单份记录上限 {{ Math.floor((options.max_bytes || 0) / 1048576) }}MiB、{{ options.max_duration_seconds }}秒；当前登记用量 {{ Math.ceil((options.used_bytes || 0) / 1048576) }}MiB。</p>
      <el-checkbox v-model="confirmed" :disabled="uploading">我已核对原文件来源、使用授权及所选患者和原就诊关联</el-checkbox>
      <el-input v-model="note" type="textarea" :rows="2" maxlength="1000" aria-label="心电原文件授权核对说明" placeholder="填写来源、关联与授权核对依据（至少5字），不写无关身份联系方式" :disabled="uploading" />
      <el-form-item label="原始采集时刻（可选）"><el-date-picker v-model="recordedAt" type="datetime" placeholder="未知时留空，不默认当前时间" :disabled="uploading" /></el-form-item>
      <el-button type="primary" :disabled="!confirmed || note.trim().length < 5 || !headerFile || !signalFile" :loading="uploading" @click="upload">登记成对原心电</el-button>
    </el-collapse-item></el-collapse>
    <el-dialog v-model="viewVisible" title="所选原始心电波形" width="min(1050px, 95vw)" append-to-body><ai-ecg-viewer v-if="viewVisible && selected" :source="selected" allow-download /><template #footer><el-button @click="viewVisible = false">关闭</el-button></template></el-dialog>
  </section>
</template>
<script setup>
import { computed, onActivated, onBeforeUnmount, onDeactivated, ref, watch } from "vue";
import { ElMessage, ElMessageBox } from "element-plus";
import { getAIEcgAsset, getAIEcgAssets, getAIEcgOptions, uploadAIEcg, withdrawAIEcg } from "@/api/ai";
import AiEcgViewer from "@/components/AIEcgViewer/index.vue";
const props = defineProps({ patientId: { type: Number, required: true }, encounterRef: { type: String, default: "" }, modelValue: { type: String, default: "" }, locked: Boolean });
const emit = defineEmits(["update:modelValue", "availability"]);
const loading = ref(false), uploading = ref(false), assets = ref([]), options = ref({}), truncated = ref(false), headerFile = ref(null), signalFile = ref(null), headerInput = ref(null), signalInput = ref(null), confirmed = ref(false), note = ref(""), recordedAt = ref(null), viewVisible = ref(false);
const statuses = { ready: "可读取", withdrawn: "已撤回", purge_pending: "清除中", purged: "原文件已清除" };
const selected = computed(() => assets.value.find(item => item.asset_id === props.modelValue));
const hasSamples = computed(() => selected.value?.signal_metadata?.leads.some(lead => lead.missing_samples < selected.value.signal_metadata.sample_count));
let scope = 0, listRequest = 0, uploadRequest = 0, inactive = false;
function clearFiles() { headerFile.value = null; signalFile.value = null; if (headerInput.value) headerInput.value.value = ""; if (signalInput.value) signalInput.value.value = ""; }
function invalidate() { scope += 1; listRequest += 1; uploadRequest += 1; loading.value = false; uploading.value = false; clearFiles(); confirmed.value = false; note.value = ""; recordedAt.value = null; assets.value = []; viewVisible.value = false; emit("availability", false); }
async function refresh() {
  const epoch = scope, version = ++listRequest, patient = props.patientId, encounter = props.encounterRef; loading.value = true;
  try {
    const [list, config] = await Promise.all([getAIEcgAssets({ patient_id: patient, encounter_ref: encounter || undefined }), getAIEcgOptions()]);
    if (epoch !== scope || version !== listRequest) return;
    assets.value = list.data?.items || []; truncated.value = !!list.data?.truncated; options.value = config.data || {};
    if (props.locked && props.modelValue && !selected.value) {
      const response = await getAIEcgAsset(props.modelValue);
      if (epoch === scope && version === listRequest && response.data.patient_id === patient && (!encounter || response.data.encounter_ref === encounter)) assets.value.unshift(response.data);
    }
  } finally { if (epoch === scope && version === listRequest) loading.value = false; }
}
function choose(kind, event) {
  const file = event.target.files?.[0] || null;
  if (kind === "header") headerFile.value = file; else signalFile.value = file;
  if ((headerFile.value?.size || 0) + (signalFile.value?.size || 0) > (options.value.max_bytes || Infinity)) { clearFiles(); ElMessage.error("原文件总大小超过当前登记上限"); }
}
async function upload() {
  const epoch = scope, version = ++uploadRequest, patient = props.patientId, encounter = props.encounterRef;
  if (!confirmed.value || note.value.trim().length < 5 || !headerFile.value || !signalFile.value) return;
  const data = new FormData(); data.append("header", headerFile.value); data.append("signal", signalFile.value); data.append("patient_id", String(patient)); if (encounter) data.append("encounter_ref", encounter); data.append("authorization_confirmed", "true"); data.append("authorization_note", note.value.trim()); if (recordedAt.value) data.append("recorded_at", new Date(recordedAt.value).toISOString());
  uploading.value = true;
  try {
    const response = await uploadAIEcg(data);
    if (epoch !== scope || version !== uploadRequest) { ElMessage.info("登记已完成，当前患者或就诊已切换；请返回原患者核对心电目录"); return; }
    clearFiles(); await refresh(); if (epoch === scope && version === uploadRequest) { if (!assets.value.some(item => item.asset_id === response.data.asset_id)) assets.value.unshift(response.data); emit("update:modelValue", response.data.asset_id); ElMessage.success("原心电已登记，尚未调用模型"); }
  } finally { if (epoch === scope && version === uploadRequest) uploading.value = false; }
}
async function withdraw() {
  const item = selected.value, epoch = scope;
  try { const { value } = await ElMessageBox.prompt("撤回阻止后续模型使用及普通用户旧结果读取；不能收回已发出的请求或已下载资料。请填写原因", "撤回原始心电", { inputValidator: text => text?.trim().length >= 5 || "请填写至少5字的原因", confirmButtonText: "撤回原心电" }); await withdrawAIEcg(item.asset_id, { expected_revision: item.revision, reason: value.trim() }); if (epoch !== scope) return; emit("update:modelValue", ""); viewVisible.value = false; await refresh(); }
  catch (error) { if (error !== "cancel" && error !== "close") throw error; }
}
watch([() => props.patientId, () => props.encounterRef], () => { invalidate(); if (!props.locked) emit("update:modelValue", ""); if (props.patientId && !inactive) refresh(); }, { immediate: true });
watch([selected, hasSamples, loading], () => emit("availability", !!selected.value && selected.value.status === "ready" && !!hasSamples.value && !loading.value), { immediate: true });
onActivated(() => { if (inactive) { inactive = false; if (props.patientId) refresh(); } });
onDeactivated(() => { inactive = true; invalidate(); }); onBeforeUnmount(invalidate);
</script>
<style scoped>
.ecg-input { margin: 16px 0; padding: 12px; border: 1px solid var(--el-border-color); line-height: 1.7; }.file-row { margin: 10px 0; }.data-gap { color: #8b5d12; }
</style>
