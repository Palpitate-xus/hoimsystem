<template>
  <div class="app-container">
    <vab-page-header title="危重护理记录" description="人工记录意识、GCS、氧疗和生命体征；空项表示未记录，不推定正常值或完整量表。" />
    <el-card>
      <el-form :model="form" inline @submit.prevent>
        <el-form-item label="住院患者"><el-select v-model="form.admission_id" aria-label="住院患者" filterable placeholder="选择在院患者" style="width: 240px" @change="selectAdmission"><el-option v-for="item in admissions" :key="item.admission_id" :label="`${item.patient_name}（${item.admission_no}）`" :value="item.admission_id" /></el-select></el-form-item>
        <el-form-item label="意识"><el-select v-model="form.consciousness" aria-label="意识" clearable placeholder="未记录" style="width: 140px"><el-option v-for="(text, value) in consciousnessLabels" :key="value" :label="`${text}（${value}）`" :value="value" /></el-select></el-form-item>
        <el-form-item label="GCS总分"><el-input-number v-model="form.gcs_score" aria-label="GCS总分" :min="3" :max="15" :precision="0" :controls="false" placeholder="未记录" /></el-form-item>
        <el-form-item label="氧疗"><el-input v-model="form.oxygen_support" aria-label="氧疗" maxlength="200" placeholder="鼻导管/面罩/呼吸机" style="width: 190px" /></el-form-item>
        <el-form-item label="血压"><el-input v-model="form.blood_pressure" aria-label="血压" maxlength="30" placeholder="120/80" style="width: 120px" /></el-form-item>
        <el-form-item label="脉搏"><el-input-number v-model="form.pulse" aria-label="脉搏" :min="0" :max="300" :precision="0" :controls="false" placeholder="未记录" /></el-form-item>
        <el-form-item label="SpO₂"><el-input-number v-model="form.spo2" aria-label="SpO₂" :min="0" :max="100" :precision="1" :controls="false" placeholder="未记录" /></el-form-item>
        <el-form-item label="尿量"><el-input v-model="form.urine_output" aria-label="尿量" maxlength="100" placeholder="如 20ml/h" style="width: 130px" /></el-form-item>
        <el-form-item label="观测时点"><el-input v-model="form.record_time" aria-label="观测时点" placeholder="如 2026-10-20T08:30:00+08:00，可留空" style="width: 340px" /></el-form-item>
        <el-form-item label="备注"><el-input v-model="form.note" aria-label="危重护理备注" maxlength="1000" placeholder="异常变化和处置" style="width: 280px" /></el-form-item>
        <el-form-item><el-button type="primary" :loading="submitting" @click="submit">记录危重护理</el-button><el-button @click="load">刷新</el-button></el-form-item>
      </el-form>
      <p>观测时点留空时仅保留登记时间；GCS 总分为人工原记录，未提供分项时不能验证其计算。</p>
    </el-card>
    <el-card>
      <el-table :data="records" v-loading="loading" border empty-text="暂无危重护理记录">
        <el-table-column prop="patient_name" label="患者" width="110" />
        <el-table-column label="时点与来源" min-width="230"><template #default="{ row }"><div>{{ row.record_time ?? '未记录' }}</div><div>{{ timeBasisText(row.time_basis) }}</div><el-tag :type="row.entry_version === 'nullable_v1' ? 'info' : 'warning'">{{ row.entry_version === 'nullable_v1' ? '逐项人工记录' : '历史原值未核实' }}</el-tag></template></el-table-column>
        <el-table-column label="意识/GCS" min-width="160"><template #default="{ row }">{{ consciousnessText(row) }} / {{ row.gcs_score ?? '未记录' }}<div v-if="row.entry_version !== 'nullable_v1'">GCS 原值未核实</div></template></el-table-column>
        <el-table-column prop="oxygen_support" label="氧疗" width="130" />
        <el-table-column prop="blood_pressure" label="血压" width="100" />
        <el-table-column label="脉搏" width="80"><template #default="{ row }">{{ row.pulse ?? '未记录' }}</template></el-table-column>
        <el-table-column label="SpO₂" width="80"><template #default="{ row }">{{ row.spo2 ?? '未记录' }}</template></el-table-column>
        <el-table-column prop="urine_output" label="尿量" width="110" />
        <el-table-column prop="note" label="备注" min-width="180" show-overflow-tooltip />
        <el-table-column prop="nurse_name" label="记录护士" width="100" />
        <el-table-column v-if="canUseAI" label="AI辅助" width="150"><template #default="{ row }"><ai-action v-if="row.admission_id" label="AI 危重护理辅助" title="AI 原危重护理记录辅助" :patient-id="Number(row.patient_id)" :encounter-ref="row.admission_id" :feature-keys="['deterioration_risk', 'sepsis_risk', 'aki_risk', 'handover_summary']" initial-feature="handover_summary" :initial-input="{ critical_care_record_id: String(row.record_id) }" /></template></el-table-column>
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
import { createCriticalCareRecord, getCriticalCareRecordList } from "@/api/nursing";

