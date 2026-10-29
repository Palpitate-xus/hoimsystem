<template>
  <section class="audio-input" v-loading="loading" aria-label="医疗录音登记与选择">
    <el-form-item label="已登记录音">
      <el-select :model-value="modelValue || null" :disabled="loading || locked || recording || capturePending || uploading" clearable filterable placeholder="明确选择本患者的原录音" aria-label="待转写原录音" style="width: 100%" @update:model-value="$emit('update:modelValue', $event || '')"><el-option v-for="item in assets" :key="item.asset_id" :value="item.asset_id" :disabled="item.status !== 'ready'" :label="`录音 ${item.asset_id.slice(0,8)} · ${(item.duration_ms / 1000).toFixed(2)}秒 · ${statuses[item.status]} · 登记于${item.create_time || '未知'}`" /></el-select>
      <el-button :disabled="uploading || recording" @click="refresh">刷新录音</el-button>
    </el-form-item>
    <p v-if="selected">原录音时间：{{ selected.recorded_at || '未记录，不以登记时间代替' }}；原格式：{{ selected.media_type }}；解码时长：{{ (selected.duration_ms / 1000).toFixed(2) }}秒。</p>
    <el-button v-if="selected?.status === 'ready'" size="small" type="warning" :disabled="uploading || recording" @click="withdrawSelected">撤回所选录音</el-button>
    <p v-if="truncated">仅列近期50项，可从明确录音的业务入口选择旧记录。</p>
    <el-collapse v-if="!locked">
      <el-collapse-item title="登记新录音或使用麦克风采集">
        <p v-if="noticeText(options.scope_note)">{{ noticeText(options.scope_note) }}</p>
        <p>支持WAV、MP3、M4A、Ogg、WebM；单文件{{ mib(options.max_bytes) }} MiB，最长{{ options.max_duration_seconds ?? '待读取' }}秒。本人登记用量{{ mib(options.used_bytes) }} / {{ mib(options.user_quota_bytes) }} MiB。</p>
        <el-alert v-if="options.processor_available === false" title="录音处理组件尚未就绪，请联系超级管理员核对部署。" type="warning" :closable="false" />
        <el-checkbox v-model="authorizationConfirmed" :disabled="recording || capturePending || uploading">我已核对该录音的采集、处理授权及所选患者和就诊</el-checkbox>
        <el-input v-model="authorizationNote" type="textarea" :rows="2" maxlength="1000" :disabled="recording || capturePending || uploading" placeholder="填写授权依据与核对说明（至少5字）；不写无关身份或联系方式" aria-label="录音授权说明" />
        <div class="record-controls">
          <el-button :loading="capturePending" :disabled="loading || !canCapture || !authorized || uploading || recording || options.processor_available === false" @click="startCapture">开始录音</el-button>
          <el-button v-if="recording" type="danger" @click="stopCapture(false)">停止录音</el-button><span v-if="recording">采集端计时：{{ elapsed }}秒</span>
        </div>
        <p v-if="!canCapture">当前环境不能使用麦克风采集，可上传已有的授权录音。</p>
        <input ref="fileInput" type="file" accept=".wav,.mp3,.m4a,.ogg,.oga,.webm" :disabled="uploading || recording || capturePending" aria-label="选择授权录音文件" @change="chooseFile" />
        <p v-if="selectedFile">待登记文件：{{ selectedFile.name }}（{{ mib(selectedFile.size) }} MiB），尚未上传。</p>
        <el-form-item label="原录音时间（可选）"><el-date-picker v-model="recordedAt" type="datetime" :disabled="uploading || recording || capturePending" placeholder="原文件未记录则留空；不默认当前时间" /></el-form-item>
        <el-button type="primary" :loading="uploading" :disabled="!authorized || !selectedFile || recording || capturePending || options.processor_available === false" @click="upload">登记所选录音</el-button>
        <p>登记仅保存录音，不调用模型。转写时原音频会发给本功能已配置的专用服务；上传与转写均不会自动写入病历。</p>
      </el-collapse-item>
    </el-collapse>
  </section>
