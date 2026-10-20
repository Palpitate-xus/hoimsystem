<template>
  <section class="ai-image-input" aria-label="原始影像登记与选择">
    <h4>选择本患者的真实影像申请与原文件</h4>
    <label>影像申请 <el-select :model-value="orderId || null" :disabled="disabled || !!lockedOrderId || uploading || loading" clearable filterable aria-label="原始影像申请" placeholder="明确选择原申请，不按时间推定就诊" style="width: 100%" @update:model-value="setOrder"><el-option v-for="order in orders" :key="order.imaging_order_id" :value="order.imaging_order_id" :label="orderLabel(order)" /></el-select></label>
    <p>{{ orderScopeNote || '申请文字仅用于院内核对；申请与就诊的关联须另行明确，不按申请日期推定。' }}</p>
    <p v-if="selectedOrder?.status === 5 || selected?.order_status === 5" class="data-gap">原申请已取消，可核对原记录，不能继续登记或生成识别候选。</p>
    <p v-if="ordersTruncated">申请清单仅显示近期100项，不能据此断言不存在其他申请。</p>
    <label>原始影像 <el-select :model-value="selectedId || null" :disabled="disabled || uploading || loading || assetsLoading || !orderId" clearable filterable aria-label="待复核原始影像" placeholder="选择已登记的单帧DICOM原图" style="width: 100%" @update:model-value="selectAsset"><el-option v-for="item in assets" :key="item.asset_id" :value="item.asset_id" :disabled="item.status !== 'ready'" :label="assetLabel(item)" /></el-select></label>
    <p>{{ options.scope_note || '登记与预览不调用模型；当前诊疗成员按原患者、申请与就诊权限核对。' }}</p>
    <p v-if="error" role="alert" class="data-gap">{{ error }}</p>
    <template v-if="selected">
      <p>原申请 {{ selected.imaging_order_id }}；原就诊 {{ selected.encounter_ref || '未记录，不按日期推定' }}；采集时刻 {{ selected.recorded_at || '未核实，不以登记时刻或DICOM时钟代替' }}。</p>
      <p>{{ selected.image_metadata?.modality || 'unknown' }} · {{ selected.image_metadata?.columns }}列 × {{ selected.image_metadata?.rows }}行 · {{ statuses[selected.status] || selected.status }}。单张图像不代表完整序列或全部检查。</p>
      <p v-if="selected.image_metadata?.valid_pixel_count === 0" class="data-gap">原图全部为填充值，可核查原记录，不能生成识别候选。</p>
      <el-button :disabled="uploading" @click="viewVisible = true">查看所选原始影像</el-button><el-button v-if="selected.can_withdraw" type="warning" :disabled="disabled || uploading" @click="withdraw">撤回所选原始影像</el-button>
    </template>
    <p v-if="assetsTruncated">原图清单仅显示近期50项，可通过原申请缩小范围。</p>
    <el-collapse><el-collapse-item title="登记单帧DICOM原始影像">
      <p>支持单帧、8/16位原生小端灰阶DICOM；不选择压缩、多帧、容积的首张图替代完整资料，不用截图、报告文字或外部URL代替原始像素。</p>
      <label class="file-row">原始DICOM文件 <input ref="fileInput" type="file" accept=".dcm,application/dicom" aria-label="选择原始DICOM文件" :disabled="disabled || uploading || !orderId" @change="chooseFile" /></label>
      <p>原文件上限 {{ options.max_bytes ? `${Math.floor(options.max_bytes / 1048576)} MiB` : '尚未读取' }}；像素上限 {{ options.max_pixels || '尚未读取' }}；当前登记用量 {{ Math.ceil((options.used_bytes || 0) / 1048576) }} MiB。</p>
      <el-checkbox v-model="confirmed" :disabled="disabled || uploading">我已核对来源、使用授权、患者与原影像申请及所选就诊的关联</el-checkbox>
      <el-input v-model="note" type="textarea" :rows="2" maxlength="1000" aria-label="原影像来源与授权核对说明" placeholder="填写明确来源、患者/申请/就诊关联与授权核对依据，至少5字" :disabled="disabled || uploading" />
      <el-form-item label="经核实的原采集时刻（可选）"><el-date-picker v-model="recordedAt" type="datetime" placeholder="未知时留空，不默认当前时间" :disabled="disabled || uploading" /></el-form-item>
      <el-button type="primary" :disabled="!canUpload" :loading="uploading" @click="upload">登记原始影像</el-button>
    </el-collapse-item></el-collapse>
    <el-dialog v-model="viewVisible" title="所选单帧原始影像" width="min(1100px, 96vw)" append-to-body destroy-on-close><ai-image-viewer v-if="viewVisible && selected" :asset="selected" :patient-id="patientId" :encounter-ref="encounterRef" :imaging-order-id="orderId" /><template #footer><el-button @click="viewVisible = false">关闭</el-button></template></el-dialog>
  </section>
