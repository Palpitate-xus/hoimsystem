<template>
  <div class="app-container">
    <vab-page-header title="抢救记录" description="按患者记录抢救时间轴、操作和用药，形成可追溯的急救过程" />
    <el-card>
      <el-form :model="form" inline @submit.prevent>
        <el-form-item label="急诊患者"><el-select v-model="form.triage_id" filterable placeholder="选择分诊记录" style="width: 220px"><el-option v-for="item in triages" :key="item.triage_id" :label="`${item.patient_name}（${item.triage_level_text}）`" :value="item.triage_id" /></el-select></el-form-item>
        <el-form-item label="事件类型"><el-select v-model="form.event_type" style="width: 120px"><el-option label="用药" value="用药" /><el-option label="操作" value="操作" /><el-option label="病情变化" value="病情变化" /><el-option label="其他" value="其他" /></el-select></el-form-item>
        <el-form-item label="抢救描述"><el-input v-model="form.description" maxlength="500" placeholder="记录抢救操作和患者反应" style="width: 300px" /></el-form-item>
        <el-form-item label="用药"><el-input v-model="form.medication" maxlength="300" placeholder="药品、剂量、途径（可选）" style="width: 240px" /></el-form-item>
        <el-form-item><el-button type="primary" @click="submit">记录事件</el-button><el-button @click="loadEvents">刷新</el-button></el-form-item>
      </el-form>
    </el-card>
    <el-card>
      <el-table :data="events" v-loading="loading" border empty-text="暂无抢救事件"><el-table-column prop="event_time" label="时间" width="180" /><el-table-column prop="patient_name" label="患者" width="110" /><el-table-column prop="event_type" label="类型" width="100" /><el-table-column prop="description" label="抢救描述" min-width="260" /><el-table-column prop="medication" label="用药" min-width="180" /><el-table-column prop="operator_name" label="记录人" width="110" /></el-table>
    </el-card>
  </div>
</template>

<script setup>
import { onMounted, ref } from "vue";
import { ElMessage } from "element-plus";
import { getEmergencyTriageList } from "@/api/emergency";
import { createEmergencyRescueEvent, getEmergencyRescueList } from "@/api/emergency";

const triages = ref([]); const events = ref([]); const loading = ref(false); const form = ref({ triage_id: "", event_type: "用药", description: "", medication: "" });
const loadTriages = async () => { const res = await getEmergencyTriageList(); triages.value = (res.data || []).filter((item) => item.status !== 3); if (!form.value.triage_id && triages.value[0]) form.value.triage_id = triages.value[0].triage_id; };
const loadEvents = async () => { loading.value = true; try { const res = await getEmergencyRescueList(); events.value = res.data || []; } catch (error) { ElMessage.error(error?.msg || "抢救记录加载失败"); } finally { loading.value = false; } };
const submit = async () => { if (!form.value.triage_id || !form.value.description.trim()) { ElMessage.warning("请选择患者并填写抢救描述"); return; } try { await createEmergencyRescueEvent(form.value); ElMessage.success("抢救事件已记录"); form.value.description = ""; form.value.medication = ""; await loadEvents(); } catch (error) { ElMessage.error(error?.msg || "记录失败"); } };
onMounted(async () => { await loadTriages(); await loadEvents(); });
</script>
