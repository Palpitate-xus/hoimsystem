<template>
  <div class="app-container">
    <vab-page-header title="急诊分诊" description="按四级分诊记录主诉、生命体征和绿色通道状态，优先处理高危患者" />
    <el-card>
      <el-form :model="form" inline @submit.prevent>
        <el-form-item label="患者"><el-select v-model="form.patient_id" filterable placeholder="选择患者" style="width: 180px"><el-option v-for="item in patients" :key="item.id" :label="item.name" :value="item.id" /></el-select></el-form-item>
        <el-form-item label="分诊级别"><el-select v-model="form.triage_level" style="width: 150px"><el-option label="一级·立即" :value="1" /><el-option label="二级·紧急" :value="2" /><el-option label="三级·一般" :value="3" /><el-option label="四级·非急" :value="4" /></el-select></el-form-item>
        <el-form-item label="主诉"><el-input v-model="form.chief_complaint" maxlength="500" placeholder="症状和就诊原因" style="width: 250px" /></el-form-item>
        <el-form-item label="生命体征"><el-input v-model="form.vital_signs" maxlength="500" placeholder="如 BP 120/80，P 80" style="width: 220px" /></el-form-item>
        <el-form-item label="绿色通道"><el-switch v-model="form.green_channel" :active-value="1" :inactive-value="0" /></el-form-item>
        <el-form-item><el-button type="primary" @click="submit">提交分诊</el-button><el-button @click="load">刷新</el-button></el-form-item>
      </el-form>
    </el-card>
    <el-card>
      <el-table :data="records" v-loading="loading" border empty-text="暂无急诊分诊记录"><el-table-column prop="patient_name" label="患者" width="110" /><el-table-column label="级别" width="115"><template #default="{ row }"><el-tag :type="levelType(row.triage_level)">{{ row.triage_level_text }}</el-tag></template></el-table-column><el-table-column prop="chief_complaint" label="主诉" min-width="180" /><el-table-column prop="vital_signs" label="生命体征" min-width="150" /><el-table-column label="绿色通道" width="100"><template #default="{ row }"><el-tag v-if="row.green_channel" type="danger">优先</el-tag><span v-else>否</span></template></el-table-column><el-table-column label="状态" width="100"><template #default="{ row }"><el-tag :type="statusType(row.status)">{{ row.status_text }}</el-tag></template></el-table-column><el-table-column label="操作" width="180"><template #default="{ row }"><el-button v-if="row.status === 0" size="small" type="primary" @click="update(row, 1)">开始处理</el-button><el-button v-if="row.status === 1" size="small" type="success" @click="update(row, 2)">完成</el-button><el-button v-if="row.status < 2" size="small" @click="update(row, 3)">取消</el-button></template></el-table-column></el-table>
    </el-card>
  </div>
</template>

<script setup>
import { onMounted, ref } from "vue";
import { ElMessage } from "element-plus";
import { getPatientList } from "@/api/admin";
import { createEmergencyTriage, getEmergencyTriageList, updateEmergencyTriage } from "@/api/emergency";

const patients = ref([]); const records = ref([]); const loading = ref(false); const form = ref({ patient_id: null, triage_level: 3, chief_complaint: "", vital_signs: "", green_channel: 0 });
const levelType = (level) => ["", "danger", "warning", "primary", "info"][level] || "info";
const statusType = (status) => ["warning", "primary", "success", "info"][status] || "info";
const load = async () => { loading.value = true; try { const res = await getEmergencyTriageList(); records.value = res.data || []; } catch (error) { ElMessage.error(error?.msg || "急诊分诊加载失败"); } finally { loading.value = false; } };
const submit = async () => { if (!form.value.patient_id || !form.value.chief_complaint.trim()) { ElMessage.warning("请选择患者并填写主诉"); return; } try { await createEmergencyTriage(form.value); ElMessage.success("分诊记录已提交"); form.value.patient_id = null; form.value.chief_complaint = ""; form.value.vital_signs = ""; await load(); } catch (error) { ElMessage.error(error?.msg || "提交失败"); } };
const update = async (row, status) => { try { await updateEmergencyTriage({ triage_id: row.triage_id, status }); ElMessage.success("分诊状态已更新"); await load(); } catch (error) { ElMessage.error(error?.msg || "状态更新失败"); } };
onMounted(async () => { await Promise.all([load(), getPatientList().then((res) => { patients.value = res.data || []; })]); });
</script>