</template>

<script setup>
import { computed, onActivated, onBeforeUnmount, onDeactivated, ref, watch } from "vue";
import { ElMessage, ElMessageBox } from "element-plus";
import request from "@/utils/request";
import store from "@/store";
import AiImageViewer from "./AiImageViewer.vue";

const props = defineProps({ patientId: { type: [Number, String], required: true }, encounterRef: { type: String, default: "" }, lockedOrderId: { type: String, default: "" }, disabled: Boolean, modelValue: { type: String, default: "" } });
const emit = defineEmits(["select", "update:modelValue", "availability", "order-change"]);
const orders = ref([]), orderId = ref(props.lockedOrderId), selectedId = ref(props.modelValue), assets = ref([]), options = ref({}), loading = ref(false), assetsLoading = ref(false), uploading = ref(false), error = ref(""), orderScopeNote = ref(""), ordersTruncated = ref(false), assetsTruncated = ref(false);
const fileInput = ref(null), imageFile = ref(null), confirmed = ref(false), note = ref(""), recordedAt = ref(null), viewVisible = ref(false);
const selected = computed(() => assets.value.find(item => item.asset_id === selectedId.value));
const selectedOrder = computed(() => orders.value.find(item => item.imaging_order_id === orderId.value));
const statuses = { ready: "可读取", withdrawn: "已撤回", purge_pending: "清除中", purged: "原文件已清除" }, orderStatuses = ["申请", "检查中", "待报告", "已报告", "已审核", "取消"];
const canUpload = computed(() => !props.disabled && !loading.value && !assetsLoading.value && !uploading.value && !!props.patientId && !!orderId.value && selectedOrder.value?.status !== 5 && !!options.value.max_bytes && !!imageFile.value && confirmed.value && note.value.trim().length >= 5);
let epoch = 0, listSequence = 0, assetSequence = 0, uploadSequence = 0, inactive = false, initial = true;

