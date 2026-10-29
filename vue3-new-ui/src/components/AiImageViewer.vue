<template>
  <section class="ai-image-viewer" aria-label="原始单帧影像复核">
    <p>当前来源 {{ sourceId || '未选择' }}；每次显示一张图像。</p>
    <p v-if="metadata">原始 {{ metadata.columns }}列 × {{ metadata.rows }}行；{{ metadata.modality || 'unknown' }}，部位 {{ metadata.body_part_examined || 'unknown' }}，体位 {{ metadata.view_position || 'unknown' }}。按存储行列显示，不推定解剖左右或病灶实际尺寸。</p>
    <p v-if="metadata?.burned_in_annotation !== 'NO'" class="data-gap">像素内是否含文字标识：{{ metadata?.burned_in_annotation || 'unknown' }}。请核对像素中的身份信息。</p>
    <el-button :loading="loading" :disabled="!sourceId || disabled" @click="load">{{ pixels ? '重新读取原始像素' : '加载原始影像像素' }}</el-button>
    <p v-if="error" role="alert" class="data-gap">{{ error }}</p>
    <template v-if="pixels && metadata">
      <div class="image-controls">
        <label>显示窗 <el-select v-model="windowChoice" aria-label="影像显示窗" style="width: 230px" @change="chooseWindow"><el-option v-for="(preset, index) in metadata.window_presets" :key="index" :value="`preset:${index}`" :label="`原窗${index + 1} · WL ${preset.center} / WW ${preset.width}`" /><el-option value="auto" label="自动全范围（仅显示选项）" /><el-option value="manual" label="自定义显示窗" /></el-select></label>
        <label>窗位 WL <input v-model.number="center" type="number" step="any" aria-label="影像窗位WL" @change="windowChoice = 'manual'" /></label>
        <label>窗宽 WW <input v-model.number="width" type="number" step="any" aria-label="影像窗宽WW" @change="windowChoice = 'manual'" /></label>
        <label>窗函数 <el-select v-model="voi" aria-label="影像窗函数" style="width: 155px" @change="windowChoice = 'manual'"><el-option v-for="name in VOI_FUNCTIONS" :key="name" :value="name" :label="name" /></el-select></label>
      </div>
      <p>{{ windowChoice === 'auto' ? '自动采用非填充像素的重标定最小值和最大值。' : windowChoice === 'manual' ? '当前为人工调整的显示窗，不写回原文件或诊断结论。' : '使用原文件中的窗预设。' }} {{ metadata.invert_display ? '按已核对的原灰阶关系反转一次。' : '按已核对的原灰阶关系显示。' }} 填充值始终显示为黑色。</p>
      <div class="image-controls"><el-button aria-label="放大原始影像" :disabled="zoom >= 12" @click="changeZoom(zoom * 1.25)">放大</el-button><el-button aria-label="缩小原始影像" :disabled="zoom <= 0.25" @click="changeZoom(zoom / 1.25)">缩小</el-button><el-button @click="resetView">适合窗口并复位</el-button><span>缩放 {{ Math.round(zoom * 100) }}% · 拖动平移、滚轮缩放</span></div>
      <div ref="viewport" class="image-viewport"><canvas ref="canvas" role="img" aria-label="原始行列灰阶影像" :data-source-asset-id="loaded?.asset_id || ''" @pointerdown="pointerDown" @pointermove="pointerMove" @pointerup="pointerUp" @pointercancel="pointerUp" @pointerleave="cursor = null" @wheel.prevent="wheel" /></div>
      <p v-if="renderError" role="alert" class="data-gap">{{ renderError }}</p>
      <p v-if="cursor">原始像素坐标（0起始）：列 {{ cursor.column }}，行 {{ cursor.row }}；{{ cursor.padding ? '此处为原始填充值' : `stored ${cursor.stored}，重标定值 ${cursor.scaled}` }}。此处未进行解剖定位或长度测量。</p>
      <p v-else>在图上移动可核对原始行、列和灰阶值；不添加左右方向或测量标记。</p>
      <p v-if="metadata.valid_pixel_count === 0" class="data-gap">影像全部为填充值，请上传含有效像素的影像。</p>
      <p>PixelSpacing（原行/列间距）：{{ spacing(metadata.pixel_spacing_mm) }}；ImagerPixelSpacing（原探测器行/列间距）：{{ spacing(metadata.imager_pixel_spacing_mm) }}。两类间距分别保留，不推定实际病灶尺寸。</p>
    </template>
  </section>
