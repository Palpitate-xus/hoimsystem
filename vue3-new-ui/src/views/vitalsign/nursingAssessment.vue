<template>
  <div class="app-container">
    <vab-page-header title="入院护理评估" description="记录 ADL、压疮、跌倒、意识和营养风险，完成后形成护理计划依据" />
    <el-card>
      <el-form :model="form" inline @submit.prevent>
        <el-form-item label="住院患者"><el-select v-model="form.admission_id" filterable placeholder="选择在院患者" style="width: 250px" @change="selectAdmission"><el-option v-for="item in admissions" :key="item.admission_id" :label="`${item.patient_name}（${item.admission_no}）`" :value="item.admission_id" /></el-select></el-form-item>
        <el-form-item label="ADL评分"><el-input-number v-model="form.adl_score" :min="0" :max="100" /></el-form-item>
        <el-form-item label="压疮风险"><el-select v-model="form.pressure_ulcer_risk" style="width: 110px"><el-option label="无" :value="0" /><el-option label="低" :value="1" /><el-option label="中" :value="2" /><el-option label="高" :value="3" /></el-select></el-form-item>
        <el-form-item label="跌倒风险"><el-select v-model="form.fall_risk" style="width: 110px"><el-option label="无" :value="0" /><el-option label="低" :value="1" /><el-option label="中" :value="2" /><el-option label="高" :value="3" /></el-select></el-form-item>
        <el-form-item label="意识"><el-select v-model="form.consciousness" style="width: 110px"><el-option label="清醒" :value="0" /><el-option label="嗜睡" :value="1" /><el-option label="意识模糊" :value="2" /><el-option label="昏迷" :value="3" /></el-select></el-form-item>
        <el-form-item label="营养风险"><el-select v-model="form.nutrition_risk" style="width: 110px"><el-option label="无" :value="0" /><el-option label="低" :value="1" /><el-option label="中" :value="2" /><el-option label="高" :value="3" /></el-select></el-form-item>
        <el-form-item label="备注"><el-input v-model="form.note" maxlength="1000" placeholder="护理重点和风险说明" style="width: 300px" /></el-form-item>
        <el-form-item><el-button type="primary" :loading="submitting" @click="submit">保存评估</el-button><el-button @click="load">刷新</el-button></el-form-item>
      </el-form>
    </el-card>
    <el-card><el-table :data="records" v-loading="loading" border empty-text="暂无护理评估"><el-table-column prop="patient_name" label="患者" width="120" /><el-table-column prop="adl_score" label="ADL" width="80" /><el-table-column label="压疮/跌倒" width="120"><template #default="{ row }">{{ riskText(row.pressure_ulcer_risk) }}/{{ riskText(row.fall_risk) }}</template></el-table-column><el-table-column prop="note" label="护理重点" min-width="240" /><el-table-column prop="nurse_name" label="评估护士" width="110" /><el-table-column label="状态" width="100"><template #default="{ row }"><el-tag :type="row.status ? 'success' : 'warning'">{{ row.status_text }}</el-tag></template></el-table-column><el-table-column label="操作" width="100"><template #default="{ row }"><el-button v-if="!row.status" size="small" type="success" @click="complete(row)">完成评估</el-button></template></el-table-column></el-table></el-card>
  </div>
</template>

<script setup>
import { onMounted, ref } from "vue";
import { ElMessage } from "element-plus";
import { getAdmissionList } from "@/api/admission";
import { completeNursingAssessment, createNursingAssessment, getNursingAssessmentList } from "@/api/nursing";

const admissions = ref([]); const records = ref([]); const loading = ref(false); const submitting = ref(false); const form = ref({ admission_id: "", patient_id: null, adl_score: 100, pressure_ulcer_risk: 0, fall_risk: 0, consciousness: 0, nutrition_risk: 0, note: "" });
const riskText = (value) => ["无", "低", "中", "高"][value] || "未知";
const load = async () => { loading.value = true; try { const res = await getNursingAssessmentList(); records.value = res.data || []; } catch (error) { ElMessage.error(error?.msg || "护理评估加载失败"); } finally { loading.value = false; } };
const selectAdmission = (id) => { const item = admissions.value.find((entry) => entry.admission_id === id); form.value.patient_id = item?.patient_id || null; };
const submit = async () => { if (!form.value.admission_id || !form.value.patient_id) { ElMessage.warning("请选择住院患者"); return; } submitting.value = true; try { await createNursingAssessment(form.value); ElMessage.success("护理评估已保存"); form.value.note = ""; await load(); } catch (error) { ElMessage.error(error?.msg || "保存失败"); } finally { submitting.value = false; } };
const complete = async (row) => { try { await completeNursingAssessment({ assessment_id: row.assessment_id }); ElMessage.success("护理评估已完成"); await load(); } catch (error) { ElMessage.error(error?.msg || "完成失败"); } };
onMounted(async () => { const res = await getAdmissionList({ status: 1 }); admissions.value = res.data || []; if (admissions.value[0]) { form.value.admission_id = admissions.value[0].admission_id; selectAdmission(form.value.admission_id); } await load(); });
</script>