function orderLabel(order) { return `${order.modality || 'unknown'} · ${order.body_part || '部位未列出'} · ${order.accession_no || order.imaging_order_id} · ${orderStatuses[order.status] || '当前状态待核对'}`; }
function assetLabel(item) { return `原图 ${item.asset_id.slice(0, 8)} · ${item.image_metadata?.modality || 'unknown'} · ${item.image_metadata?.columns}×${item.image_metadata?.rows} · ${statuses[item.status] || item.status}`; }
function clearFile() { imageFile.value = null; if (fileInput.value) fileInput.value.value = ''; confirmed.value = false; note.value = ''; recordedAt.value = null; }
function publishSelection(id) { selectedId.value = id || ''; emit('update:modelValue', selectedId.value); emit('select', selectedId.value, selected.value || null); }
function invalidate(clearSelection = true) {
  epoch++; listSequence++; assetSequence++; uploadSequence++; loading.value = false; assetsLoading.value = false; uploading.value = false;
  orders.value = []; assets.value = []; options.value = {}; error.value = ''; orderScopeNote.value = ''; ordersTruncated.value = false; assetsTruncated.value = false; viewVisible.value = false; clearFile();
  orderId.value = props.lockedOrderId; if (clearSelection) publishSelection(''); emit('availability', false);
}
function matchesScope(item, patient, order, encounter) { return String(item?.patient_id ?? item?.pid) === String(patient) && (!order || item.imaging_order_id === order) && (!encounter || item.encounter_ref === encounter); }
function pinnedOrder(id) { return { imaging_order_id: id, modality: 'unknown', body_part: '固定原申请，近期清单未返回详情', status: null }; }
async function refreshAssets(preferred = null) {
  if (!orderId.value || !props.patientId || inactive) { assets.value = []; return; }
  const currentEpoch = epoch, version = ++assetSequence, patient = props.patientId, order = orderId.value, encounter = props.encounterRef;
  assetsLoading.value = true; error.value = '';
  try {
    const response = await request({ url: 'ai/image-assets', method: 'get', params: { patient_id: patient, imaging_order_id: order, encounter_ref: encounter || undefined }, retry: 0 });
    if (currentEpoch !== epoch || version !== assetSequence) return;
    const items = response.data?.items || [];
    if (items.some(item => !matchesScope(item, patient, order, encounter))) throw new Error('返回的原图与当前患者、申请或就诊不一致');
    assets.value = items; assetsTruncated.value = !!response.data?.truncated;
    if (preferred && matchesScope(preferred, patient, order, encounter) && !assets.value.some(item => item.asset_id === preferred.asset_id)) assets.value.unshift(preferred);
    if (selectedId.value && !selected.value) {
      const id = selectedId.value, detail = await request({ url: `ai/image-assets/${encodeURIComponent(id)}`, method: 'get', retry: 0 });
      if (currentEpoch !== epoch || version !== assetSequence) return;
      if (detail.data?.asset_id !== id || !matchesScope(detail.data, patient, order, encounter)) throw new Error('指定原图不属于当前患者、申请或就诊');
      assets.value.unshift(detail.data);
    }
    if (selected.value) emit('select', selectedId.value, selected.value);
  } catch (failure) { if (currentEpoch === epoch && version === assetSequence) { assets.value = []; publishSelection(''); error.value = failure?.message || '原始影像目录未能读取，请核对当前诊疗权限'; } }
  finally { if (currentEpoch === epoch && version === assetSequence) assetsLoading.value = false; }
}
async function refresh() {
  if (!props.patientId || inactive) return;
  const currentEpoch = epoch, version = ++listSequence, patient = props.patientId, encounter = props.encounterRef;
  loading.value = true; error.value = '';
  try {
    const [list, limits] = await Promise.all([request({ url: 'ai/image-orders', method: 'get', params: { patient_id: patient, encounter_ref: encounter || undefined }, retry: 0 }), request({ url: 'ai/image-options', method: 'get', retry: 0 })]);
    if (currentEpoch !== epoch || version !== listSequence) return;
    const items = list.data?.items || [];
    if (items.some(item => String(item.patient_id ?? item.pid) !== String(patient))) throw new Error('返回的影像申请不属于当前患者');
    orders.value = items; ordersTruncated.value = !!list.data?.truncated; orderScopeNote.value = list.data?.scope_note || ''; options.value = limits.data || {};
    let preferred = null;
    if (selectedId.value && !orderId.value) {
      const id = selectedId.value, response = await request({ url: `ai/image-assets/${encodeURIComponent(id)}`, method: 'get', retry: 0 });
      if (currentEpoch !== epoch || version !== listSequence) return;
      if (response.data?.asset_id !== id || !matchesScope(response.data, patient, '', encounter)) throw new Error('指定原图不属于当前患者或就诊');
      preferred = response.data; orderId.value = preferred.imaging_order_id;
    }
    if (orderId.value && !orders.value.some(item => item.imaging_order_id === orderId.value)) orders.value.unshift(pinnedOrder(orderId.value));
    if (orderId.value) await refreshAssets(preferred);
  } catch (failure) { if (currentEpoch === epoch && version === listSequence) { orders.value = []; assets.value = []; publishSelection(''); error.value = failure?.message || '影像申请或登记范围未能读取，请核对当前权限'; } }
  finally { if (currentEpoch === epoch && version === listSequence) loading.value = false; }
}
function setOrder(value) {
  const id = value || ''; if (props.lockedOrderId && id !== props.lockedOrderId) return;
  epoch++; assetSequence++; uploadSequence++; assets.value = []; assetsLoading.value = false; uploading.value = false; viewVisible.value = false; clearFile(); publishSelection(''); orderId.value = id; emit('order-change', id);
  if (id) refreshAssets();
}
function selectAsset(value) { viewVisible.value = false; publishSelection(value || ''); }
function chooseFile(event) {
  const file = event.target.files?.[0] || null; confirmed.value = false; note.value = ''; recordedAt.value = null;
  if (file && file.size > (options.value.max_bytes || 0)) { clearFile(); ElMessage.error('原文件超过当前登记上限或登记限制尚未读取'); return; }
  imageFile.value = file;
}
async function upload() {
  if (!canUpload.value) return;
  const currentEpoch = epoch, version = ++uploadSequence, patient = props.patientId, order = orderId.value, encounter = props.encounterRef;
  const data = new FormData(); data.append('image', imageFile.value); data.append('patient_id', String(patient)); data.append('imaging_order_id', order); if (encounter) data.append('encounter_ref', encounter); data.append('authorization_confirmed', 'true'); data.append('authorization_note', note.value.trim());
  if (recordedAt.value) { const instant = new Date(recordedAt.value); if (!Number.isFinite(instant.getTime())) { error.value = '采集时间无效，请重新核对或留空'; return; } data.append('recorded_at', instant.toISOString()); }
  uploading.value = true; error.value = '';
  try {
    const response = await request({ url: 'ai/image-assets', method: 'post', data, headers: { 'Content-Type': undefined }, timeout: 180000, retry: 0 });
    if (currentEpoch !== epoch || version !== uploadSequence) { ElMessage.info('原图登记已完成，当前患者、申请或就诊已切换；请返回原范围核对目录'); return; }
    if (!matchesScope(response.data, patient, order, encounter)) throw new Error('登记结果与原患者、申请或就诊不一致');
    clearFile(); selectedId.value = response.data.asset_id; await refreshAssets(response.data);
    if (currentEpoch === epoch && version === uploadSequence && selected.value) { publishSelection(selectedId.value); ElMessage.success('原始影像已登记，尚未调用模型'); }
  } catch (failure) { if (currentEpoch === epoch && version === uploadSequence) error.value = failure?.message || '原始影像未能登记，请核对原文件与来源关联'; }
  finally { if (currentEpoch === epoch && version === uploadSequence) uploading.value = false; }
}
async function withdraw() {
  const item = selected.value, currentEpoch = epoch; if (!item?.can_withdraw || props.disabled) return;
  try {
    const { value } = await ElMessageBox.prompt('请填写撤回原因。撤回阻止后续使用，但不能收回已发送请求或已下载资料', '撤回原始影像', { inputValidator: text => text?.trim().length >= 5 || '请填写至少5字的原因', confirmButtonText: '撤回原图' });
    if (currentEpoch !== epoch) return;
    await request({ url: `ai/image-assets/${encodeURIComponent(item.asset_id)}/withdraw`, method: 'post', data: { expected_revision: item.revision, reason: value.trim() }, retry: 0 });
    if (currentEpoch !== epoch) return; viewVisible.value = false; publishSelection(''); await refreshAssets();
  } catch (failure) { if (failure !== 'cancel' && failure !== 'close' && currentEpoch === epoch) error.value = failure?.message || '原图未能撤回，请核对当前版本与权限'; }
}

