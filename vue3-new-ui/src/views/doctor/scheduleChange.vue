<template>
  <div class="app-container">
    <vab-page-header title="停诊/加号申请" description="医生提交排班变更申请，由科主任或管理员审批" />
    <el-card>
      <el-form :model="form" inline @submit.prevent>
        <el-form-item label="申请类型"><el-select v-model="form.request_type" style="width: 120px"><el-option label="停诊" value="stop" /><el-option label="加号" value="add" /></el-select></el-form-item>
        <el-form-item label="日期"><el-date-picker v-model="form.target_date" type="date" value-format="YYYY-MM-DD" /></el-form-item>
        <el-form-item v-if="form.request_type === 'add'" label="加号数"><el-input-number v-model="form.extra_slots" :min="1" :max="100" /></el-form-item>
        <el-form-item label="原因"><el-input v-model="form.reason" maxlength="200" placeholder="填写申请原因" style="width: 260px" /></el-form-item>
        <el-form-item><el-button type="primary" @click="submit">提交申请</el-button><el-button @click="fetchList">刷新</el-button></el-form-item>
      </el-form>
    </el-card>
    <el-card>
      <el-table :data="records" v-loading="loading" border empty-text="暂无申请记录"><el-table-column prop="doctor_name" label="医生" width="120" /><el-table-column prop="request_type_text" label="类型" width="90" /><el-table-column prop="target_date" label="申请日期" width="120" /><el-table-column prop="extra_slots" label="加号数" width="90" /><el-table-column prop="reason" label="原因" min-width="190" /><el-table-column label="状态" width="100"><template #default="{ row }"><el-tag :type="row.status === 0 ? 'warning' : row.status === 1 ? 'success' : 'info'">{{ row.status_text }}</el-tag></template></el-table-column><el-table-column prop="approver_name" label="审批人" width="110" /><el-table-column v-if="isApprover" label="操作" width="150"><template #default="{ row }"><el-button v-if="row.status === 0" type="success" size="small" @click="approve(row)">批准</el-button><el-button v-if="row.status === 0" size="small" @click="reject(row)">驳回</el-button></template></el-table-column></el-table>
    </el-card>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from "vue";
import { useStore } from "vuex";
import { ElMessage, ElMessageBox } from "element-plus";
import { approveScheduleChange, createScheduleChange, getScheduleChangeList, rejectScheduleChange } from "@/api/doctor";

const store = useStore(); const isApprover = computed(() => store.state.user.permissions.some((role) => ["admin", "super_admin", "director"].includes(role)));
const form = ref({ request_type: "stop", target_date: "", extra_slots: 0, reason: "" }); const records = ref([]); const loading = ref(false);
const fetchList = async () => { loading.value = true; try { const res = await getScheduleChangeList(); records.value = res.data || []; } catch (error) { ElMessage.error(error?.msg || "申请列表加载失败"); } finally { loading.value = false; } };
const submit = async () => { if (!form.value.target_date || !form.value.reason.trim() || (form.value.request_type === "add" && form.value.extra_slots < 1)) { ElMessage.warning("请填写日期、原因和有效加号数"); return; } try { await createScheduleChange(form.value); ElMessage.success("申请已提交"); form.value.reason = ""; await fetchList(); } catch (error) { ElMessage.error(error?.msg || "提交失败"); } };
const approve = async (row) => { try { await approveScheduleChange({ request_id: row.request_id }); ElMessage.success("申请已批准"); await fetchList(); } catch (error) { ElMessage.error(error?.msg || "审批失败"); } };
const reject = async (row) => { try { await ElMessageBox.confirm("确认驳回该排班申请？", "提示", { type: "warning" }); await rejectScheduleChange({ request_id: row.request_id }); ElMessage.success("申请已驳回"); await fetchList(); } catch (error) { if (error !== "cancel" && error !== "close") ElMessage.error(error?.msg || "操作失败"); } };
onMounted(fetchList);
</script>
