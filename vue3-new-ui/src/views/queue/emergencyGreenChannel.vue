<template>
  <div class="app-container">
    <vab-page-header title="绿色通道" description="对急危重症患者记录先救治后付费申请、审批和关闭过程" />
    <el-card v-if="canApply">
      <el-form :model="form" inline @submit.prevent>
        <el-form-item label="急诊患者"><el-select v-model="form.triage_id" filterable placeholder="选择绿色通道分诊记录" style="width: 240px"><el-option v-for="item in triages" :key="item.triage_id" :label="`${item.patient_name}（${item.triage_level_text}）`" :value="item.triage_id" /></el-select></el-form-item>
        <el-form-item label="申请理由"><el-input v-model="form.reason" maxlength="500" placeholder="说明先救治后付费的临床理由" style="width: 420px" /></el-form-item>
        <el-form-item><el-button type="primary" :loading="submitting" @click="submit">提交绿色通道申请</el-button><el-button @click="load">刷新</el-button></el-form-item>
      </el-form>
    </el-card>
    <el-card v-else><el-button @click="load">刷新</el-button></el-card>
    <el-card>
      <el-table :data="records" v-loading="loading" border empty-text="暂无绿色通道申请">
        <el-table-column prop="patient_name" label="患者" width="110" />
        <el-table-column prop="reason" label="申请理由" min-width="300" show-overflow-tooltip />
        <el-table-column prop="applicant_name" label="申请人" width="110" />
        <el-table-column prop="approver_name" label="审批人" width="110" />
        <el-table-column prop="create_time" label="申请时间" width="175" />
        <el-table-column label="状态" width="100"><template #default="{ row }"><el-tag :type="statusType(row.status)">{{ row.status_text }}</el-tag></template></el-table-column>
        <el-table-column label="操作" width="150"><template #default="{ row }"><el-button v-if="canApprove && row.status === 0" size="small" type="success" @click="approve(row)">批准</el-button><el-button v-if="canClose && row.status === 1" size="small" @click="close(row)">关闭通道</el-button></template></el-table-column>
      </el-table>
    </el-card>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from "vue";
import { useStore } from "vuex";
import { ElMessage } from "element-plus";
import { approveEmergencyGreenChannel, closeEmergencyGreenChannel, createEmergencyGreenChannel, getEmergencyGreenChannelList, getEmergencyTriageList } from "@/api/emergency";

const store = useStore(); const permissions = computed(() => store.state.user.permissions || []); const canApply = computed(() => permissions.value.some((role) => ["admin", "super_admin", "director", "doctor", "nurse"].includes(role))); const canApprove = computed(() => permissions.value.some((role) => ["admin", "super_admin", "director"].includes(role))); const canClose = computed(() => permissions.value.some((role) => ["admin", "super_admin", "director", "doctor", "nurse"].includes(role)));
const triages = ref([]); const records = ref([]); const loading = ref(false); const submitting = ref(false); const form = ref({ triage_id: "", reason: "" });
const statusType = (status) => ({ 0: "warning", 1: "danger", 2: "success", 3: "info" }[status] || "info");
const load = async () => { loading.value = true; try { const res = await getEmergencyGreenChannelList(); records.value = res.data || []; } catch (error) { ElMessage.error(error?.msg || "绿色通道加载失败"); } finally { loading.value = false; } };
const loadTriages = async () => { const res = await getEmergencyTriageList(); triages.value = (res.data || []).filter((item) => item.green_channel && item.status !== 3); if (!form.value.triage_id && triages.value[0]) form.value.triage_id = triages.value[0].triage_id; };
const submit = async () => { if (!form.value.triage_id || !form.value.reason.trim()) { ElMessage.warning("请选择患者并填写申请理由"); return; } submitting.value = true; try { await createEmergencyGreenChannel(form.value); ElMessage.success("绿色通道申请已提交"); form.value.reason = ""; await load(); } catch (error) { ElMessage.error(error?.msg || "提交失败"); } finally { submitting.value = false; } };
const approve = async (row) => { try { await approveEmergencyGreenChannel({ channel_id: row.channel_id }); ElMessage.success("绿色通道已批准"); await load(); } catch (error) { ElMessage.error(error?.msg || "审批失败"); } };
const close = async (row) => { try { await closeEmergencyGreenChannel({ channel_id: row.channel_id, note: "救治及费用流程已完成" }); ElMessage.success("绿色通道已关闭"); await load(); } catch (error) { ElMessage.error(error?.msg || "关闭失败"); } };
onMounted(async () => { await Promise.all([load(), loadTriages()]); });
</script>
