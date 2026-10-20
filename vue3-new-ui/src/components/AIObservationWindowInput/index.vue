<template>
  <div aria-label="风险观测窗选择">
    <el-alert type="info" :closable="false" title="先选择原住院的冻结观测窗。离散记录不代表连续监护完整，也不代表模型已验证。" />
    <p v-if="!admissionId">请选择原住院记录；门诊体征和患者级检验不会按日期归入住院。</p>
    <template v-else-if="canUse">
      <el-form-item label="原住院观测窗">
        <el-select v-model="selectedId" clearable :disabled="loading || disabled" placeholder="明确选择并核对来源" aria-label="原住院观测窗" style="width: 100%">
          <el-option v-for="item in options" :key="item.window_id" :value="item.window_id" :label="`${item.start_at} 至 ${item.end_at} · 可用截止 ${item.as_of} · ${item.window_id.slice(0, 8)}`" />
          <el-option v-if="selectedId && !options.some(item => item.window_id === selectedId)" :value="selectedId" :label="`指定窗口 ${selectedId}`" />
        </el-select>
      </el-form-item>
      <el-button :loading="loading" :disabled="disabled" @click="reload">刷新可选观测窗</el-button>
      <el-collapse v-model="sourceSections" class="spaced">
        <el-collapse-item title="核实原住院来源并建立观测窗" name="sources">
          <el-tabs v-if="sourceSections.includes('sources')" v-model="sourceTab">
            <el-tab-pane label="检验来源登记" name="laboratory" lazy><inpatient-lab-source-panel v-if="sourceTab === 'laboratory'" :patient-id="patientId" :admission-id="admissionId" :active="!disabled" @source-created="sourceChanged" @source-revoked="sourceChanged" /></el-tab-pane>
            <el-tab-pane label="点测、尿量与新建窗口" name="observations" lazy><inpatient-observation-panel v-if="sourceTab === 'observations'" :patient-id="patientId" :admission-id="admissionId" :active="!disabled" @window-created="windowCreated" /></el-tab-pane>
          </el-tabs>
        </el-collapse-item>
      </el-collapse>
      <p v-if="sourceNotice">{{ sourceNotice }}</p>
      <p>可在护理工作台的“结构化观测”中登记原测量、分时尿量并冻结观测窗。观测时间和系统录入截止分别保存，晚录资料不进入较早截止时点。</p>
      <p v-if="truncated">这里只列出有限窗口目录；从原窗口入口打开时仍按明确标识核对，不把目录条数当作完整测量记录。</p>
      <p v-if="checking">正在重新核对原住院、观测资料和窗口状态。</p>
      <el-alert v-if="error" type="warning" :closable="false" :title="error" />
      <p v-if="current">已核对 {{ current.window_id }} · v{{ current.revision }}；测量范围 {{ current.start_at }} 至 {{ current.end_at }}，系统可用截止 {{ current.as_of }}。生成时仍会重核原资料。</p>
    </template>
    <el-alert v-else type="warning" :closable="false" title="当前角色不能读取住院观测来源。" />
  </div>
</template>

<script setup>
import { computed, defineAsyncComponent, onActivated, onBeforeUnmount, onDeactivated, ref, watch } from "vue";
import { useStore } from "vuex";
import { getObservationWindow, getObservationWindows, observationWindowMatches } from "@/api/inpatientObservations";

const InpatientLabSourcePanel = defineAsyncComponent(() => import("@/components/InpatientLabSourcePanel/index.vue"));
const InpatientObservationPanel = defineAsyncComponent(() => import("@/components/InpatientObservationPanel/index.vue"));

