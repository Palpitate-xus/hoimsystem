<template>
  <section aria-label="原住院受控检验来源" class="lab-source-panel">
    <p v-if="!canRead">请选择明确原住院并以有权限的工作人员身份读取来源。</p>
    <template v-else>
      <p>患者 #{{ patientId }} · 原住院 {{ admissionId }}。这里登记已审核结构化检验的受控副本，不修改原申请、报告或旧时钟，不自动纳入未确认的住院。</p>
      <p>登记后可用时点由服务器记录，不能倒填原报告首次可用时间；已审核报告、项目映射与临床模型验证是不同事项。</p>
      <el-collapse v-if="canCreate"><el-collapse-item title="登记已审核检验原来源">
        <p>候选只表示同一患者的已审核原观察项，尚未确认属于本住院。所有原值只读，不从正文解析或补数值、单位。</p>
        <el-button :loading="candidateLoading" :disabled="creating" @click="loadCandidates">读取已审核检验候选</el-button>
        <p v-if="candidateTruncated">候选目录已截断，未列出不表示不存在；不能据此断言历史齐全。</p>
        <el-form label-position="top" :disabled="creating" @submit.prevent>
          <el-form-item label="同患者原观察项"><el-select v-model="candidateId" aria-label="待核实原检验观察项" placeholder="明确选择，不自动选最近结果" :disabled="candidateLoading" filterable clearable><el-option v-for="row in candidates" :key="row.observation_id" :label="candidateLabel(row)" :value="row.observation_id" :disabled="row.registration?.status === 'already_registered'" /></el-select></el-form-item>
          <template v-if="candidate">
            <p class="hash">原观察项 {{ candidate.observation_id }} · 原始内容摘要 {{ candidate.raw_original_hash }}</p>
            <p>原数据库结果 {{ candidateObservation.value_num !== null && candidateObservation.value_num !== undefined ? candidateObservation.value_num : candidateObservation.value_text ?? '未提供' }} {{ candidateObservation.unit ?? '' }}；旧采样钟点 {{ candidateObservation.collected_at ?? '未记录' }}（时区未知，不自动转换）。</p>
            <p>原编码 {{ candidateObservation.code_system }}:{{ candidateObservation.code }}；方法 {{ candidateObservation.method || '未记录' }}；标本 {{ candidateObservation.specimen_type || '未记录' }}。</p>
            <el-form-item label="已审核项目映射"><el-select v-model="mappingId" aria-label="受控检验项目映射" placeholder="明确选择已审核且精确匹配的映射" clearable><el-option v-for="item in matchingMappings" :key="item.mapping_id" :value="item.mapping_id" :label="`${item.label || item.analyte_label || item.analyte_key} · ${item.source_namespace} · v${item.revision}`" /></el-select></el-form-item>
            <p v-if="!matchingMappings.length">没有已审核且精确匹配的映射，不能通过改写原项目或单位继续；请由超级管理员核对项目身份。</p>
          </template>
          <template v-if="mapping">
            <p>映射命名空间 {{ mapping.source_namespace }}；项目身份 {{ mapping.label || mapping.analyte_label || mapping.analyte_key }}。同编码文字不证明出自同一来源系统。</p>
            <el-form-item label="人工核实的采样UTC"><el-input v-model="form.collected_at_utc" aria-label="人工核实采样UTC" placeholder="明确填写含秒和时区的ISO；不从旧clock自动填入" /></el-form-item>
            <el-checkbox v-model="form.collection_time_confirmed">我已核实此观察项的真实采样UTC</el-checkbox>
            <el-input v-model="form.collection_time_basis_note" aria-label="采样UTC核实依据" type="textarea" maxlength="2000" placeholder="至少20字，说明原时钟语义及UTC核实依据" />
            <el-checkbox v-model="form.admission_binding_confirmed">我已核实此观察项属于所选患者和原住院</el-checkbox>
            <el-input v-model="form.admission_binding_note" aria-label="检验原住院关联依据" type="textarea" maxlength="2000" placeholder="至少20字，填写明确住院关联核对依据，不按时间推定" />
            <el-checkbox v-model="form.source_namespace_confirmed">我已核实原观察项属于所选映射的来源命名空间</el-checkbox>
            <el-input v-model="form.source_namespace_basis_note" aria-label="检验来源命名空间核实依据" type="textarea" maxlength="2000" placeholder="至少20字，说明原来源系统与映射命名空间一致的依据" />
          </template>
          <el-button type="primary" :loading="creating" :disabled="!canRegister" @click="register">登记本住院检验来源</el-button>
        </el-form>
      </el-collapse-item></el-collapse>
      <p v-else>当前角色只读已登记检验来源；不能登记、改写或确认原关联。</p>
      <p v-if="error" role="alert">{{ error }}</p>
      <el-button :loading="loading" @click="loadSources">刷新本住院检验来源</el-button>
      <p>目录共 {{ total ?? '未知' }} 项；目录未逐项核对一致性，选择原行后重新核对。</p>
      <el-table :data="sources" v-loading="loading" empty-text="本页未列检验来源；无资料不表示正常或阴性">
        <el-table-column prop="lab_source_id" label="原来源ID" min-width="230" /><el-table-column prop="collected_at_utc" label="人工核实采样UTC" min-width="230" /><el-table-column prop="available_at" label="本次纳入可用UTC" min-width="230" /><el-table-column label="状态与一致性" min-width="150"><template #default="{ row }">{{ row.status === 'active' ? '活动' : '已撤销' }} · v{{ row.revision }}<br />目录尚未逐项核对</template></el-table-column><el-table-column label="核对" width="130"><template #default="{ row }"><el-button @click="inspect(row)">核对原检验来源</el-button></template></el-table-column>
      </el-table>
      <el-pagination v-if="total > pageSize" v-model:current-page="page" :page-size="pageSize" :total="total" layout="prev,pager,next" @current-change="loadSources" />
    </template>
    <el-dialog v-model="detailOpen" title="受控检验原来源核对" width="min(1050px,96vw)" @closed="clearDetail">
      <div v-if="canRead" v-loading="inspecting"><p v-if="detailError" role="alert">{{ detailError }}</p><template v-if="detail"><ai-laboratory-findings :source="detail" :expected-patient-id="patientId" :expected-admission-id="admissionId" /><template v-if="canCreate && detail.can_revoke === true && detail.status === 'active'"><el-input v-model="reason" aria-label="检验来源撤销依据" maxlength="1000" placeholder="明确填写撤销原因，不恢复或原地修改" /><el-button type="danger" :disabled="!reason.trim()" :loading="revoking" @click="revoke">撤销此检验来源</el-button></template></template></div>
      <template #footer><el-button @click="detailOpen = false">关闭</el-button></template>
    </el-dialog>
  </section>