</template>

<script setup>
import { computed, nextTick, onActivated, onBeforeUnmount, onDeactivated, onMounted, ref, shallowRef, watch } from "vue";
import request from "@/utils/request";
import store from "@/store";
import { automaticImageWindow, decodeImagePixels, isPadding, renderImagePixels, validateImageMetadata, verifyImagePixelHash, VOI_FUNCTIONS } from "@/utils/aiImagePixels";

const props = defineProps({ asset: { type: Object, default: null }, source: { type: Object, default: null }, assetId: { type: String, default: "" }, patientId: { type: [Number, String], default: null }, encounterRef: { type: String, default: "" }, imagingOrderId: { type: String, default: "" }, disabled: Boolean });
const given = computed(() => props.asset || props.source);
const sourceId = computed(() => given.value?.asset_id || props.assetId);
const loaded = shallowRef(null), pixels = shallowRef(null), loading = ref(false), error = ref(""), renderError = ref("");
const metadata = computed(() => loaded.value?.image_metadata || given.value?.image_metadata || null);
const canvas = ref(null), viewport = ref(null), center = ref(0), width = ref(1), voi = ref("LINEAR"), windowChoice = ref("auto"), zoom = ref(1), panX = ref(0), panY = ref(0), cursor = ref(null);
let epoch = 0, sequence = 0, imageFrame, screenFrame, observer, rawCanvas = null, drag = null, geometry = null, inactive = false;