const props = defineProps({ patientId: { type: Number, required: true }, admissionId: { type: String, default: "" }, initialWindowId: { type: String, default: "" }, disabled: { type: Boolean, default: false } });
const emit = defineEmits(["selection", "availability"]);
const store = useStore();
const roles = computed(() => store.getters["user/permissions"] || []);
const canUse = computed(() => roles.value.some(role => ["nurse", "doctor", "director", "admin", "super_admin"].includes(role)));
const options = ref([]), selectedId = ref(""), current = ref(null), loading = ref(false), checking = ref(false), truncated = ref(false), error = ref("");
const sourceSections = ref([]), sourceTab = ref("laboratory"), sourceNotice = ref("");
let listVersion = 0, detailVersion = 0, alive = true, paused = false, allowInitialSelection = true;
const scope = () => JSON.stringify([props.patientId, props.admissionId, props.initialWindowId, store.state.user.accessToken, roles.value]);
const valid = (stamp, identity, detail = false) => alive && !paused && stamp === (detail ? detailVersion : listVersion) && identity === scope() && canUse.value;
function clearSelection() { current.value = null; emit("selection", null); emit("availability", false); }
function sourceChanged() { listVersion++; detailVersion++; allowInitialSelection = false; selectedId.value = ""; options.value = []; loading.value = false; checking.value = false; truncated.value = false; clearSelection(); sourceNotice.value = "检验来源已变化；旧观测窗不会补入新资料，请重新建立窗口并明确选择核对。"; }
function windowCreated() { allowInitialSelection = false; reload(); sourceNotice.value = "新观测窗已建立，请从目录明确选择并核对；此操作未调用模型。"; }
async function reload() {
  const stamp = ++listVersion, identity = scope();
  detailVersion++;
  clearSelection(); options.value = []; selectedId.value = ""; error.value = ""; checking.value = false; truncated.value = false; loading.value = false;
  if (!alive || paused || !canUse.value || !props.patientId || !props.admissionId) return;
  loading.value = true;
  try {
    const response = await getObservationWindows({ patient_id: props.patientId, admission_id: props.admissionId });
    if (!valid(stamp, identity)) return;
    options.value = (response.data || []).filter(item => item.status === "active" && item.patient_id === props.patientId && item.admission_id === props.admissionId);
    truncated.value = !!response.truncated;
    if (allowInitialSelection && props.initialWindowId) { allowInitialSelection = false; selectedId.value = props.initialWindowId; }
  } catch { if (valid(stamp, identity)) error.value = "当前无法读取本次住院窗口，请核对诊疗关系或限时授权后重试。"; }
  finally { if (valid(stamp, identity)) loading.value = false; }
}
watch(selectedId, async id => {
  const stamp = ++detailVersion, identity = scope();
  clearSelection(); checking.value = false; error.value = "";
  if (!id || !alive || paused || !canUse.value || !props.patientId || !props.admissionId) return;
  checking.value = true;
  try {
    const response = await getObservationWindow(id, { patient_id: props.patientId, admission_id: props.admissionId });
    if (!valid(stamp, identity, true) || selectedId.value !== id) return;
    const data = response.data;
    const frozen = data?.snapshot;
    if (data?.window_id !== id || data.patient_id !== props.patientId || data.admission_id !== props.admissionId || data.status !== "active" || data.revision !== 1 || data.freshness?.state !== "current" || !["inpatient_window_v1", "inpatient_window_v2"].includes(frozen?.schema_version) || data.schema_version !== frozen.schema_version || !observationWindowMatches(data, props.patientId, props.admissionId) || frozen.window_id !== id || frozen.patient_id !== props.patientId || frozen.admission_id !== props.admissionId || frozen.content_hash !== data.content_hash || frozen.source_id !== data.source_id || data.source_id !== `observation_window:${id}:${(data.content_hash || "").slice(0, 12)}` || !/^[a-f0-9]{64}$/.test(data.content_hash || "") || ["start_at", "end_at", "as_of"].some(key => frozen[key] !== data[key])) {
      error.value = "窗口已撤销、原资料已变化或范围不符，请重新建立并核对来源。"; return;
    }
    current.value = data;
    sourceNotice.value = "";
    emit("selection", { observation_window_id: data.window_id, content_hash: data.content_hash }); emit("availability", true);
  } catch { if (valid(stamp, identity, true)) error.value = "无法核对该窗口的当前来源，请重新选择；不会沿用旧资料。"; }
  finally { if (valid(stamp, identity, true)) checking.value = false; }
});
watch([() => props.patientId, () => props.admissionId, () => props.initialWindowId, () => store.state.user.accessToken, () => JSON.stringify(roles.value)], (values, previous) => {
  allowInitialSelection = !previous?.length || values.slice(0, 3).some((value, index) => value !== previous[index]);
  reload();
}, { immediate: true });
watch([() => props.patientId, () => props.admissionId, () => store.state.user.accessToken, () => JSON.stringify(roles.value)], () => { sourceSections.value = []; sourceNotice.value = ""; sourceTab.value = "laboratory"; });
onDeactivated(() => { paused = true; allowInitialSelection = false; listVersion++; detailVersion++; selectedId.value = ""; options.value = []; loading.value = false; checking.value = false; clearSelection(); });
onActivated(() => { if (paused) { paused = false; reload(); } });
onBeforeUnmount(() => { alive = false; listVersion++; detailVersion++; clearSelection(); });
</script>
