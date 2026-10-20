<template>
  <div class="ai-assistant" v-loading="loading">
    <el-form label-position="top">
      <el-form-item label="AI 功能">
        <el-select v-model="featureKey" filterable placeholder="选择本次需要的辅助功能" style="width: 100%">
          <el-option v-for="item in features" :key="item.key" :label="item.number + ' · ' + item.name" :value="item.key" />
        </el-select>
      </el-form-item>
      <template v-if="selected">
        <div class="feature-description"><strong>需要的资料：</strong>{{ selected.inputs.join('、') }}<br /><strong>预期产出：</strong>{{ selected.deliverables.join('；') }}</div>
        <el-alert v-if="!selected.enabled" type="info" :closable="false" title="此功能尚未面向业务启用，由超级管理员配置模型和验证状态。" class="spaced" />
        <el-form-item v-if="selected.scope === 'patient'" label="患者">
          <el-select v-model="patientId" :disabled="!!props.patientId" filterable remote :remote-method="searchPatients" placeholder="搜索有访问权限的患者" style="width: 100%">
            <el-option v-for="item in patients" :key="item.patient_id" :label="item.label" :value="item.patient_id" />
          </el-select>
        </el-form-item>
        <el-form-item v-if="selected.scope === 'patient' && patientId" label="本次就诊">
          <el-select v-model="encounterRef" clearable :disabled="!!props.encounterRef" placeholder="选择门诊或住院记录；治疗路径推荐需要本次就诊" style="width: 100%">
            <el-option v-for="item in encounters" :key="item.encounter_ref" :label="item.label" :value="item.encounter_ref" />
          </el-select>
        </el-form-item>
        <el-form-item v-if="needsPrescription && patientId" label="待核查处方">
          <el-select v-model="prescriptionId" clearable placeholder="选择实际处方" style="width: 100%"><el-option v-for="item in prescriptions" :key="item.prescription_id" :label="item.label" :value="item.prescription_id" /></el-select>
        </el-form-item>
        <el-form-item label="补充资料或问题"><el-input v-model="question" type="textarea" :rows="5" maxlength="12000" show-word-limit :placeholder="'请提供与' + selected.name + '相关的信息，明确哪些是已确认事实'" /></el-form-item>
        <el-collapse v-if="canPreview" class="spaced">
          <el-collapse-item title="联调与预览选项">
            <el-checkbox v-model="preview">超级管理员预览（结果仅供评估）</el-checkbox>
            <el-input v-model="extraInput" type="textarea" :rows="4" placeholder="可选：专用适配器的结构化输入 JSON，由服务契约规定" class="spaced" />
          </el-collapse-item>
        </el-collapse>
        <el-alert v-if="selected.engine !== 'llm'" type="info" :closable="false" title="此能力通过专用模型处理，需要对应原始资料和已登记的适配服务。" class="spaced" />
        <div class="actions">
          <el-button v-if="selected.scope === 'patient'" :disabled="!patientId" @click="inspectContext">查看本次资料</el-button>
          <el-button type="primary" :loading="submitting" :disabled="busy || (!selected.enabled && !preview) || (selected.scope === 'patient' && !patientId)" @click="submit">生成辅助建议</el-button>
          <el-button v-if="busy" @click="cancel">取消接收结果</el-button>
        </div>
      </template>
      <el-empty v-else-if="!loading" description="当前角色暂无可用 AI 能力" />
    </el-form>

    <el-card v-if="run" shadow="never" class="spaced" aria-label="AI任务结果">
      <template #header><div class="result-header"><strong>{{ run.feature_name }}</strong><el-tag>{{ statuses[run.status] || run.status }}</el-tag><el-tag v-if="run.patient_id" type="info">患者 #{{ run.patient_id }}</el-tag><el-tag v-if="run.preview" type="warning">评估预览</el-tag><el-button v-if="busy" link @click="refreshRun">刷新状态</el-button></div></template>
      <el-alert v-if="busy" type="info" :closable="false" title="任务已保存，正在等待处理或生成结果。" />
      <el-alert v-if="run.status === 'failed'" type="error" :closable="false" :title="run.error_message || '生成失败，请联系管理员检查服务状态'" />
      <template v-if="run.status === 'succeeded'">
        <el-alert type="info" :closable="false" title="以下内容为辅助建议或草稿，请核对事实和引用依据后使用。" />
        <p class="plain-text">{{ run.result?.summary }}</p>
        <el-alert v-for="(item, index) in run.result?.warnings || []" :key="'warning-' + index" type="warning" :closable="false" :title="item" class="spaced" />
        <div v-if="run.result?.missing_data?.length" class="spaced"><strong>仍需补充或核实：</strong><ul><li v-for="(item, index) in run.result.missing_data" :key="index">{{ item }}</li></ul></div>
        <section v-for="(section, index) in run.result?.sections || []" :key="index" class="result-section">
          <h4>{{ section.title }}</h4><p class="plain-text">{{ section.content }}</p>
          <el-button v-for="id in section.source_ids" :key="id" link type="primary" @click="inspectEvidence(id)">查看依据：{{ evidenceTitle(id) }}</el-button>
        </section>
        <div class="actions"><el-button @click="copyDraft">复制草稿</el-button><el-button @click="feedbackDialog = true">记录复核反馈</el-button></div>
        <p class="metadata">Prompt v{{ run.prompt_version }} · 模型配置 v{{ run.provider_revision }} · 输入/输出 {{ run.input_tokens }}/{{ run.output_tokens }} Token</p>
      </template>
    </el-card>

    <el-collapse class="spaced" @change="loadHistory">
      <el-collapse-item title="最近任务"><el-table :data="history" empty-text="暂无历史任务"><el-table-column prop="feature_name" label="功能" /><el-table-column label="状态" width="90"><template #default="{ row }">{{ statuses[row.status] || row.status }}</template></el-table-column><el-table-column prop="create_time" label="时间" /><el-table-column label="操作" width="80"><template #default="{ row }"><el-button link @click="openRun(row.run_id)">查看</el-button></template></el-table-column></el-table></el-collapse-item>
    </el-collapse>
    <el-dialog v-model="contextDialog" title="本次提供给 AI 的患者资料" width="760px"><el-alert type="info" :closable="false" title="资料保留时间和状态，缺失信息会单独标记。" /><pre class="plain-text">{{ JSON.stringify(contextData, null, 2) }}</pre></el-dialog>
    <el-dialog v-model="evidenceDialog" title="核查引用依据" width="760px"><template v-if="evidence"><p><strong>{{ evidence.title }}</strong> {{ evidence.version ? '· ' + evidence.version : '' }}</p><p v-if="evidence.source_uri" class="plain-text">来源：{{ evidence.source_uri }}</p><p v-if="evidence.observed_at">记录时间：{{ evidence.observed_at }}</p><pre class="plain-text">{{ evidence.content }}</pre></template></el-dialog>
    <el-dialog v-model="feedbackDialog" title="人工复核反馈" width="540px"><el-radio-group v-model="feedback.outcome"><el-radio value="accepted">采纳</el-radio><el-radio value="rejected">驳回</el-radio><el-radio value="modified">修改后采纳</el-radio></el-radio-group><el-input v-model="feedback.comment" type="textarea" :rows="4" maxlength="2000" placeholder="说明核查结果或修改内容；反馈不会自动写入病历、处方或医嘱" class="spaced" /><template #footer><el-button @click="feedbackDialog = false">取消</el-button><el-button type="primary" @click="submitFeedback">保存反馈</el-button></template></el-dialog>
  </div>
