<template>
  <section ref="container" class="ecg-viewer" aria-label="原始心电波形复核">
    <p>原文件 {{ source?.asset_id }}。横轴为相对采样时间，纵轴为按原增益、基线和单位换算的mV；各导联共用当前窗口的纵轴尺度。</p>
    <div class="controls">
      <label>起始样本 <el-input-number v-model="startSample" :min="0" :max="Math.max(0, total - 1)" :step="1" :precision="0" aria-label="心电起始样本" /></label>
      <label>窗口秒数 <el-select v-model="seconds" aria-label="心电窗口秒数" style="width: 100px"><el-option v-for="value in [1, 2, 5, 10, 30]" :key="value" :value="value" :label="`${value}秒`" :disabled="value * rate > 50000" /></el-select></label>
      <el-button :loading="loading" :disabled="!source?.asset_id" @click="load">{{ windowData ? '刷新波形' : '加载原始波形' }}</el-button>
      <el-button :disabled="loading || !windowData || startSample <= 0" @click="move(-1)">上一窗</el-button><el-button :disabled="loading || !windowData || windowData.end_sample_exclusive >= total" @click="move(1)">下一窗</el-button>
    </div>
    <p v-if="error" class="data-gap">{{ error }}</p>
    <template v-if="windowData">
      <p>已读取原样本 {{ windowData.start_sample }}–{{ windowData.end_sample_exclusive }}（结束不含）；{{ (windowData.start_sample / rate).toFixed(3) }}–{{ (windowData.end_sample_exclusive / rate).toFixed(3) }}秒。当前原文件状态：{{ statuses[windowData.status] || windowData.status }}，版本{{ windowData.revision }}。</p>
      <p v-if="windowData.decimated" class="data-gap">当前为保留极值的抽样概览，缺失区间断开；请缩小窗口查看完整采样点，不能把概览当作全部原始采样。</p>
      <p v-else>当前窗口显示全部原始采样点，缺失值保持缺失。</p>
      <p v-if="highlight">模型定位导联 {{ highlight.leads?.join('、') || '所示导联' }}，原样本 {{ highlight.start }}–{{ highlight.end }}（结束不含），待人工核对；不表示已确认病变或诊疗发生时间。</p>
      <div class="lead-grid">
        <div v-for="lead in windowData.leads" :key="lead.name" class="lead-panel">
          <strong>{{ lead.name }}</strong><span v-if="lead.missing_samples_in_window"> · 本窗缺失 {{ lead.missing_samples_in_window }} 个采样</span>
          <canvas :ref="el => bindCanvas(lead.name, el)" :aria-label="`导联 ${lead.name} 原始波形`" role="img" />
        </div>
      </div>
      <p>{{ windowData.scope_note }}</p>
    </template>
    <p>采样与幅度显示不证明设备校准、生理信号质量或诊断已验证；不补齐缺失导联、缺失采样或实际采集时间。</p>
    <div v-if="allowDownload" class="controls"><el-button :disabled="downloading" @click="download('header')">下载原头文件（可能含标识）</el-button><el-button :disabled="downloading" @click="download('pair')">下载原始成对文件（含原头注释）</el-button></div>
  </section>
