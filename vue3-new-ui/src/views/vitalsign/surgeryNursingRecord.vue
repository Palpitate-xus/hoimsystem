<template>
  <div class="app-container">
    <vab-page-header title="手术护理记录" description="按术前、术中、术后三个阶段记录核查、器械清点、标本和伤口情况" />
    <el-card>
      <el-form :model="form" inline @submit.prevent>
        <el-form-item label="手术排台"><el-select v-model="form.schedule_id" filterable placeholder="选择手术排台" style="width: 260px" @change="selectSchedule"><el-option v-for="item in schedules" :key="item.schedule_id" :label="`${item.patient_name}｜${item.surgery_name}`" :value="item.schedule_id" /></el-select></el-form-item>
        <el-form-item label="阶段"><el-select v-model="form.phase" style="width: 110px"><el-option label="术前" :value="0" /><el-option label="术中" :value="1" /><el-option label="术后" :value="2" /></el-select></el-form-item>
        <el-form-item label="核查内容"><el-input v-model="form.checklist" maxlength="1000" placeholder="身份、手术部位、器械和用物核查" style="width: 320px" /></el-form-item>
        <el-form-item label="器械清点"><el-input v-model="form.instrument_count" maxlength="300" style="width: 180px" /></el-form-item>
        <el-form-item label="标本"><el-input v-model="form.specimen" maxlength="500" style="width: 180px" /></el-form-item>
        <el-form-item label="伤口"><el-input v-model="form.wound_condition" maxlength="500" style="width: 180px" /></el-form-item>
        <el-form-item><el-button type="primary" :loading="submitting" @click="submit">保存手术护理记录</el-button><el-button @click="load">刷新</el-button></el-form-item>
      </el-form>
    </el-card>
    <el-card><el-table :data="records" v-loading="loading" border empty-text="暂无手术护理记录"><el-table-column prop="patient_name" label="患者" width="110" /><el-table-column prop="surgery_name" label="手术" width="160" /><el-table-column prop="phase_text" label="阶段" width="80" /><el-table-column prop="checklist" label="核查内容" min-width="260" /><el-table-column prop="instrument_count" label="器械清点" width="160" /><el-table-column prop="specimen" label="标本" width="150" /><el-table-column prop="wound_condition" label="伤口" width="150" /><el-table-column prop="record_time" label="记录时间" width="175" /><el-table-column prop="nurse_name" label="记录护士" width="110" /></el-table></el-card>
  </div>
</template>

<script setup>
import { onMounted, ref } from "vue";
import { ElMessage } from "element-plus";
import { getSurgeryScheduleList } from "@/api/surgery";
import { createSurgeryNursingRecord, getSurgeryNursingRecordList } from "@/api/nursing";

const schedules = ref([]); const records = ref([]); const loading = ref(false); const submitting = ref(false); const form = ref({ schedule_id: "", patient_id: null, phase: 0, checklist: "", instrument_count: "", specimen: "", wound_condition: "" });
const load = async () => { loading.value = true; try { const res = await getSurgeryNursingRecordList(); records.value = res.data || []; } catch (error) { ElMessage.error(error?.msg || "手术护理记录加载失败"); } finally { loading.value = false; } };
const selectSchedule = (id) => { const item = schedules.value.find((entry) => entry.schedule_id === id); form.value.patient_id = item?.patient_id || null; };
const submit = async () => { if (!form.value.schedule_id || !form.value.patient_id || !form.value.checklist.trim()) { ElMessage.warning("请选择手术排台并填写核查内容"); return; } submitting.value = true; try { await createSurgeryNursingRecord(form.value); ElMessage.success("手术护理记录已保存"); form.value.checklist = ""; form.value.instrument_count = ""; form.value.specimen = ""; form.value.wound_condition = ""; await load(); } catch (error) { ElMessage.error(error?.msg || "保存失败"); } finally { submitting.value = false; } };
onMounted(async () => { const res = await getSurgeryScheduleList(); schedules.value = res.data || []; if (schedules.value[0]) { form.value.schedule_id = schedules.value[0].schedule_id; selectSchedule(form.value.schedule_id); } await load(); });
</script>
