<template>
  <div class="app-container">
    <vab-page-header title="护理计划" description="围绕护理诊断制定目标和措施，完成后保留闭环记录" />
    <el-card>
      <el-form :model="form" inline @submit.prevent>
        <el-form-item label="住院患者"><el-select v-model="form.admission_id" filterable placeholder="选择在院患者" style="width: 240px" @change="selectAdmission"><el-option v-for="item in admissions" :key="item.admission_id" :label="`${item.patient_name}（${item.admission_no}）`" :value="item.admission_id" /></el-select></el-form-item>
        <el-form-item label="护理诊断"><el-input v-model="form.nursing_diagnosis" maxlength="500" placeholder="如活动耐力下降" style="width: 230px" /></el-form-item>
        <el-form-item label="目标"><el-input v-model="form.goal" maxlength="500" placeholder="可衡量的护理目标" style="width: 250px" /></el-form-item>
        <el-form-item label="护理措施"><el-input v-model="form.measures" maxlength="1000" placeholder="具体护理措施和频次" style="width: 300px" /></el-form-item>
        <el-form-item><el-button type="primary" :loading="submitting" @click="submit">保存护理计划</el-button><el-button @click="load">刷新</el-button></el-form-item>
      </el-form>
    </el-card>
    <el-card><el-table :data="records" v-loading="loading" border empty-text="暂无护理计划"><el-table-column prop="patient_name" label="患者" width="120" /><el-table-column prop="nursing_diagnosis" label="护理诊断" min-width="180" /><el-table-column prop="goal" label="目标" min-width="200" /><el-table-column prop="measures" label="措施" min-width="260" /><el-table-column prop="nurse_name" label="责任护士" width="110" /><el-table-column label="状态" width="100"><template #default="{ row }"><el-tag :type="row.status === 0 ? 'warning' : row.status === 1 ? 'success' : 'info'">{{ row.status_text }}</el-tag></template></el-table-column><el-table-column label="操作" width="100"><template #default="{ row }"><el-button v-if="row.status === 0" size="small" type="success" @click="complete(row)">完成计划</el-button></template></el-table-column></el-table></el-card>
  </div>
</template>

<script setup>
import { onMounted, ref } from "vue";
import { ElMessage } from "element-plus";
import { getAdmissionList } from "@/api/admission";
import { createNursingPlan, getNursingPlanList, updateNursingPlan } from "@/api/nursing";

const admissions = ref([]); const records = ref([]); const loading = ref(false); const submitting = ref(false); const form = ref({ admission_id: "", patient_id: null, nursing_diagnosis: "", goal: "", measures: "" });
const load = async () => { loading.value = true; try { const res = await getNursingPlanList(); records.value = res.data || []; } catch (error) { ElMessage.error(error?.msg || "护理计划加载失败"); } finally { loading.value = false; } };
const selectAdmission = (id) => { const item = admissions.value.find((entry) => entry.admission_id === id); form.value.patient_id = item?.patient_id || null; };
const submit = async () => { if (!form.value.admission_id || !form.value.patient_id || !form.value.nursing_diagnosis.trim() || !form.value.goal.trim() || !form.value.measures.trim()) { ElMessage.warning("请完整填写患者、护理诊断、目标和措施"); return; } submitting.value = true; try { await createNursingPlan(form.value); ElMessage.success("护理计划已保存"); form.value.nursing_diagnosis = ""; form.value.goal = ""; form.value.measures = ""; await load(); } catch (error) { ElMessage.error(error?.msg || "保存失败"); } finally { submitting.value = false; } };
const complete = async (row) => { try { await updateNursingPlan({ plan_id: row.plan_id, status: 1 }); ElMessage.success("护理计划已完成"); await load(); } catch (error) { ElMessage.error(error?.msg || "完成失败"); } };
onMounted(async () => { const res = await getAdmissionList({ status: 1 }); admissions.value = res.data || []; if (admissions.value[0]) { form.value.admission_id = admissions.value[0].admission_id; selectAdmission(form.value.admission_id); } await load(); });
</script>