</template>
<script setup>
import { computed, nextTick, onBeforeUnmount, onDeactivated, onMounted, ref, watch } from "vue";
import { getAIEcgContent, getAIEcgWindow } from "@/api/ai";
const props = defineProps({ source: { type: Object, required: true }, allowDownload: Boolean });
const container = ref(null), startSample = ref(0), seconds = ref(10), loading = ref(false), downloading = ref(false), windowData = ref(null), error = ref(""), highlight = ref(null);
const rate = computed(() => Number(props.source?.signal_metadata?.sample_rate_hz) || 1), total = computed(() => props.source?.signal_metadata?.sample_count || 1);
const statuses = { ready: "可读取", withdrawn: "已撤回", purge_pending: "清除中", purged: "已清除" };
const canvases = new Map(); let scope = 0, request = 0, observer, frame;
function bindCanvas(name, element) { if (element) canvases.set(name, element); else canvases.delete(name); }
function invalidate() { scope += 1; request += 1; loading.value = false; downloading.value = false; windowData.value = null; error.value = ""; highlight.value = null; startSample.value = 0; seconds.value = rate.value * 10 > 50000 ? 1 : 10; cancelAnimationFrame(frame); }
function scheduleDraw() { cancelAnimationFrame(frame); frame = requestAnimationFrame(draw); }
function draw() {
  const data = windowData.value; if (!data) return;
  const observed = Math.max(0, ...data.leads.flatMap(lead => lead.points.map(point => Math.abs(point.value_mv || 0)))), maximum = observed || 1;
  const unit = Math.pow(10, Math.floor(Math.log10(maximum))), limit = Math.ceil(maximum / unit) * unit;
  for (const lead of data.leads) {
    const canvas = canvases.get(lead.name); if (!canvas) continue;
    const width = Math.max(260, Math.round(canvas.getBoundingClientRect().width)), height = 150, dpr = Math.min(window.devicePixelRatio || 1, 2);
    canvas.width = width * dpr; canvas.height = height * dpr;
    const context = canvas.getContext("2d"); if (!context) continue;
    context.setTransform(dpr, 0, 0, dpr, 0, 0); context.fillStyle = "#ffffff"; context.fillRect(0, 0, width, height);
    const left = 65, right = width - 10, top = 12, bottom = height - 25;
    const x = sample => left + (sample - data.start_sample) / (data.end_sample_exclusive - data.start_sample) * (right - left);
    const y = value => (top + bottom) / 2 - value / limit * (bottom - top) / 2;
    context.font = "10px sans-serif"; context.strokeStyle = "#dce2eb"; context.lineWidth = 1; context.fillStyle = "#526172";
    for (const fraction of [0, 0.25, 0.5, 0.75, 1]) { const value = limit * (1 - fraction * 2); context.beginPath(); context.moveTo(left, y(value)); context.lineTo(right, y(value)); context.stroke(); context.fillText(`${Number(value.toPrecision(3))}mV`, 2, y(value) + 3); }
    for (const fraction of [0, 0.25, 0.5, 0.75, 1]) { const sample = data.start_sample + fraction * (data.end_sample_exclusive - data.start_sample); context.beginPath(); context.moveTo(x(sample), top); context.lineTo(x(sample), bottom); context.stroke(); context.fillText(`${(sample / rate.value).toFixed(2)}s`, Math.min(x(sample), right - 30), height - 6); }
    if (highlight.value && (!highlight.value.leads?.length || highlight.value.leads.includes(lead.name))) { context.fillStyle = "rgba(224,161,24,0.17)"; const start = Math.max(data.start_sample, highlight.value.start), end = Math.min(data.end_sample_exclusive, highlight.value.end); if (start < end) context.fillRect(x(start), top, x(end) - x(start), bottom - top); }
    context.strokeStyle = "#2165a1"; context.fillStyle = "#2165a1"; context.lineWidth = 1.3; context.beginPath(); let connected = false;
    for (const point of lead.points) { if (point.value_mv == null) { connected = false; continue; } if (!connected || point.break_before) { context.moveTo(x(point.sample), y(point.value_mv)); context.fillRect(x(point.sample) - 1, y(point.value_mv) - 1, 2, 2); } else context.lineTo(x(point.sample), y(point.value_mv)); connected = true; }
    context.stroke();
    if (lead.points.every(point => point.value_mv == null)) { context.fillStyle = "#8b5d12"; context.fillText("当前窗全部为缺失标记，未补写为0", left + 10, top + 25); }
  }
}
async function load() {
  if (!props.source?.asset_id) return;
  const epoch = scope, version = ++request, id = props.source.asset_id, hash = props.source.content_hash; loading.value = true; error.value = "";
  try {
    const response = await getAIEcgWindow(id, { start_sample: startSample.value, sample_count: Math.max(1, Math.min(50000, Math.round(seconds.value * rate.value))), max_points: 1000 });
    if (epoch !== scope || version !== request) return;
    if (response.data.asset_id !== id || response.data.content_hash !== hash) { windowData.value = null; error.value = "当前波形与所选冻结来源不匹配，已停止显示"; return; }
    windowData.value = response.data; await nextTick(); if (epoch === scope && version === request) scheduleDraw();
  } catch { if (epoch === scope && version === request) { windowData.value = null; error.value = "原始波形未能读取，请核对当前诊疗权限、原文件状态和存储"; } }
  finally { if (epoch === scope && version === request) loading.value = false; }
}
async function move(direction) { startSample.value = Math.max(0, Math.min(total.value - 1, startSample.value + direction * Math.max(1, Math.min(50000, Math.round(seconds.value * rate.value))))); await load(); }
async function seekTo(start, end, leads) { highlight.value = { start, end, leads }; startSample.value = Math.max(0, Math.min(total.value - 1, start - Math.round(rate.value / 2))); await load(); }
async function showRecording() { highlight.value = null; startSample.value = 0; await load(); }
async function download(part) {
  const epoch = scope, id = props.source.asset_id; downloading.value = true;
  try { const blob = await getAIEcgContent(id, part); if (epoch !== scope) return; const url = URL.createObjectURL(blob), element = document.createElement("a"); element.href = url; element.download = `ecg-${id}${part === 'header' ? '.hea' : '.zip'}`; element.click(); setTimeout(() => URL.revokeObjectURL(url), 1000); }
  finally { if (epoch === scope) downloading.value = false; }
}
watch([() => props.source?.asset_id, () => props.source?.content_hash], invalidate, { immediate: true });
watch(highlight, scheduleDraw);
onMounted(() => { if (window.ResizeObserver) { observer = new ResizeObserver(scheduleDraw); observer.observe(container.value); } });
onDeactivated(invalidate); onBeforeUnmount(() => { invalidate(); observer?.disconnect(); });
defineExpose({ seekTo, showRecording });
</script>
<style scoped>
.ecg-viewer { line-height: 1.7; padding: 10px 0; }.controls { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; }.lead-grid { display: grid; grid-template-columns: repeat(auto-fit,minmax(300px,1fr)); gap: 12px; }.lead-panel { min-width: 0; border: 1px solid #dce2eb; padding: 6px; }.lead-panel canvas { display: block; width: 100%; height: 150px; }.data-gap { color: #8b5d12; }
</style>
