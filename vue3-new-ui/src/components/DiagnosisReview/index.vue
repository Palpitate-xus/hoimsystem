<template>
  <el-button v-if="canReview" size="small" @click="open">诊断复核</el-button>
  <el-dialog v-model="visible" title="责任医生诊断复核" width="min(720px, 96vw)" append-to-body destroy-on-close>
    <div v-loading="loading">
      <el-alert title="请复核下方诊断字段中的全部内容。含疑似、待排或未明确项目时，保留待确认状态。此操作单独留痕。" type="info" :closable="false" />
      <p class="diagnosis-text">{{ source.diagnosis_text || '原记录未填写诊断' }}</p>
      <el-form label-width="110px">
        <el-form-item label="当前状态"><el-tag>{{ labels[source.certainty] || '未复核' }}</el-tag><span class="revision">复核版本 {{ source.revision || 0 }}</span></el-form-item>
        <el-form-item label="本次复核状态"><el-select v-model="form.certainty" aria-label="本次复核状态"><el-option v-for="key in ['unknown', 'suspected', 'confirmed', 'excluded']" :key="key" :value="key" :label="labels[key]" /></el-select></el-form-item>
        <el-form-item label="复核说明"><el-input v-model="form.reason" type="textarea" :rows="3" maxlength="1000" placeholder="记录核实依据、仍待确认的信息或状态变化原因" /></el-form-item>
        <el-form-item v-if="form.certainty === 'confirmed'" label="确认范围"><el-checkbox v-model="acknowledged">我已逐项核对上述诊断字段，确认其中全部诊断均已明确</el-checkbox></el-form-item>
      </el-form>
      <el-alert v-if="source.signed === false" title="请先完成病历签名，再记录诊断复核。" type="warning" :closable="false" />
      <el-collapse><el-collapse-item title="历史复核记录"><el-table :data="source.history || []"><el-table-column prop="revision" label="版本" width="65" /><el-table-column label="状态" width="110"><template #default="{ row }">{{ labels[row.certainty] }}</template></el-table-column><el-table-column prop="reason" label="说明" /><el-table-column prop="reviewed_at" label="时间" width="170" /></el-table></el-collapse-item></el-collapse>
    </div>
    <template #footer><el-button @click="visible = false">关闭</el-button><el-button type="primary" :loading="saving" :disabled="!source.signed || loading || form.reason.trim().length < 5 || (form.certainty === 'confirmed' && !acknowledged)" @click="submit">记录复核</el-button></template>
  </el-dialog>
</template>

<script setup>
import { computed, ref } from "vue";
import { useStore } from "vuex";
import { ElMessage } from "element-plus";
import { getDiagnosisReview, saveDiagnosisReview } from "@/api/doctor";
const props = defineProps({ sourceKind: { type: String, default: "outpatient" }, sourceId: { type: String, required: true } });
const emit = defineEmits(["reviewed"]);
const store = useStore();
const canReview = computed(() => store.getters["user/permissions"].some(role => ["doctor", "director"].includes(role)));
const visible = ref(false), loading = ref(false), saving = ref(false), acknowledged = ref(false), source = ref({}), form = ref({ certainty: "unknown", reason: "" });
const labels = { unknown: "未明确", suspected: "疑似 / 待排", confirmed: "已明确", excluded: "已排除", stale: "原文已改变，需复核" };
async function open() {
  visible.value = true; loading.value = true; acknowledged.value = false; source.value = {}; form.value = { certainty: "unknown", reason: "" };
  try { source.value = (await getDiagnosisReview({ source_kind: props.sourceKind, source_id: props.sourceId })).data; form.value.certainty = ["confirmed", "suspected", "excluded"].includes(source.value.certainty) ? source.value.certainty : "unknown"; }
  catch { visible.value = false; }
  finally { loading.value = false; }
}
async function submit() {
  saving.value = true;
  try {
    await saveDiagnosisReview({ source_kind: props.sourceKind, source_id: props.sourceId, source_hash: source.value.source_hash, expected_revision: source.value.revision, ...form.value });
    ElMessage.success("诊断复核已留痕"); visible.value = false; emit("reviewed");
  } finally { saving.value = false; }
}
</script>

<style scoped>
.diagnosis-text { white-space: pre-wrap; overflow-wrap: anywhere; line-height: 1.8; padding: 12px; background: var(--el-fill-color-light); }
.revision { margin-left: 12px; color: var(--el-text-color-secondary); }
</style>
