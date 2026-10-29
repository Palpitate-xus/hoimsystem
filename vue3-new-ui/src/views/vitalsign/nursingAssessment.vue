<template>
  <div class="app-container">
    <el-card>
      <el-alert v-if="editingId" :title="`继续填写草稿 #${editingId}；保存后仍须单独完成评估`" type="info" :closable="false" />
      <el-form :model="form" inline @submit.prevent>
        <el-form-item label="住院患者"><el-select v-model="form.admission_id" aria-label="住院患者" filterable placeholder="选择在院患者" style="width: 250px" @change="selectAdmission"><el-option v-for="item in admissions" :key="item.admission_id" :label="`${item.patient_name}（${item.admission_no}）`" :value="item.admission_id" /></el-select></el-form-item>
        <el-form-item label="ADL评分"><el-input-number v-model="form.adl_score" aria-label="ADL评分" :min="0" :max="100" :precision="0" :controls="false" placeholder="未评估" /></el-form-item>
        <el-form-item v-for="field in riskFields" :key="field.key" :label="field.label"><el-select v-model="form[field.key]" :aria-label="field.label" clearable placeholder="未评估" style="width: 125px"><el-option v-for="(text, value) in risks" :key="value" :label="`${text}（${value}）`" :value="value" /></el-select></el-form-item>
        <el-form-item label="意识"><el-select v-model="form.consciousness" aria-label="意识" clearable placeholder="未评估" style="width: 140px"><el-option v-for="(text, value) in consciousnessLabels" :key="value" :label="`${text}（${value}）`" :value="value" /></el-select></el-form-item>
        <el-form-item label="评估时点"><el-input v-model="form.assessed_at" aria-label="评估时点" placeholder="如 2026-10-20T08:30:00+08:00，可留空" style="width: 340px" /></el-form-item>
        <el-form-item label="备注"><el-input v-model="form.note" aria-label="护理评估备注" maxlength="1000" placeholder="护理重点和风险说明" style="width: 300px" /></el-form-item>
        <el-form-item><el-button type="primary" :loading="submitting" @click="submit">{{ editingId ? '保存修改' : '保存评估' }}</el-button><el-button v-if="editingId" @click="cancelEdit">取消填写</el-button><el-button @click="load">刷新</el-button></el-form-item>
      </el-form>
      <p>空项表示未评估；0分需手动录入。至少评估一项才能完成，请填写实际评估时间。</p>
    </el-card>
    <el-card>
      <el-table :data="records" v-loading="loading" border empty-text="暂无护理评估">
        <el-table-column prop="patient_name" label="患者" width="110" />
        <el-table-column label="评估原值" min-width="240"><template #default="{ row }"><div v-for="field in valueFields" :key="field.key">{{ field.label }}：{{ recordedValue(row, field.key) }}</div></template></el-table-column>
        <el-table-column label="来源与时点" min-width="240"><template #default="{ row }"><el-tag :type="row.entry_version === 'nullable_v1' ? 'info' : 'warning'">{{ row.entry_version === 'nullable_v1' ? '逐项人工记录' : '历史原值未核实' }}</el-tag><div>评估时点：{{ row.assessed_at ?? '未记录' }}</div><div>登记：{{ row.create_time ?? '未记录' }}</div><div>未评估：{{ missingLabels(row) }}</div><div>尚未验证为标准风险量表</div></template></el-table-column>
        <el-table-column prop="note" label="护理重点" min-width="180" />
        <el-table-column prop="nurse_name" label="评估护士" width="100" />
        <el-table-column label="状态" width="90"><template #default="{ row }"><el-tag :type="row.status === 1 ? 'success' : 'warning'">{{ row.status_text }}</el-tag></template></el-table-column>
        <el-table-column label="操作" width="290"><template #default="{ row }"><template v-if="row.status === 0"><el-button size="small" @click="edit(row)">继续填写</el-button><el-button size="small" type="success" :disabled="!hasAssessment(row) || editingId === row.assessment_id" @click="complete(row)">完成评估</el-button></template><ai-action v-if="canUseAI && row.status === 1 && row.admission_id" label="AI 护理辅助" title="AI 原护理评估辅助" :patient-id="Number(row.patient_id)" :encounter-ref="row.admission_id" :feature-keys="['nursing_risk_assessment', 'nursing_plan', 'handover_summary']" initial-feature="nursing_risk_assessment" :initial-input="{ nursing_assessment_id: String(row.assessment_id) }" /></template></el-table-column>
      </el-table>
    </el-card>
  </div>
</template>

<script setup>
import { computed, onActivated, onBeforeUnmount, onDeactivated, onMounted, ref } from "vue";
import { useStore } from "vuex";
import { ElMessage } from "element-plus";
import AiAction from "@/components/AIAction/index.vue";
import { getAdmissionList } from "@/api/admission";
import { completeNursingAssessment, createNursingAssessment, getNursingAssessmentList, updateNursingAssessment } from "@/api/nursing";