</template>

<script setup>
import { computed, onActivated, onBeforeUnmount, onDeactivated, onMounted, ref, watch } from "vue";
import { useStore } from "vuex";
import { ElMessage } from "element-plus";
import { cancelAIRun, createAIRun, getAIClinicalContext, getAIEncounters, getAIFeatures, getAIPatients, getAIPrescriptions, getAIRun, getAIRuns, reviewAIRun } from "@/api/ai";

const props = defineProps({ featureKeys: { type: Array, default: () => [] }, initialFeature: { type: String, default: "" }, patientId: { type: Number, default: null }, encounterRef: { type: String, default: "" }, initialInput: { type: Object, default: () => ({}) } });
const store = useStore();
const canPreview = computed(() => store.getters["user/permissions"].includes("super_admin"));
const statuses = { queued: "已排队", running: "生成中", succeeded: "待复核", failed: "失败", cancelled: "已取消" };
const loading = ref(false), submitting = ref(false), features = ref([]), featureKey = ref("");
const patientId = ref(null), encounterRef = ref(""), prescriptionId = ref(null), patients = ref([]), encounters = ref([]), prescriptions = ref([]);
const question = ref(""), extraInput = ref(""), preview = ref(false), run = ref(null), history = ref([]);
const contextDialog = ref(false), contextData = ref(null), evidenceDialog = ref(false), evidence = ref(null), feedbackDialog = ref(false), feedback = ref({ outcome: "accepted", comment: "" });
const selected = computed(() => features.value.find(item => item.key === featureKey.value));
const needsPrescription = computed(() => ["interaction_review", "allergy_review", "dose_review", "antimicrobial_review"].includes(featureKey.value));
const busy = computed(() => ["queued", "running"].includes(run.value?.status));
let timer = null, pollVersion = 0, formVersion = 0;