const consciousnessLabels = ["清醒", "嗜睡", "意识模糊", "昏迷"];
const emptyForm = (admission_id = "", patient_id = null) => ({ admission_id, patient_id, consciousness: null, gcs_score: null, oxygen_support: "", blood_pressure: "", pulse: null, spo2: null, urine_output: "", record_time: "", note: "" });
const admissions = ref([]), records = ref([]), loading = ref(false), submitting = ref(false), form = ref(emptyForm());
const store = useStore();
const canUseAI = computed(() => store.getters["user/permissions"].some(role => ["super_admin", "doctor", "director", "nurse"].includes(role)));
let scopeEpoch = 0, loadSequence = 0, deactivated = false;
const consciousnessText = row => row.consciousness === null || row.consciousness === undefined ? "未记录" : row.entry_version !== "nullable_v1" ? `原值 ${row.consciousness}（未核实）` : `${consciousnessLabels[row.consciousness] ?? "未知编码"}（${row.consciousness}）`;
const timeBasisText = basis => ({ utc: "已声明观测时点（UTC）", unspecified: "原时钟未声明时区", recorded_at_only: "仅登记时间，观测时点未知" })[basis] ?? "原时点依据未核实";
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
  try { const res = await getCriticalCareRecordList(admission ? { admission_id: admission } : {}); if (sequence === loadSequence) records.value = res.data ?? []; }
  catch (error) { if (sequence === loadSequence) ElMessage.error(error?.msg || "危重护理记录加载失败"); }
  finally { if (sequence === loadSequence) loading.value = false; }
};
const selectAdmission = id => {
  const item = admissions.value.find(entry => entry.admission_id === id);
  scopeEpoch++; form.value = emptyForm(id, item?.patient_id ?? null); records.value = []; load();
};
const submit = async () => {
  if (submitting.value) return;
  if (!form.value.admission_id || !form.value.patient_id) { ElMessage.warning("请选择住院患者"); return; }
  let record_time;
  try { record_time = awareTime(form.value.record_time); } catch (error) { ElMessage.warning(error.message); return; }
  const payload = { ...form.value, consciousness: form.value.consciousness ?? null, gcs_score: form.value.gcs_score ?? null, pulse: form.value.pulse ?? null, spo2: form.value.spo2 ?? null, record_time }, epoch = scopeEpoch;
  submitting.value = true;
  try {
    await createCriticalCareRecord(payload); ElMessage.success("危重护理记录已保存");
    if (epoch === scopeEpoch) { scopeEpoch++; form.value = emptyForm(payload.admission_id, payload.patient_id); await load(); }
  } catch (error) { ElMessage.error(error?.msg || "记录失败"); } finally { submitting.value = false; }
};
const invalidate = () => { scopeEpoch++; loadSequence++; form.value = emptyForm(); records.value = []; loading.value = false; };
onDeactivated(() => { deactivated = true; invalidate(); });
onActivated(() => { if (deactivated) { deactivated = false; load(); } });
onBeforeUnmount(invalidate);
onMounted(async () => { const epoch = scopeEpoch; try { const res = await getAdmissionList({ status: 1 }); if (epoch === scopeEpoch) { admissions.value = res.data ?? []; await load(); } } catch (error) { ElMessage.error(error?.msg || "住院患者加载失败"); } });
</script>
