<template>
  <section class="observation-governance" aria-label="AI住院观测窗管理">
    <p v-if="!allowed">仅超级管理员可管理全院观测窗。</p>
    <template v-else>
      <p>按原患者和住院核对冻结观测窗。原资料是离散观测、采样计划未知，不代表连续监护齐全。管理、查看或撤销均不调用模型，不启用功能或改变临床验证状态。</p>
      <el-form inline @submit.prevent="load">
        <el-form-item label="患者ID"><el-input v-model="filters.patient_id" aria-label="观测窗治理患者ID" inputmode="numeric" clearable placeholder="全部患者" /></el-form-item>
        <el-form-item label="原住院ID"><el-input v-model="filters.admission_id" aria-label="观测窗治理原住院ID" clearable placeholder="全部原住院" /></el-form-item>
        <el-form-item label="窗口状态"><el-select v-model="filters.status" aria-label="观测窗治理状态" clearable placeholder="全部状态"><el-option label="活动" value="active" /><el-option label="已撤销" value="revoked" /></el-select></el-form-item>
        <el-form-item><el-button native-type="submit" type="primary" :loading="loading">查询观测窗</el-button></el-form-item>
      </el-form>
      <p v-if="error" role="alert">{{ error }}</p>
      <p v-if="truncated">目录已截断，请缩小患者、住院或状态范围；未列出不表示不存在。</p>
      <el-table :data="items" v-loading="loading" empty-text="暂无匹配观测窗">
        <el-table-column prop="window_id" label="窗口ID" min-width="280" />
        <el-table-column label="原患者与住院" min-width="240"><template #default="{ row }">患者 #{{ row.patient_id }}<br />{{ row.admission_id }}</template></el-table-column>
        <el-table-column label="原时间范围" min-width="280"><template #default="{ row }">{{ row.start_at }}<br />至 {{ row.end_at }}<br />截至 {{ row.as_of }}</template></el-table-column>
        <el-table-column label="状态与版本" min-width="160"><template #default="{ row }">{{ statusLabel(row.status) }} · v{{ row.revision }}<br />{{ freshnessLabel(row.freshness) }}</template></el-table-column>
        <el-table-column label="核对" width="150"><template #default="{ row }"><el-button @click="inspect(row)">核对冻结观测窗</el-button></template></el-table-column>
      </el-table>
      <el-dialog v-model="detailOpen" title="冻结住院观测窗审计" width="min(1100px,96vw)" @closed="clearDetail">
        <div v-if="allowed" v-loading="inspecting">
          <p v-if="detailError" role="alert">{{ detailError }}</p>
          <template v-if="detail">
            <p class="hash">窗口 {{ detail.window_id }} · 患者 #{{ detail.patient_id }} · 原住院 {{ detail.admission_id }}<br />{{ detail.start_at }} 至 {{ detail.end_at }}<br />截至当时可知 {{ detail.as_of }} · 冻结 {{ detail.created_at }}<br />{{ statusLabel(detail.status) }} · 版本 {{ detail.revision }} · 内容摘要 {{ detail.content_hash }}</p>
            <p>当前一致性：{{ freshnessLabel(detail.freshness) }}。{{ detail.freshness?.message || '' }}</p>
            <p>下列数据保留创建时原版本。超级管理员能查看已变化或已撤销窗口的冻结审计，这不表示它仍可作为当前AI输入。</p>
            <template v-if="detail.snapshot">
              <h4>冻结原点测量</h4>
              <el-table :data="detail.snapshot.points || []" aria-label="窗口冻结点测量" empty-text="窗口未冻结点测量；无资料不表示正常">
                <el-table-column prop="observation_id" label="原观测ID" min-width="220" /><el-table-column prop="observed_at" label="实际观察时间" min-width="230" /><el-table-column prop="recorded_at" label="录入时间" min-width="230" />
                <el-table-column label="原数值与缺项" min-width="260"><template #default="{ row }"><div v-for="field in metricFields" :key="field.key">{{ field.label }}：{{ measurement(row.payload?.measurements?.[field.key] ?? row.measurements?.[field.key]) }}</div><div>吸氧：{{ oxygenLabels[row.payload?.supplemental_oxygen ?? row.supplemental_oxygen] || '未知' }}</div><div>意识：{{ consciousness(row.payload?.consciousness ?? row.consciousness) }}</div></template></el-table-column>
              </el-table>
              <h4>冻结原分时尿量</h4>
              <el-table :data="detail.snapshot.urine_intervals || []" aria-label="窗口冻结分时尿量" empty-text="窗口未冻结尿量区间；无资料不表示0mL">
                <el-table-column prop="interval_id" label="原区间ID" min-width="220" /><el-table-column label="原收集时间" min-width="230"><template #default="{ row }">{{ row.start_at }} 至 {{ row.end_at }}</template></el-table-column><el-table-column prop="recorded_at" label="录入时间" min-width="230" /><el-table-column label="原体积与收集范围" min-width="220"><template #default="{ row }">{{ urineSummary(row.payload || row) }}</template></el-table-column>
              </el-table>
              <el-collapse><el-collapse-item title="冻结质量说明与完整原资料"><pre class="frozen-json">{{ JSON.stringify(detail.snapshot, null, 2) }}</pre></el-collapse-item></el-collapse>
            </template>
            <p v-else>本次响应未提供冻结原资料，请核对审计来源。</p>
            <template v-if="detail.status === 'active' && detail.can_revoke === true"><el-input v-model="reason" aria-label="治理观测窗撤销依据" type="textarea" maxlength="1000" placeholder="填写明确撤销依据；撤销不可恢复" /><el-button type="danger" :disabled="!reason.trim()" :loading="revoking" @click="revoke">撤销此观测窗</el-button></template>
            <p v-if="detail.status === 'revoked'">撤销 {{ detail.revoked_at || '未记录' }}；原因 {{ detail.revoke_reason || '未记录' }}。</p>
          </template>
        </div>
        <template #footer><el-button @click="detailOpen = false">关闭</el-button></template>
      </el-dialog>
    </template>
  </section>