function spacing(value) { return Array.isArray(value) && value.length === 2 && value.every(item => Number.isFinite(item) && item > 0) ? `${value[0]} / ${value[1]} mm` : '未记录，不按显示尺寸推定'; }
function clearRawCanvas() { if (rawCanvas) { rawCanvas.width = 0; rawCanvas.height = 0; rawCanvas = null; } }
function invalidate() {
  epoch++; sequence++; loading.value = false; loaded.value = null; pixels.value = null; error.value = ""; renderError.value = ""; cursor.value = null; drag = null; geometry = null;
  cancelAnimationFrame(imageFrame); cancelAnimationFrame(screenFrame); observer?.disconnect(); clearRawCanvas();
  if (canvas.value) { const context = canvas.value.getContext("2d"); context?.clearRect(0, 0, canvas.value.width, canvas.value.height); }
  zoom.value = 1; panX.value = 0; panY.value = 0;
}
function bindingMatches(candidate, expected) {
  return candidate?.asset_id === sourceId.value && (!expected?.content_hash || candidate.content_hash === expected.content_hash) && (!expected?.pixel_hash || candidate.pixel_hash === expected.pixel_hash)
    && (props.patientId == null || candidate.patient_id == null || String(candidate.patient_id) === String(props.patientId))
    && (!props.imagingOrderId || candidate.imaging_order_id === props.imagingOrderId) && (!props.encounterRef || candidate.encounter_ref === props.encounterRef);
}
async function load() {
  if (!sourceId.value || props.disabled || inactive) return;
  const currentEpoch = epoch, currentSequence = ++sequence, id = sourceId.value;
  const expected = given.value ? JSON.parse(JSON.stringify(given.value)) : null;
  loading.value = true; error.value = ""; renderError.value = ""; pixels.value = null; loaded.value = null; geometry = null; drag = null; cursor.value = null; observer?.disconnect(); clearRawCanvas();
  await nextTick();
  try {
    if (currentEpoch !== epoch || currentSequence !== sequence) return;
    if (props.assetId && expected?.asset_id && props.assetId !== expected.asset_id) throw new Error("所选原图标识与冻结来源不符");
    let detail = expected;
    if (!detail?.image_metadata || !detail?.pixel_hash) {
      const response = await request({ url: `ai/image-assets/${encodeURIComponent(id)}`, method: "get", retry: 0 });
      if (currentEpoch !== epoch || currentSequence !== sequence) return;
      detail = response.data;
    }
    if (!bindingMatches(detail, expected)) throw new Error("原图与当前患者、申请、就诊或冻结来源不一致");
    validateImageMetadata(detail.image_metadata);
    const buffer = await request({ url: `ai/image-assets/${encodeURIComponent(id)}/pixels`, method: "get", responseType: "arraybuffer", timeout: 120000, retry: 0 });
    if (currentEpoch !== epoch || currentSequence !== sequence) return;
    await verifyImagePixelHash(buffer, detail.pixel_hash);
    if (currentEpoch !== epoch || currentSequence !== sequence || sourceId.value !== id) return;
    const decoded = decodeImagePixels(buffer, detail.image_metadata);
    loaded.value = detail; pixels.value = decoded; resetView();
    chooseWindow(detail.image_metadata.window_presets.length ? 'preset:0' : 'auto');
    await nextTick(); if (currentEpoch === epoch && currentSequence === sequence) { if (viewport.value) observer?.observe(viewport.value); scheduleImage(); }
  } catch (failure) {
    if (currentEpoch === epoch && currentSequence === sequence) { pixels.value = null; loaded.value = null; clearRawCanvas(); error.value = failure?.message || "原始像素未能读取，请核对当前权限、原文件状态与私有存储"; }
  } finally { if (currentEpoch === epoch && currentSequence === sequence) loading.value = false; }
}
function chooseWindow(choice) {
  windowChoice.value = choice;
  if (!pixels.value || !metadata.value || choice === 'manual') return;
  const preset = choice === 'auto' ? automaticImageWindow(pixels.value, metadata.value) : { ...metadata.value.window_presets[Number(choice.split(':')[1])], function: metadata.value.voi_lut_function };
  if (!preset) { center.value = 0; width.value = 1; voi.value = 'LINEAR_EXACT'; return; }
  center.value = preset.center; width.value = preset.width; voi.value = preset.function;
}
function scheduleImage() { cancelAnimationFrame(imageFrame); if (!inactive) imageFrame = requestAnimationFrame(renderOriginal); }
function scheduleScreen() { cancelAnimationFrame(screenFrame); if (!inactive) screenFrame = requestAnimationFrame(drawScreen); }
function renderOriginal() {
  if (!pixels.value || !loaded.value) return;
  try {
    const m = loaded.value.image_metadata, rgba = renderImagePixels(pixels.value, m, { center: center.value, width: width.value, function: voi.value });
    if (!rawCanvas) rawCanvas = document.createElement('canvas');
    rawCanvas.width = m.columns; rawCanvas.height = m.rows;
    const context = rawCanvas.getContext('2d'); if (!context) throw new Error('浏览器无法建立原始灰阶画布');
    context.putImageData(new ImageData(rgba, m.columns, m.rows), 0, 0); renderError.value = '';
  } catch (failure) { clearRawCanvas(); renderError.value = failure?.message || '显示窗无效，已停止显示'; }
  scheduleScreen();
}
function drawScreen() {
  if (!canvas.value || !viewport.value || !metadata.value) return;
  const element = canvas.value, rect = viewport.value.getBoundingClientRect(), width = Math.max(1, Math.round(rect.width)), height = 480, dpr = Math.min(window.devicePixelRatio || 1, 2);
  element.width = Math.round(width * dpr); element.height = Math.round(height * dpr);
  const context = element.getContext('2d'); if (!context) return;
  context.setTransform(dpr, 0, 0, dpr, 0, 0); context.fillStyle = '#000'; context.fillRect(0, 0, width, height);
  if (!rawCanvas) { geometry = null; return; }
  const m = metadata.value, scale = Math.min(width / m.columns, height / m.rows) * zoom.value;
  const left = (width - m.columns * scale) / 2 + panX.value, top = (height - m.rows * scale) / 2 + panY.value;
  context.imageSmoothingEnabled = false; context.drawImage(rawCanvas, left, top, m.columns * scale, m.rows * scale); geometry = { left, top, scale };
}
function resetView() { zoom.value = 1; panX.value = 0; panY.value = 0; cursor.value = null; scheduleScreen(); }
function changeZoom(value, point = null) {
  const next = Math.max(0.25, Math.min(12, value));
  if (point && geometry && viewport.value) {
    const rect = viewport.value.getBoundingClientRect(), factor = next / zoom.value;
    panX.value = point.x - rect.width / 2 - factor * (point.x - rect.width / 2 - panX.value);
    panY.value = point.y - 480 / 2 - factor * (point.y - 480 / 2 - panY.value);
  }
  zoom.value = next; scheduleScreen();
}
function eventPoint(event) { const rect = canvas.value.getBoundingClientRect(); return { x: event.clientX - rect.left, y: event.clientY - rect.top }; }
function pointerDown(event) { if (!pixels.value || event.button !== 0) return; drag = { x: event.clientX, y: event.clientY, panX: panX.value, panY: panY.value }; event.currentTarget.setPointerCapture?.(event.pointerId); }
function pointerMove(event) {
  if (drag) { panX.value = drag.panX + event.clientX - drag.x; panY.value = drag.panY + event.clientY - drag.y; scheduleScreen(); }
  if (!geometry || !pixels.value || !metadata.value) { cursor.value = null; return; }
  const point = eventPoint(event), column = Math.floor((point.x - geometry.left) / geometry.scale), row = Math.floor((point.y - geometry.top) / geometry.scale), m = metadata.value;
  if (column < 0 || row < 0 || column >= m.columns || row >= m.rows) { cursor.value = null; return; }
  const stored = pixels.value[row * m.columns + column], scaled = stored * m.rescale_slope + m.rescale_intercept;
  cursor.value = { column, row, stored, scaled: Number(scaled.toPrecision(8)), padding: isPadding(stored, m.padding) };
}
function pointerUp(event) { drag = null; if (event.currentTarget.hasPointerCapture?.(event.pointerId)) event.currentTarget.releasePointerCapture(event.pointerId); }
function wheel(event) { if (pixels.value) changeZoom(zoom.value * (event.deltaY < 0 ? 1.15 : 1 / 1.15), eventPoint(event)); }

