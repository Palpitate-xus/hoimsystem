<template>
  <div class="app-container">
    <vab-page-header title="危重护理记录" description="记录危重患者意识、GCS、氧疗、生命体征和尿量，支持 ICU 级连续观察" />
    <el-card>
      <el-form :model="form" inline @submit.prevent>
        <el-form-item label="住院患者"><el-select v-model="form.admission_id" filterable placeholder="选择在院患者" style="width: 240px" @change="selectAdmission"><el-option v-for="item in admissions" :key="item.admission_id" :label="`${item.patient_name}（${item.admission_no}）`" :value="item.admission_id" /></el-select></el-form-item>
        <el-form-item label="意识"><el-select v-model="form.consciousness" style="width: 120px"><el-option label="清醒" :value="0" /><el-option label="嗜睡" :value="1" /><el-option label="意识模糊" :value="2" /><el-option label="昏迷" :value="3" /></el-select></el-form-item>
        <el-form-item label="GCS"><el-input-number v-model="form.gcs_score" :min="3" :max="15" controls-position="right" /></el-form-item>
        <el-form-item label="氧疗"><el-input v-model="form.oxygen_support" maxlength="200" placeholder="鼻导管/面罩/呼吸机" style="width: 190px" /></el-form-item>
        <el-form-item label="血压"><el-input v-model="form.blood_pressure" maxlength="30" placeholder="120/80" style="width: 120px" /></el-form-item>
        <el-form-item label="脉搏"><el-input-number v-model="form.pulse" :min="0" :max="300" /></el-form-item>
        <el-form-item label="SpO₂"><el-input-number v-model="form.spo2" :min="0" :max="100" :precision="1" /></el-form-item>
        <el-form-item label="尿量"><el-input v-model="form.urine_output" maxlength="100" placeholder="如 20ml/h" style="width: 130px" /></el-form-item>
        <el-form-item label="备注"><el-input v-model="form.note" maxlength="1000" placeholder="异常变化和处置" style="width: 280px" /></el-form-item>
        <el-form-item><el-button type="primary" :loading="submitting" @click="submit">记录危重护理</el-button><el-button @click="load">刷新</el-button></el-form-item>
      </el-form>
    </el-card>
    <el-card><el-table :data="records" v-loading="loading" border empty-text="暂无危重护理记录"><el-table-column prop="patient_name" label="患者" width="110" /><el-table-column prop="record_time" label="记录时间" width="175" /><el-table-column label="意识/GCS" width="110"><template #default="{ row }">{{ consciousnessText(row.consciousness) }} / {{ row.gcs_score || '-' }}</template></el-table-column><el-table-column prop="oxygen_support" label="氧疗" width="150" /><el-table-column prop="blood_pressure" label="血压" width="100" /><el-table-column prop="pulse" label="脉搏" width="80" /><el-table-column prop="spo2" label="SpO₂" width="80" /><el-table-column prop="urine_output" label="尿量" width="110" /><el-table-column prop="note" label="备注" min-width="220" show-overflow-tooltip /><el-table-column prop="nurse_name" label="记录护士" width="110" /></el-table></el-card>
  </div>
</template>

<script setup>
import { onMounted, ref } from "vue";
import { ElMessage } from "element-plus";
import { getAdmissionList } from "@/api/admission";
import { createCriticalCareRecord, getCriticalCareRecordList } from "@/api/nursing";

const admissions = ref([]); const records = ref([]); const loading = ref(false); const submitting = ref(false); const form = ref({ admission_id: "", patient_id: null, consciousness: 0, gcs_score: 15, oxygen_support: "", blood_pressure: "", pulse: null, spo2: null, urine_output: "", note: "" });
const consciousnessText = (value) => ["清醒", "嗜睡", "意识模糊", "昏迷"][value] || "未知";
const load = async () => { loading.value = true; try { const res = await getCriticalCareRecordList(); records.value = res.data || []; } catch (error) { ElMessage.error(error?.msg || "危重护理记录加载失败"); } finally { loading.value = false; } };
const selectAdmission = (id) => { const item = admissions.value.find((entry) => entry.admission_id === id); form.value.patient_id = item?.patient_id || null; };
const submit = async () => { if (!form.value.admission_id || !form.value.patient_id) { ElMessage.warning("请选择住院患者"); return; } submitting.value = true; try { await createCriticalCareRecord(form.value); ElMessage.success("危重护理记录已保存"); form.value.note = ""; await load(); } catch (error) { ElMessage.error(error?.msg || "记录失败"); } finally { submitting.value = false; } };
onMounted(async () => { const res = await getAdmissionList({ status: 1 }); admissions.value = res.data || []; if (admissions.value[0]) { form.value.admission_id = admissions.value[0].admission_id; selectAdmission(form.value.admission_id); } await load(); });
</script>