</template>

<script setup>
import { computed, onActivated, onBeforeUnmount, onDeactivated, reactive, ref, watch } from "vue";
import { useStore } from "vuex";
import { ElMessage } from "element-plus";
import { getAdminObservationWindow, getAdminObservationWindows, observationAbsentReasons as absentReasons, observationMetricFields as metricFields, observationOxygenLabels as oxygenLabels, observationWindowMatches, revokeObservationWindow } from "@/api/inpatientObservations";
const store = useStore();
const roles = computed(() => store.getters["user/permissions"] || []);
const allowed = computed(() => !!store.state.user.accessToken && roles.value.includes("super_admin"));
const filters = reactive({ patient_id: "", admission_id: "", status: "" }), items = ref([]), loading = ref(false), error = ref(""), truncated = ref(false);
const detailOpen = ref(false), detail = ref(null), inspecting = ref(false), detailError = ref(""), reason = ref(""), revoking = ref(false);
let scopeEpoch = 0, listSequence = 0, detailSequence = 0, inactive = false;
const sessionKey = () => JSON.stringify([store.state.user.accessToken, roles.value]);
const filterKey = () => JSON.stringify(filters);
const capture = () => ({ epoch: scopeEpoch, session: sessionKey() });
const current = ticket => ticket.epoch === scopeEpoch && ticket.session === sessionKey() && allowed.value && !inactive;
const statusLabel = status => ({ active: "活动", revoked: "已撤销" }[status] || "未知");
const freshnessLabel = freshness => ({ not_checked: "目录尚未核对一致性", current: "本次原资料一致", stale: "原资料已变化", revoked: "窗口已撤销" }[freshness?.state] || "一致性未知");
const measurement = value => value?.value !== null && value?.value !== undefined ? `${value.value} ${value.unit}` : value ? absentReasons[value.absent_reason] || "未知" : "未记录";
const consciousness = value => value ? `${value.system} · ${value.code}` : "未观察";
const urineSummary = value => `${value.volume_ml !== null && value.volume_ml !== undefined ? `${value.volume_ml} mL` : `未知（${absentReasons[value.absent_reason] || '未记录原因'}）`}；完整性 ${({ complete: '完整', partial: '部分', unknown: '未知' })[value.collection_completeness] || '未知'}；患者总量 ${value.patient_total === true ? '是' : value.patient_total === false ? '否' : '未知'}`;
function clearDetail() { detailSequence++; detail.value = null; detailError.value = ""; inspecting.value = false; reason.value = ""; revoking.value = false; }
function clearAll() { scopeEpoch++; listSequence++; clearDetail(); detailOpen.value = false; items.value = []; loading.value = false; error.value = ""; truncated.value = false; }
async function load() {
  if (!allowed.value || inactive) return;
  const ticket = capture(), sequence = ++listSequence, key = filterKey(); let params;
  try { const patient = filters.patient_id.trim(); if (patient && (!/^[1-9]\d*$/.test(patient) || !Number.isSafeInteger(Number(patient)))) throw new Error("患者ID须为正整数"); params = { ...(patient ? { patient_id: Number(patient) } : {}), ...(filters.admission_id.trim() ? { admission_id: filters.admission_id.trim() } : {}), ...(filters.status ? { status: filters.status } : {}) }; } catch (failure) { error.value = failure.message; return; }
  loading.value = true; error.value = ""; items.value = [];
  try { const response = await getAdminObservationWindows(params); if (!current(ticket) || sequence !== listSequence || key !== filterKey()) return; if (!Array.isArray(response.data) || response.data.some(row => !row || typeof row.window_id !== "string" || (params.patient_id && row.patient_id !== params.patient_id) || (params.admission_id && row.admission_id !== params.admission_id) || (params.status && row.status !== params.status))) throw new Error("窗口目录与指定患者、住院或状态不一致"); items.value = response.data; truncated.value = response.truncated === true; } catch (failure) { if (current(ticket) && sequence === listSequence && key === filterKey()) { items.value = []; error.value = failure?.message || "观测窗目录未能读取"; } } finally { if (current(ticket) && sequence === listSequence && key === filterKey()) loading.value = false; }
}
async function inspect(row) { if (!allowed.value || inactive) return; clearDetail(); const ticket = capture(), sequence = detailSequence; detailOpen.value = true; inspecting.value = true; try { const response = await getAdminObservationWindow(row.window_id); if (!current(ticket) || sequence !== detailSequence || !detailOpen.value) return; if (response.data?.window_id !== row.window_id || !observationWindowMatches(response.data, row.patient_id, row.admission_id)) throw new Error("冻结观测窗回执与原窗口、患者或住院不一致"); detail.value = response.data; } catch (failure) { if (current(ticket) && sequence === detailSequence && detailOpen.value) detailError.value = failure?.message || "冻结原窗口未能读取"; } finally { if (current(ticket) && sequence === detailSequence) inspecting.value = false; } }
async function revoke() { if (!allowed.value || inactive || !detail.value || detail.value.status !== "active" || detail.value.can_revoke !== true || !reason.value.trim() || revoking.value) return; const ticket = capture(), sequence = detailSequence, original = detail.value; revoking.value = true; try { const response = await revokeObservationWindow(original.window_id, { expected_revision: original.revision, reason: reason.value.trim() }); if (!current(ticket) || sequence !== detailSequence || !detailOpen.value) return; if (response.data?.window_id !== original.window_id || !observationWindowMatches(response.data, original.patient_id, original.admission_id)) throw new Error("撤销回执与原窗口不一致"); detail.value = response.data; reason.value = ""; await load(); } catch (failure) { if (current(ticket) && sequence === detailSequence) ElMessage.error(failure?.message || "撤销失败，请刷新核对版本与权限"); } finally { if (current(ticket) && sequence === detailSequence) revoking.value = false; } }
watch(filterKey, () => { listSequence++; items.value = []; loading.value = false; error.value = ""; truncated.value = false; detailOpen.value = false; clearDetail(); }, { flush: "sync" });
watch(sessionKey, () => { clearAll(); load(); }, { immediate: true, flush: "sync" });
onDeactivated(() => { inactive = true; clearAll(); });
onActivated(() => { if (inactive) { inactive = false; clearAll(); load(); } });
onBeforeUnmount(() => { inactive = true; clearAll(); });
</script>

<style scoped>
.observation-governance p { line-height: 1.7; }.hash { overflow-wrap: anywhere; }.frozen-json { white-space: pre-wrap; overflow-wrap: anywhere; max-height: 480px; overflow: auto; }.el-button { margin-top: 8px; }
</style>