</template>
<script setup>
import { noticeText, noticeList } from "@/utils/noticeText.cjs";
import { computed, onBeforeUnmount, onDeactivated, ref, shallowRef, watch } from "vue";
import { ElMessage, ElMessageBox } from "element-plus";
import { getAIAudioAsset, getAIAudioAssets, getAIAudioOptions, uploadAIAudio, withdrawAIAudio } from "@/api/ai";
const props = defineProps({ patientId: { type: Number, required: true }, encounterRef: { type: String, default: "" }, modelValue: { type: String, default: "" }, locked: Boolean });
const emit = defineEmits(["update:modelValue", "availability"]);
const loading = ref(false), uploading = ref(false), assets = ref([]), options = ref({}), truncated = ref(false), selectedFile = shallowRef(null), fileInput = ref(null);
const authorizationConfirmed = ref(false), authorizationNote = ref(""), recordedAt = ref(null), recording = ref(false), capturePending = ref(false), elapsed = ref(0);
const statuses = { ready: "可用", withdrawn: "已撤回", purge_pending: "清除中", purged: "原文件已清除" };
const selected = computed(() => assets.value.find(item => item.asset_id === props.modelValue));
const authorized = computed(() => authorizationConfirmed.value && authorizationNote.value.trim().length >= 5);
const canCapture = computed(() => !!navigator.mediaDevices?.getUserMedia && typeof MediaRecorder !== "undefined");
const mib = number => number == null ? "待读取" : (number / 1048576).toFixed(2);
let scopeVersion = 0, listVersion = 0, captureVersion = 0, recorder = null, stream = null, timer = null, discardCapture = false;
watch(selected, item => emit("availability", item?.status === "ready"), { immediate: true });
function stopTracks() { stream?.getTracks().forEach(track => track.stop()); stream = null; clearInterval(timer); timer = null; }
function stopCapture(discard = true) { discardCapture = discard; if (recorder && recorder.state !== "inactive") recorder.stop(); stopTracks(); recording.value = false; }
async function refresh() {
  const current = scopeVersion, request = ++listVersion; loading.value = true;
  try {
    const [catalog, limits] = await Promise.all([getAIAudioAssets({ patient_id: props.patientId, encounter_ref: props.encounterRef || undefined }), getAIAudioOptions()]);
    if (current !== scopeVersion || request !== listVersion) return;
    assets.value = catalog.data?.items || []; options.value = limits.data || {}; truncated.value = !!catalog.data?.truncated;
    if (props.locked && props.modelValue && !selected.value) { const detail = await getAIAudioAsset(props.modelValue); if (current === scopeVersion && request === listVersion) assets.value.unshift(detail.data); }
  } finally { if (current === scopeVersion && request === listVersion) loading.value = false; }
}
function chooseFile(event) {
  selectedFile.value = event.target.files?.[0] || null; recordedAt.value = null; authorizationConfirmed.value = false;
  if (selectedFile.value && options.value.max_bytes && selectedFile.value.size > options.value.max_bytes) { ElMessage.error("所选录音超过当前大小限制"); selectedFile.value = null; }
}
async function startCapture() {
  if (!authorized.value || !canCapture.value || recording.value || capturePending.value || uploading.value || loading.value) return;
  const current = scopeVersion, capture = ++captureVersion; capturePending.value = true; selectedFile.value = null;
  try {
    const captured = await navigator.mediaDevices.getUserMedia({ audio: true });
    if (current !== scopeVersion || capture !== captureVersion) { captured.getTracks().forEach(track => track.stop()); return; }
    stream = captured;
    const mimeType = ["audio/webm;codecs=opus", "audio/ogg;codecs=opus", "audio/mp4"].find(type => MediaRecorder.isTypeSupported(type));
    recorder = new MediaRecorder(stream, mimeType ? { mimeType } : undefined);
    const activeRecorder = recorder, chunks = []; let size = 0; discardCapture = false;
    recordedAt.value = new Date(); const started = Date.now(); elapsed.value = 0;
    activeRecorder.ondataavailable = event => {
      if (current !== scopeVersion || capture !== captureVersion || discardCapture || !event.data.size) return;
      size += event.data.size;
      if (size > options.value.max_bytes) { discardCapture = true; stopCapture(true); ElMessage.error("录音超过大小限制，本次采集未登记，请缩短录音"); return; }
      chunks.push(event.data);
    };
    activeRecorder.onstop = () => {
      if (current !== scopeVersion || capture !== captureVersion) { captured.getTracks().forEach(track => track.stop()); chunks.length = 0; return; }
      stopTracks(); recording.value = false;
      recorder = null;
      if (discardCapture || !size) { chunks.length = 0; return; }
      const type = activeRecorder.mimeType || mimeType || "", extension = type.startsWith("audio/mp4") ? ".m4a" : type.startsWith("audio/ogg") ? ".ogg" : type.startsWith("audio/webm") ? ".webm" : null;
      if (!extension) { ElMessage.error("浏览器录音编码暂不支持，请使用授权原文件上传"); return; }
      selectedFile.value = new File(chunks, "recording" + extension, { type });
      chunks.length = 0;
    };
    activeRecorder.onerror = () => { if (current !== scopeVersion || capture !== captureVersion) { captured.getTracks().forEach(track => track.stop()); return; } stopCapture(true); ElMessage.error("录音失败，请检查麦克风后重新采集"); };
    activeRecorder.start(1000); recording.value = true;
    timer = setInterval(() => { elapsed.value = Math.floor((Date.now() - started) / 1000); if (elapsed.value >= options.value.max_duration_seconds) { stopCapture(false); ElMessage.info("已达到录音时长限制，请核对后登记"); } }, 500);
  } catch { if (current === scopeVersion && capture === captureVersion) { stopCapture(true); ElMessage.error("无法使用麦克风，请检查浏览器权限或上传授权录音"); } }
  finally { if (current === scopeVersion && capture === captureVersion) capturePending.value = false; }
}
async function upload() {
  if (!selectedFile.value || !authorized.value) return;
  const current = scopeVersion, data = new FormData();
  data.append("file", selectedFile.value); data.append("patient_id", String(props.patientId)); if (props.encounterRef) data.append("encounter_ref", props.encounterRef);
  data.append("authorization_confirmed", "true"); data.append("authorization_note", authorizationNote.value.trim()); if (recordedAt.value) data.append("recorded_at", new Date(recordedAt.value).toISOString());
  uploading.value = true;
  try {
    const response = await uploadAIAudio(data);
    if (current !== scopeVersion) { ElMessage.info("登记请求已完成，当前患者已切换；请返回原患者核对录音目录"); return; }
    selectedFile.value = null; recordedAt.value = null; authorizationConfirmed.value = false; authorizationNote.value = ""; if (fileInput.value) fileInput.value.value = "";
    await refresh(); if (current === scopeVersion) emit("update:modelValue", response.data.asset_id); ElMessage.success("原录音已登记，尚未调用模型");
  } finally { if (current === scopeVersion) uploading.value = false; }
}
async function withdrawSelected() {
  const source = selected.value; if (!source) return;
  try {
    const { value } = await ElMessageBox.prompt("撤回将阻止后续转写和普通用户历史读取；不能收回已发出的模型请求或已读取资料。请填写原因", "撤回所选录音", { inputValidator: value => value?.trim().length >= 5 || "请填写至少5字的原因", confirmButtonText: "撤回录音" });
    await withdrawAIAudio(source.asset_id, { expected_revision: source.revision, reason: value.trim() }); emit("update:modelValue", ""); await refresh();
  } catch (error) { if (error !== "cancel" && error !== "close") throw error; }
}
function invalidate() { scopeVersion += 1; listVersion += 1; captureVersion += 1; stopCapture(true); if (recorder) { recorder.ondataavailable = null; recorder.onstop = null; recorder.onerror = null; recorder = null; } capturePending.value = false; uploading.value = false; selectedFile.value = null; recordedAt.value = null; authorizationConfirmed.value = false; authorizationNote.value = ""; }
watch([() => props.patientId, () => props.encounterRef], () => { invalidate(); assets.value = []; truncated.value = false; if (!props.locked) emit("update:modelValue", ""); refresh(); }, { immediate: true });
onDeactivated(invalidate); onBeforeUnmount(invalidate);
</script>
<style scoped>
.audio-input { border: 1px solid var(--el-border-color); border-radius: 6px; padding: 14px; margin: 12px 0; line-height: 1.7; }.record-controls { display: flex; gap: 10px; align-items: center; margin: 12px 0; }.el-textarea { margin-top: 10px; }
</style>
