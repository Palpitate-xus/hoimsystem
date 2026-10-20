<template>
  <div class="app-container">
    <vab-page-header title="护理计划" description="围绕护理诊断制定目标和措施，完成后保留闭环记录" />
    <el-card>
      <el-form :model="form" inline @submit.prevent>
        <el-form-item label="住院患者"><el-select v-model="form.admission_id" aria-label="住院患者" filterable placeholder="选择在院患者" style="width: 240px" @change="selectAdmission"><el-option v-for="item in admissions" :key="item.admission_id" :label="`${item.patient_name}（${item.admission_no}）`" :value="item.admission_id" /></el-select></el-form-item>
        <el-form-item label="护理诊断"><el-input v-model="form.nursing_diagnosis" maxlength="500" placeholder="如活动耐力下降" style="width: 230px" /></el-form-item>
        <el-form-item label="目标"><el-input v-model="form.goal" maxlength="500" placeholder="可衡量的护理目标" style="width: 250px" /></el-form-item>
        <el-form-item label="护理措施"><el-input v-model="form.measures" maxlength="1000" placeholder="具体护理措施和频次" style="width: 300px" /></el-form-item>
        <el-form-item><el-button type="primary" :loading="submitting" @click="submit">保存护理计划</el-button><el-button @click="load">刷新</el-button></el-form-item>
      </el-form>
    </el-card>
    <el-card><el-table :data="records" v-loading="loading" border empty-text="暂无护理计划"><el-table-column prop="patient_name" label="患者" width="120" /><el-table-column prop="nursing_diagnosis" label="护理诊断" min-width="180" /><el-table-column prop="goal" label="目标" min-width="200" /><el-table-column prop="measures" label="措施" min-width="260" /><el-table-column prop="nurse_name" label="责任护士" width="110" /><el-table-column label="状态" width="100"><template #default="{ row }"><el-tag :type="row.status === 0 ? 'warning' : row.status === 1 ? 'success' : 'info'">{{ row.status_text }}</el-tag></template></el-table-column><el-table-column label="操作" width="270"><template #default="{ row }"><el-button v-if="row.status === 0" size="small" type="success" @click="complete(row)">完成计划</el-button><ai-action v-if="canUseAI && row.admission_id" label="AI 护理计划辅助" title="AI 原护理计划辅助" :patient-id="Number(row.patient_id)" :encounter-ref="row.admission_id" :feature-keys="['nursing_plan', 'handover_summary']" initial-feature="nursing_plan" :initial-input="{ nursing_plan_id: String(row.plan_id) }" /></template></el-table-column></el-table></el-card>
  </div>
</template>

<script setup>
import { computed, onActivated, onBeforeUnmount, onDeactivated, onMounted, ref } from "vue";
import { useStore } from "vuex";
import { ElMessage } from "element-plus";
import AiAction from "@/components/AIAction/index.vue";
import { getAdmissionList } from "@/api/admission";
import { createNursingPlan, getNursingPlanList, updateNursingPlan } from "@/api/nursing";

const emptyForm = (admission_id = "", patient_id = null) => ({ admission_id, patient_id, nursing_diagnosis: "", goal: "", measures: "" });
const admissions = ref([]), records = ref([]), loading = ref(false), submitting = ref(false), form = ref(emptyForm());
const store = useStore();
const canUseAI = computed(() => store.getters["user/permissions"].some(role => ["super_admin", "doctor", "director", "nurse"].includes(role)));
let scopeEpoch = 0, loadSequence = 0, deactivated = false;
const load = async () => {
  const sequence = ++loadSequence, admission = form.value.admission_id;
  loading.value = true;
  try { const res = await getNursingPlanList(admission ? { admission_id: admission } : {}); if (sequence === loadSequence) records.value = res.data ?? []; }
  catch (error) { if (sequence === loadSequence) ElMessage.error(error?.msg || "护理计划加载失败"); }
  finally { if (sequence === loadSequence) loading.value = false; }
};
const selectAdmission = id => {
  const item = admissions.value.find(entry => entry.admission_id === id);
  scopeEpoch++; form.value = emptyForm(id, item?.patient_id ?? null); records.value = []; load();
};
const submit = async () => {
  if (submitting.value) return;
  if (!form.value.admission_id || !form.value.patient_id || !form.value.nursing_diagnosis.trim() || !form.value.goal.trim() || !form.value.measures.trim()) { ElMessage.warning("请完整填写患者、护理诊断、目标和措施"); return; }
  const payload = { ...form.value }, epoch = scopeEpoch;
  submitting.value = true;
  try { await createNursingPlan(payload); ElMessage.success("护理计划已保存"); if (epoch === scopeEpoch) { scopeEpoch++; form.value = emptyForm(payload.admission_id, payload.patient_id); await load(); } }
  catch (error) { ElMessage.error(error?.msg || "保存失败"); } finally { submitting.value = false; }
};
const complete = async row => { const epoch = scopeEpoch; try { await updateNursingPlan({ plan_id: row.plan_id, status: 1 }); ElMessage.success("护理计划已完成"); if (epoch === scopeEpoch) await load(); } catch (error) { ElMessage.error(error?.msg || "完成失败"); } };
const invalidate = () => { scopeEpoch++; loadSequence++; form.value = emptyForm(); records.value = []; loading.value = false; };
onDeactivated(() => { deactivated = true; invalidate(); });
onActivated(() => { if (deactivated) { deactivated = false; load(); } });
onBeforeUnmount(invalidate);
onMounted(async () => { const epoch = scopeEpoch; try { const res = await getAdmissionList({ status: 1 }); if (epoch === scopeEpoch) { admissions.value = res.data ?? []; await load(); } } catch (error) { ElMessage.error(error?.msg || "住院患者加载失败"); } });
</script>
