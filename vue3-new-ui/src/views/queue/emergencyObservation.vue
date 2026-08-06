<template>
  <div class="app-container">
    <vab-page-header title="留观管理" description="登记急诊留观患者、记录病情和医嘱，并在结束时补齐费用状态" />
    <el-card>
      <el-form :model="form" inline @submit.prevent>
        <el-form-item label="急诊患者"><el-select v-model="form.triage_id" filterable placeholder="选择分诊记录" style="width: 220px"><el-option v-for="item in triages" :key="item.triage_id" :label="`${item.patient_name}（${item.triage_level_text}）`" :value="item.triage_id" /></el-select></el-form-item>
        <el-form-item label="当前病情"><el-input v-model="form.condition" maxlength="500" placeholder="生命体征、症状变化和观察重点" style="width: 320px" /></el-form-item>
        <el-form-item label="留观医嘱"><el-input v-model="form.medical_advice" maxlength="500" placeholder="观察频次、用药和复评要求" style="width: 280px" /></el-form-item>
        <el-form-item label="费用"><el-input-number v-model="form.fee_amount" :min="0" :precision="2" :step="10" controls-position="right" /></el-form-item>
        <el-form-item><el-button type="primary" :loading="submitting" @click="submit">登记留观</el-button><el-button @click="load">刷新</el-button></el-form-item>
      </el-form>
    </el-card>
    <el-card>
      <el-table :data="records" v-loading="loading" border empty-text="暂无留观记录">
        <el-table-column prop="patient_name" label="患者" width="110" />
        <el-table-column prop="start_time" label="开始时间" width="175" />
        <el-table-column prop="end_time" label="结束时间" width="175" />
        <el-table-column prop="condition" label="当前病情" min-width="220" show-overflow-tooltip />
        <el-table-column prop="medical_advice" label="留观医嘱" min-width="200" show-overflow-tooltip />
        <el-table-column label="费用" width="120"><template #default="{ row }">¥{{ Number(row.fee_amount || 0).toFixed(2) }} <el-tag size="small" :type="row.fee_status ? 'success' : 'warning'">{{ row.fee_status_text }}</el-tag></template></el-table-column>
        <el-table-column label="状态" width="100"><template #default="{ row }"><el-tag :type="statusType(row.status)">{{ row.status_text }}</el-tag></template></el-table-column>
        <el-table-column label="操作" width="180"><template #default="{ row }"><el-button v-if="row.status === 1" size="small" type="primary" @click="finish(row)">结束留观</el-button><el-button v-if="row.status === 1 && !row.fee_status" size="small" @click="markFee(row)">标记已计费</el-button></template></el-table-column>
      </el-table>
    </el-card>
  </div>
</template>

<script setup>
import { onMounted, ref } from "vue";
import { ElMessage } from "element-plus";
import { createEmergencyObservation, getEmergencyObservationList, getEmergencyTriageList, updateEmergencyObservation } from "@/api/emergency";

const triages = ref([]); const records = ref([]); const loading = ref(false); const submitting = ref(false);
const form = ref({ triage_id: "", condition: "", medical_advice: "", fee_amount: 0 });
const statusType = (status) => ({ 1: "warning", 2: "success", 3: "info" }[status] || "info");
const load = async () => { loading.value = true; try { const res = await getEmergencyObservationList(); records.value = res.data || []; } catch (error) { ElMessage.error(error?.msg || "留观记录加载失败"); } finally { loading.value = false; } };
const loadTriages = async () => { const res = await getEmergencyTriageList(); triages.value = (res.data || []).filter((item) => item.status !== 3); if (!form.value.triage_id && triages.value[0]) form.value.triage_id = triages.value[0].triage_id; };
const submit = async () => { if (!form.value.triage_id || !form.value.condition.trim()) { ElMessage.warning("请选择患者并填写当前病情"); return; } submitting.value = true; try { await createEmergencyObservation(form.value); ElMessage.success("留观登记已完成"); form.value.condition = ""; form.value.medical_advice = ""; form.value.fee_amount = 0; await load(); } catch (error) { ElMessage.error(error?.msg || "登记失败"); } finally { submitting.value = false; } };
const finish = async (row) => { try { await updateEmergencyObservation({ observation_id: row.observation_id, status: 2 }); ElMessage.success("留观已结束"); await load(); } catch (error) { ElMessage.error(error?.msg || "结束留观失败"); } };
const markFee = async (row) => { try { await updateEmergencyObservation({ observation_id: row.observation_id, fee_status: 1 }); ElMessage.success("已标记为计费"); await load(); } catch (error) { ElMessage.error(error?.msg || "费用状态更新失败"); } };
onMounted(async () => { await Promise.all([load(), loadTriages()]); });
</script>