watch(() => JSON.stringify([sourceId.value, given.value?.content_hash, given.value?.pixel_hash, given.value?.revision, given.value?.status, given.value?.patient_id, given.value?.imaging_order_id, given.value?.encounter_ref, given.value?.image_metadata, props.patientId, props.imagingOrderId, props.encounterRef, store.state.user.accessToken]), invalidate, { immediate: true });
watch([center, width, voi], scheduleImage);
onMounted(() => { if (window.ResizeObserver) observer = new ResizeObserver(scheduleScreen); });
onActivated(() => { inactive = false; if (viewport.value) observer?.observe(viewport.value); });
onDeactivated(() => { inactive = true; observer?.disconnect(); invalidate(); });
onBeforeUnmount(() => { inactive = true; observer?.disconnect(); invalidate(); });
defineExpose({ load, loadPixels: load, clear: invalidate });
</script>

<style scoped>
.ai-image-viewer { line-height: 1.7; }.image-controls { display: flex; flex-wrap: wrap; align-items: center; gap: 10px; margin: 12px 0; }.image-controls label { display: inline-flex; align-items: center; gap: 6px; }.image-controls input { width: 120px; padding: 5px; border: 1px solid var(--el-border-color); border-radius: 4px; }.image-viewport { width: 100%; height: 480px; overflow: hidden; background: #000; }.image-viewport canvas { width: 100%; height: 480px; display: block; touch-action: none; cursor: grab; }.image-viewport canvas:active { cursor: grabbing; }.data-gap { color: #8b5d12; }
</style>