const risks = ["无", "低", "中", "高"], consciousnessLabels = ["清醒", "嗜睡", "意识模糊", "昏迷"];
const riskFields = [{ key: "pressure_ulcer_risk", label: "压疮风险" }, { key: "fall_risk", label: "跌倒风险" }, { key: "nutrition_risk", label: "营养风险" }];
const valueFields = [{ key: "adl_score", label: "ADL" }, ...riskFields, { key: "consciousness", label: "意识" }];
const emptyForm = (admission_id = "", patient_id = null) => ({ admission_id, patient_id, adl_score: null, pressure_ulcer_risk: null, fall_risk: null, consciousness: null, nutrition_risk: null, assessed_at: "", note: "" });
const admissions = ref([]), records = ref([]), loading = ref(false), submitting = ref(false), editingId = ref(null), form = ref(emptyForm());
const store = useStore();
const canUseAI = computed(() => store.getters["user/permissions"].some(role => ["super_admin", "doctor", "director", "nurse"].includes(role)));
let scopeEpoch = 0, loadSequence = 0, deactivated = false;
const hasAssessment = row => valueFields.some(field => row[field.key] !== null && row[field.key] !== undefined);
const missingLabels = row => valueFields.filter(field => row[field.key] === null || row[field.key] === undefined).map(field => field.label).join("、") || "无空项";
const recordedValue = (row, key) => {
  const value = row[key];
  if (value === null || value === undefined) return "未评估";
  if (row.entry_version !== "nullable_v1") return `原值 ${value}（未核实）`;
  if (key === "adl_score") return String(value);
  return `${(key === "consciousness" ? consciousnessLabels : risks)[value] ?? "未知编码"}（${value}）`;
};
// Keep an explicit observed time separate from the time at which a record is entered.
const awareTime = (value) => {
  const text = value.trim();
  if (!text) return null;
  const match = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.\d{1,6})?(Z|[+-]\d{2}:\d{2})$/.exec(text);
  if (!match) throw new Error("时点须为带时区的完整日期，例如 2026-10-20T08:30:00+08:00");
  const [, year, month, day, hour, minute, second, zone] = match;
  const y = Number(year), m = Number(month), d = Number(day);
  const days = [31, y % 4 === 0 && (y % 100 !== 0 || y % 400 === 0) ? 29 : 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31];
  if (y < 1 || m < 1 || m > 12 || d < 1 || d > days[m - 1] || Number(hour) > 23 || Number(minute) > 59 || Number(second) > 59 || (zone !== "Z" && (Number(zone.slice(1, 3)) > 23 || Number(zone.slice(4)) > 59)) || !Number.isFinite(Date.parse(text)) || new Date(text).getUTCFullYear() < 1 || new Date(text).getUTCFullYear() > 9999) throw new Error("请输入合法的日期、时间和时区");
  return text;
};
const load = async () => {
  const sequence = ++loadSequence, admission = form.value.admission_id;
  loading.value = true;
  try { const res = await getNursingAssessmentList(admission ? { admission_id: admission } : {}); if (sequence === loadSequence) records.value = res.data ?? []; }
  catch (error) { if (sequence === loadSequence) ElMessage.error(error?.msg || "护理评估加载失败"); }
  finally { if (sequence === loadSequence) loading.value = false; }
};
const selectAdmission = id => {
  const item = admissions.value.find(entry => entry.admission_id === id);
  scopeEpoch++; editingId.value = null; form.value = emptyForm(id, item?.patient_id ?? null); records.value = []; load();
};
const cancelEdit = () => { scopeEpoch++; editingId.value = null; form.value = emptyForm(form.value.admission_id, form.value.patient_id); };
const edit = row => {
  scopeEpoch++; editingId.value = row.assessment_id;
  form.value = { ...emptyForm(row.admission_id, row.patient_id), ...Object.fromEntries(valueFields.map(field => [field.key, row[field.key] ?? null])), assessed_at: row.assessed_at ?? "", note: row.note ?? "" };
};
const submit = async () => {
  if (submitting.value) return;
  if (!form.value.admission_id || !form.value.patient_id) { ElMessage.warning("请选择住院患者"); return; }
  let assessed_at;
  try { assessed_at = awareTime(form.value.assessed_at); } catch (error) { ElMessage.warning(error.message); return; }
  const values = Object.fromEntries(valueFields.map(field => [field.key, form.value[field.key] ?? null]));
  const id = editingId.value, epoch = scopeEpoch;
  const payload = { ...values, assessed_at, note: form.value.note };
  submitting.value = true;
  try {
    if (id !== null) await updateNursingAssessment({ assessment_id: id, ...payload });
    else await createNursingAssessment({ admission_id: form.value.admission_id, patient_id: form.value.patient_id, ...payload });
    ElMessage.success("护理评估草稿已保存");
    if (epoch === scopeEpoch) { cancelEdit(); await load(); }
  } catch (error) { ElMessage.error(error?.msg || "保存失败"); } finally { submitting.value = false; }
};
const complete = async row => {
  if (!hasAssessment(row)) return;
  const epoch = scopeEpoch;
  try { await completeNursingAssessment({ assessment_id: row.assessment_id }); ElMessage.success("护理评估已完成"); if (epoch === scopeEpoch) { if (editingId.value === row.assessment_id) cancelEdit(); await load(); } }
  catch (error) { ElMessage.error(error?.msg || "完成失败"); }
};
const invalidate = () => { scopeEpoch++; loadSequence++; editingId.value = null; form.value = emptyForm(); records.value = []; loading.value = false; };
onDeactivated(() => { deactivated = true; invalidate(); });
onActivated(() => { if (deactivated) { deactivated = false; load(); } });
onBeforeUnmount(invalidate);
onMounted(async () => { const epoch = scopeEpoch; try { const res = await getAdmissionList({ status: 1 }); if (epoch === scopeEpoch) { admissions.value = res.data ?? []; await load(); } } catch (error) { ElMessage.error(error?.msg || "住院患者加载失败"); } });
</script>
