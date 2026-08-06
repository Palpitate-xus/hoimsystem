<template>
  <div class="app-container">
    <vab-page-header title="血库管理" description="用血申请、血型复核、交叉配血、发血和输血反应上报" />
    <el-tabs v-model="activeTab">
      <el-tab-pane label="用血申请" name="request"><div class="page-toolbar"><el-button type="primary" @click="requestDialog = true">新建用血申请</el-button></div><el-table :data="requests" border empty-text="暂无用血申请"><el-table-column prop="patient_name" label="患者" /><el-table-column prop="blood_type" label="血型" /><el-table-column prop="component" label="成分" /><el-table-column prop="volume" label="数量" /><el-table-column prop="status_text" label="状态" /><el-table-column prop="blood_type_verified" label="血型复核"><template #default="{ row }">{{ row.blood_type_verified ? "已复核" : "未复核" }}</template></el-table-column></el-table></el-tab-pane>
      <el-tab-pane label="输血反应" name="reaction"><el-table :data="reactions" border empty-text="暂无输血反应"><el-table-column prop="patient_name" label="患者" /><el-table-column prop="symptoms" label="症状" /><el-table-column prop="severity" label="程度" /><el-table-column prop="action_taken" label="处置措施" /><el-table-column prop="report_time" label="上报时间" /></el-table></el-tab-pane>
    </el-tabs>
    <el-dialog v-model="requestDialog" title="新建用血申请" width="520px"><el-form :model="form" label-width="100px"><el-form-item label="患者ID"><el-input v-model="form.patient_id" /></el-form-item><el-form-item label="血型"><el-select v-model="form.blood_type"><el-option v-for="item in bloodTypes" :key="item" :label="item" :value="item" /></el-select></el-form-item><el-form-item label="血液成分"><el-input v-model="form.component" placeholder="如：红细胞" /></el-form-item><el-form-item label="申请量"><el-input-number v-model="form.volume" :min="1" /></el-form-item><el-form-item label="申请理由"><el-input v-model="form.reason" type="textarea" /></el-form-item></el-form><template #footer><el-button @click="requestDialog = false">取消</el-button><el-button type="primary" @click="saveRequest">提交</el-button></template></el-dialog>
  </div>
</template>

<script setup>
import { onMounted, ref } from "vue";
import { ElMessage } from "element-plus";
import { createBloodRequest, getBloodReactions, getBloodRequests } from "@/api/blood";

const activeTab = ref("request"); const requests = ref([]); const reactions = ref([]); const requestDialog = ref(false); const bloodTypes = ["A+", "A-", "B+", "B-", "AB+", "AB-", "O+", "O-"]; const form = ref({ patient_id: "", blood_type: "A+", component: "红细胞", volume: 1, reason: "" });
const load = async () => { try { const [requestRes, reactionRes] = await Promise.all([getBloodRequests(), getBloodReactions()]); requests.value = requestRes.data || []; reactions.value = reactionRes.data || []; } catch (e) { ElMessage.error(e.msg || "获取血库数据失败"); } };
const saveRequest = async () => { try { await createBloodRequest(form.value); ElMessage.success("用血申请已提交"); requestDialog.value = false; await load(); } catch (e) { ElMessage.error(e.msg || "提交失败"); } };
onMounted(load);
</script>
