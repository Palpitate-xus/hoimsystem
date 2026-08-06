<template>
  <div class="app-container">
    <vab-page-header title="急诊病历" description="按急诊分诊记录书写主诉、查体、诊断和处理计划，签名后不可修改" />
    <el-card>
      <el-form :model="form" label-width="90px">
        <el-form-item label="急诊患者"><el-select v-model="form.triage_id" filterable placeholder="选择分诊记录" style="width: 280px"><el-option v-for="item in triages" :key="item.triage_id" :label="`${item.patient_name}（${item.triage_level_text}）`" :value="item.triage_id" /></el-select></el-form-item>
        <el-form-item label="主诉"><el-input v-model="form.chief_complaint" maxlength="500" placeholder="患者主要症状和就诊原因" /></el-form-item>
        <el-form-item label="现病史"><el-input v-model="form.present_illness" type="textarea" maxlength="1000" /></el-form-item>
        <el-form-item label="体格检查"><el-input v-model="form.physical_exam" type="textarea" maxlength="1000" /></el-form-item>
        <el-form-item label="诊断"><el-input v-model="form.diagnosis" maxlength="500" /></el-form-item>
        <el-form-item label="处理计划"><el-input v-model="form.treatment_plan" type="textarea" maxlength="1000" /></el-form-item>
        <el-form-item><el-button type="primary" :loading="submitting" @click="submit">保存急诊病历</el-button><el-button @click="load">刷新</el-button></el-form-item>
      </el-form>
    </el-card>
    <el-card>
      <el-table :data="records" v-loading="loading" border empty-text="暂无急诊病历"><el-table-column prop="patient_name" label="患者" width="110" /><el-table-column prop="chief_complaint" label="主诉" min-width="180" /><el-table-column prop="diagnosis" label="诊断" min-width="180" /><el-table-column prop="treatment_plan" label="处理计划" min-width="220" /><el-table-column prop="doctor_name" label="医生" width="110" /><el-table-column label="状态" width="100"><template #default="{ row }"><el-tag :type="row.status ? 'success' : 'warning'">{{ row.status_text }}</el-tag></template></el-table-column><el-table-column label="操作" width="100"><template #default="{ row }"><el-button v-if="!row.status" size="small" type="success" @click="sign(row)">签名</el-button></template></el-table-column></el-table>
    </el-card>
  </div>
</template>

<script setup>
import { onMounted, ref } from "vue";
import { ElMessage } from "element-plus";
import { createEmergencyMedicalRecord, getEmergencyMedicalRecordList, getEmergencyTriageList, signEmergencyMedicalRecord } from "@/api/emergency";

const triages = ref([]); const records = ref([]); const loading = ref(false); const submitting = ref(false); const form = ref({ triage_id: "", chief_complaint: "", present_illness: "", physical_exam: "", diagnosis: "", treatment_plan: "" });
const load = async () => { loading.value = true; try { const res = await getEmergencyMedicalRecordList(); records.value = res.data || []; } catch (error) { ElMessage.error(error?.msg || "急诊病历加载失败"); } finally { loading.value = false; } };
const loadTriages = async () => { const res = await getEmergencyTriageList(); triages.value = (res.data || []).filter((item) => item.status !== 3); if (!form.value.triage_id && triages.value[0]) form.value.triage_id = triages.value[0].triage_id; };
const submit = async () => { if (!form.value.triage_id || !form.value.chief_complaint.trim()) { ElMessage.warning("请选择患者并填写主诉"); return; } submitting.value = true; try { await createEmergencyMedicalRecord(form.value); ElMessage.success("急诊病历已保存"); form.value.chief_complaint = ""; form.value.present_illness = ""; form.value.physical_exam = ""; form.value.diagnosis = ""; form.value.treatment_plan = ""; await load(); } catch (error) { ElMessage.error(error?.msg || "保存失败"); } finally { submitting.value = false; } };
const sign = async (row) => { try { await signEmergencyMedicalRecord({ record_id: row.record_id }); ElMessage.success("急诊病历已签名"); await load(); } catch (error) { ElMessage.error(error?.msg || "签名失败"); } };
onMounted(async () => { await Promise.all([load(), loadTriages()]); });
</script>