function stopPolling() { pollVersion += 1; clearTimeout(timer); timer = null; }
function startPolling() {
  stopPolling();
  if (!busy.value) return;
  const version = pollVersion, id = run.value.run_id;
  const poll = async () => {
    try {
      const response = await getAIRun(id);
      if (version !== pollVersion) return;
      run.value = response.data;
      if (busy.value) timer = setTimeout(poll, 2000);
    } catch { if (version === pollVersion) stopPolling(); }
  };
  timer = setTimeout(poll, 1200);
}
async function searchPatients(keyword = "") {
  if (selected.value?.scope !== "patient") return;
  const version = formVersion;
  const response = await getAIPatients({ feature_key: featureKey.value, keyword });
  if (version !== formVersion) return;
  patients.value = response.data || [];
  if (props.patientId && !patients.value.some(item => item.patient_id === props.patientId)) patients.value.push({ patient_id: props.patientId, label: `患者 #${props.patientId}` });
}
watch(featureKey, async () => {
  formVersion += 1; stopPolling(); run.value = null; contextData.value = null;
  patientId.value = null; encounters.value = []; prescriptions.value = []; encounterRef.value = ""; prescriptionId.value = null;
  question.value = props.initialInput.question || ""; extraInput.value = "";
  if (selected.value?.scope === "patient") { await searchPatients(); patientId.value = props.patientId || (patients.value.length === 1 ? patients.value[0].patient_id : null); }
});
watch(patientId, async id => {
  stopPolling(); run.value = null;
  encounterRef.value = ""; prescriptionId.value = null; contextData.value = null; encounters.value = []; prescriptions.value = [];
  if (!id) return;
  const version = formVersion, key = featureKey.value;
  const response = await getAIEncounters({ feature_key: key, patient_id: id });
  if (version !== formVersion || id !== patientId.value) return;
  encounters.value = response.data || []; encounterRef.value = props.encounterRef || "";
  if (needsPrescription.value) {
    const response = await getAIPrescriptions({ feature_key: key, patient_id: id });
    if (version === formVersion && id === patientId.value) { prescriptions.value = response.data || []; prescriptionId.value = props.initialInput.prescription_id || null; }
  }
});
watch(encounterRef, () => { stopPolling(); run.value = null; contextData.value = null; });
watch(() => props.initialFeature, key => { if (features.value.some(item => item.key === key)) featureKey.value = key; });
watch(() => props.patientId, id => { formVersion += 1; patientId.value = id; });
watch(() => props.encounterRef, value => { encounterRef.value = value; });
async function inspectContext() {
  const sourceKeys = selected.value?.source_reference_keys || ["record_id", "structured_record_id", "prescription_id", "lab_result_id", "imaging_report_id"];
  const references = Object.fromEntries(sourceKeys.filter(key => props.initialInput[key]).map(key => [key, props.initialInput[key]]));
  if (prescriptionId.value) references.prescription_id = prescriptionId.value;
  contextData.value = (await getAIClinicalContext({ ...references, feature_key: featureKey.value, patient_id: patientId.value, encounter_ref: encounterRef.value || undefined })).data; contextDialog.value = true;
}
async function submit() {
  let extra = {};
  if (canPreview.value && extraInput.value.trim()) {
    try { extra = JSON.parse(extraInput.value); if (!extra || Array.isArray(extra) || typeof extra !== "object") throw new Error(); }
    catch { ElMessage.error("结构化资料应为有效 JSON 对象"); return; }
  }
  submitting.value = true;
  try {
    const input = { ...props.initialInput, ...extra, question: question.value };
    if (prescriptionId.value) input.prescription_id = prescriptionId.value;
    const response = await createAIRun({ feature_key: featureKey.value, patient_id: selected.value.scope === "patient" ? patientId.value : null, encounter_ref: selected.value.scope === "patient" ? encounterRef.value || null : null, input, preview: canPreview.value && preview.value });
    run.value = response.data; startPolling();
  } finally { submitting.value = false; }
}
async function refreshRun() { if (run.value) { run.value = (await getAIRun(run.value.run_id)).data; startPolling(); } }
async function openRun(id) { stopPolling(); run.value = (await getAIRun(id)).data; startPolling(); }
async function cancel() { await cancelAIRun(run.value.run_id); await refreshRun(); }
async function loadHistory() { history.value = (await getAIRuns({ feature_key: featureKey.value || undefined })).data || []; }
const evidenceTitle = id => run.value?.evidence?.find(item => item.source_id === id)?.title || "来源";
function inspectEvidence(id) { evidence.value = run.value?.evidence?.find(item => item.source_id === id); evidenceDialog.value = !!evidence.value; }
async function copyDraft() {
  const text = [run.value.result.summary, ...run.value.result.sections.map(item => `${item.title}\n${item.content}`)].join("\n\n");
  try { await navigator.clipboard.writeText(text); ElMessage.success("草稿已复制，请核对后使用"); } catch { ElMessage.info("当前环境无法自动复制，请选中结果文本复制"); }
}
async function submitFeedback() { await reviewAIRun(run.value.run_id, feedback.value); feedbackDialog.value = false; feedback.value = { outcome: "accepted", comment: "" }; ElMessage.success("复核反馈已保存"); }
onMounted(async () => {
  loading.value = true;
  try { features.value = ((await getAIFeatures()).data || []).filter(item => !props.featureKeys.length || props.featureKeys.includes(item.key)); featureKey.value = features.value.some(item => item.key === props.initialFeature) ? props.initialFeature : features.value[0]?.key || ""; }
  finally { loading.value = false; }
});
onActivated(() => { if (busy.value) startPolling(); });
onDeactivated(stopPolling);
onBeforeUnmount(stopPolling);
</script>

<style scoped>
.feature-description { line-height: 1.8; color: #606266; margin-bottom: 16px; }
.spaced { margin-top: 14px; margin-bottom: 14px; }
.actions, .result-header { display: flex; flex-wrap: wrap; align-items: center; gap: 10px; margin-top: 14px; }
.result-header { margin-top: 0; }
.plain-text { white-space: pre-wrap; overflow-wrap: anywhere; font-family: inherit; line-height: 1.7; max-height: 60vh; overflow: auto; }
.result-section { border-top: 1px solid #ebeef5; padding-top: 10px; margin-top: 18px; }
.metadata { color: #909399; font-size: 12px; }
</style>