</template>
<script setup>
import { computed, onActivated, onBeforeUnmount, onDeactivated, ref, watch } from "vue";
import { useStore } from "vuex";
import { ElMessage } from "element-plus";
import AiLaboratoryFindings from "@/components/AILaboratoryFindings/index.vue";
import { createInpatientLabSource, getInpatientLabCandidates, getInpatientLabSource, getInpatientLabSources, labSourceMatches, revokeInpatientLabSource } from "@/api/inpatientLaboratory";
import { observationTime } from "@/api/inpatientObservations";
const props = defineProps({ patientId: { type: Number, required: true }, admissionId: { type: String, required: true }, active: { type: Boolean, default: true } });
const emit = defineEmits(["source-created", "source-revoked"]);
const store = useStore(), roles = computed(() => store.getters["user/permissions"] || []);
const canRead = computed(() => props.active && Number.isSafeInteger(props.patientId) && props.patientId > 0 && !!props.admissionId && !!store.state.user.accessToken && roles.value.some(role => ["doctor", "director", "admin", "super_admin", "nurse"].includes(role)));
const canCreate = computed(() => canRead.value && roles.value.some(role => ["doctor", "director", "admin", "super_admin"].includes(role)));
const emptyForm = () => ({ collected_at_utc: "", collection_time_confirmed: false, collection_time_basis_note: "", admission_binding_confirmed: false, admission_binding_note: "", source_namespace_confirmed: false, source_namespace_basis_note: "" });
const form = ref(emptyForm()), candidateId = ref(""), mappingId = ref(""), candidates = ref([]), candidateTruncated = ref(false), candidateLoading = ref(false), creating = ref(false), sources = ref([]), total = ref(null), page = ref(1), pageSize = 50, loading = ref(false), error = ref("");
const detail = ref(null), detailOpen = ref(false), detailError = ref(""), inspecting = ref(false), reason = ref(""), revoking = ref(false);
const candidate = computed(() => candidates.value.find(row => row.observation_id === candidateId.value));
const candidateObservation = computed(() => candidate.value?.original?.observation || {});
const matchingMappings = computed(() => {
  const item = candidateObservation.value;
  const signature = { code_system: item.code_system, code: item.code, unit: item.unit, method: item.method, specimen_type: item.specimen_type, value_kind: item.value_num !== null && item.value_num !== undefined ? "numeric" : "qualitative" };
  return (candidate.value?.matching_mappings || []).filter(mapping => mapping.status === "published" && mapping.revision === 2 && /^[a-f0-9]{64}$/.test(mapping.content_hash || "") && Object.entries(signature).every(([key, value]) => mapping.signature?.[key] === value));
});
const mapping = computed(() => matchingMappings.value.find(row => row.mapping_id === mappingId.value));
const canRegister = computed(() => canCreate.value && !creating.value && !!candidate.value && candidate.value.registration?.status !== "already_registered" && !!mapping.value && form.value.collection_time_confirmed && form.value.admission_binding_confirmed && form.value.source_namespace_confirmed && ["collection_time_basis_note", "admission_binding_note", "source_namespace_basis_note"].every(key => form.value[key].trim().length >= 20) && !!form.value.collected_at_utc.trim());
let epoch = 0, listSequence = 0, candidateSequence = 0, detailSequence = 0, inactive = false;
const key = () => JSON.stringify([props.patientId, props.admissionId, props.active, store.state.user.accessToken, roles.value]);
const capture = () => ({ epoch, key: key(), patient_id: props.patientId, admission_id: props.admissionId });
const current = ticket => ticket.epoch === epoch && ticket.key === key() && canRead.value && !inactive;
const scope = ticket => ({ patient_id: ticket.patient_id, admission_id: ticket.admission_id });
const candidateLabel = row => { const item = row.original?.observation || {}; return `${item.display || row.observation_id} · ${item.value_num ?? item.value_text ?? '未提供'} ${item.unit ?? ''} · ${item.collected_at || '原clock未记录'}`; };
function clearChoices() { candidateId.value = ""; mappingId.value = ""; form.value = emptyForm(); }
function clearDetail() { detailSequence++; detail.value = null; detailError.value = ""; inspecting.value = false; reason.value = ""; revoking.value = false; }
function clearAll() { epoch++; listSequence++; candidateSequence++; clearChoices(); clearDetail(); detailOpen.value = false; candidates.value = []; sources.value = []; total.value = null; page.value = 1; candidateLoading.value = false; loading.value = false; creating.value = false; error.value = ""; candidateTruncated.value = false; }
async function loadCandidates() { if (!canCreate.value || inactive) return; clearChoices(); candidates.value = []; const ticket = capture(), sequence = ++candidateSequence; candidateLoading.value = true; error.value = ""; try { const response = await getInpatientLabCandidates(scope(ticket)); if (!current(ticket) || !canCreate.value || sequence !== candidateSequence) return; const items = response.data?.items; if (!Array.isArray(items) || items.some(row => row.original?.order?.patient_id !== ticket.patient_id || typeof row.observation_id !== "string" || row.original?.observation?.observation_id !== row.observation_id || !/^[a-f0-9]{64}$/.test(row.raw_original_hash || ""))) throw new Error("原检验候选与患者或来源摘要不一致"); candidates.value = items; candidateTruncated.value = response.data.truncated === true; } catch (failure) { if (current(ticket) && sequence === candidateSequence) error.value = failure?.message || "候选未能读取，请核对当前照护权限"; } finally { if (current(ticket) && sequence === candidateSequence) candidateLoading.value = false; } }
async function loadSources() { if (!canRead.value || inactive) return; const ticket = capture(), sequence = ++listSequence; loading.value = true; error.value = ""; sources.value = []; try { const response = await getInpatientLabSources({ ...scope(ticket), page: page.value, page_size: pageSize }); if (!current(ticket) || sequence !== listSequence) return; const items = response.data?.items; if (!Array.isArray(items) || items.some(row => !labSourceMatches(row, ticket.patient_id, ticket.admission_id))) throw new Error("检验来源目录与当前患者或原住院不一致"); sources.value = items; total.value = response.data.total; } catch (failure) { if (current(ticket) && sequence === listSequence) { sources.value = []; error.value = failure?.message || "本住院来源未能读取"; } } finally { if (current(ticket) && sequence === listSequence) loading.value = false; } }
async function register() {
  if (!canRegister.value || inactive) return;
  let time; try { time = observationTime(form.value.collected_at_utc); if (time.microseconds > BigInt(Date.now()) * 1000n) throw new Error("核实采样时刻不能在未来"); } catch (failure) { ElMessage.warning(failure.message); return; }
  const ticket = capture(), selected = candidate.value, selectedMapping = mapping.value;
  const payload = { ...scope(ticket), observation_id: selected.observation_id, mapping_id: selectedMapping.mapping_id, expected_source_hash: selected.raw_original_hash, expected_mapping_hash: selectedMapping.content_hash, ...form.value, collected_at_utc: time.text };
  creating.value = true;
  try { const response = await createInpatientLabSource(payload); if (!current(ticket) || !canCreate.value) return; if (!labSourceMatches(response.data, ticket.patient_id, ticket.admission_id) || response.data.observation_id !== selected.observation_id || response.data.mapping_id !== selectedMapping.mapping_id || response.data.raw_original_hash !== selected.raw_original_hash || response.data.mapping_content_hash !== selectedMapping.content_hash || response.data.status !== "active" || response.data.revision !== 1) throw new Error("登记回执与原住院、观察项或映射不一致"); selected.registration = { status: "already_registered", active_lab_source_id: response.data.lab_source_id }; clearChoices(); emit("source-created", response.data); ElMessage.success("已登记原来源，未调用模型或改写旧报告"); page.value = 1; await loadSources(); } catch (failure) { if (current(ticket)) error.value = failure?.response?.data?.detail || failure?.message || "来源登记失败，请重新核对原资料和映射"; } finally { if (current(ticket)) creating.value = false; }
}
async function inspect(row) { if (!canRead.value || inactive) return; clearDetail(); const ticket = capture(), sequence = detailSequence; detailOpen.value = true; inspecting.value = true; try { const response = await getInpatientLabSource(row.lab_source_id, scope(ticket)); if (!current(ticket) || sequence !== detailSequence || !detailOpen.value) return; if (!labSourceMatches(response.data, ticket.patient_id, ticket.admission_id) || response.data.lab_source_id !== row.lab_source_id) throw new Error("原检验来源回执与指定范围不一致"); detail.value = response.data; } catch (failure) { if (current(ticket) && sequence === detailSequence && detailOpen.value) detailError.value = failure?.message || "原来源未能核对"; } finally { if (current(ticket) && sequence === detailSequence) inspecting.value = false; } }
async function revoke() { if (!canCreate.value || inactive || detail.value?.can_revoke !== true || detail.value.status !== "active" || !reason.value.trim() || revoking.value) return; const ticket = capture(), sequence = detailSequence, original = detail.value; revoking.value = true; try { const response = await revokeInpatientLabSource(original.lab_source_id, { ...scope(ticket), expected_revision: original.revision, reason: reason.value.trim() }); if (!current(ticket) || sequence !== detailSequence || !detailOpen.value) return; if (!labSourceMatches(response.data, ticket.patient_id, ticket.admission_id) || response.data.lab_source_id !== original.lab_source_id || response.data.status !== "revoked" || response.data.revision !== original.revision + 1 || response.data.content_hash !== original.content_hash) throw new Error("撤销回执与原来源不一致"); detail.value = response.data; reason.value = ""; emit("source-revoked", response.data); await loadSources(); } catch (failure) { if (current(ticket) && sequence === detailSequence) detailError.value = failure?.message || "撤销失败，请重新核对版本与权限"; } finally { if (current(ticket) && sequence === detailSequence) revoking.value = false; } }
watch(candidateId, () => { mappingId.value = ""; form.value = emptyForm(); }, { flush: "sync" });
watch(mappingId, () => { form.value = emptyForm(); }, { flush: "sync" });
watch(key, () => { clearAll(); loadSources(); }, { immediate: true, flush: "sync" });
onDeactivated(() => { inactive = true; clearAll(); }); onActivated(() => { if (inactive) { inactive = false; clearAll(); loadSources(); } }); onBeforeUnmount(() => { inactive = true; clearAll(); });
</script>
<style scoped>p { line-height: 1.7; }.hash { overflow-wrap: anywhere; }.el-select { width: 100%; }.el-checkbox { display: flex; margin: 12px 0; white-space: normal; }.el-button { margin-top: 10px; }</style>