watch([() => props.patientId, () => props.encounterRef, () => props.lockedOrderId, () => store.state.user.accessToken], () => { invalidate(!initial); initial = false; if (props.patientId && !inactive) refresh(); }, { immediate: true });
watch(() => props.modelValue, value => { const id = value || ''; if (id === selectedId.value) return; selectedId.value = id; viewVisible.value = false; if (id && !selected.value && !inactive) refresh(); });
watch([selected, loading, assetsLoading], () => emit('availability', !!selected.value && selected.value.status === 'ready' && selected.value.order_status !== 5 && Number.isInteger(selected.value.image_metadata?.valid_pixel_count) && selected.value.image_metadata.valid_pixel_count > 0 && !loading.value && !assetsLoading.value), { immediate: true });
onActivated(() => { if (inactive) { inactive = false; if (props.patientId) refresh(); } });
onDeactivated(() => { inactive = true; invalidate(); }); onBeforeUnmount(() => { inactive = true; invalidate(); });
defineExpose({ refresh, clear: invalidate });
</script>

<style scoped>
.ai-image-input { margin: 16px 0; padding: 12px; border: 1px solid var(--el-border-color); line-height: 1.7; }.ai-image-input > label { display: block; margin: 10px 0; }.file-row { display: block; margin: 12px 0; }.data-gap { color: #8b5d12; }
</style>
