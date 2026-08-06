<template>
  <div class="app-container">
    <vab-page-header title="交接班记录" description="记录病区重点事项，由接班护士确认后完成交接" />
    <el-card class="form-card">
      <el-form :model="form" inline @submit.prevent>
        <el-form-item label="班次"><el-select v-model="form.shift_type" style="width: 130px"><el-option label="白班" value="白班" /><el-option label="夜班" value="夜班" /><el-option label="其他" value="其他" /></el-select></el-form-item>
        <el-form-item label="交班内容"><el-input v-model="form.content" placeholder="患者重点情况、待办事项和风险提醒" maxlength="2000" show-word-limit style="width: 520px" /></el-form-item>
        <el-form-item><el-button type="primary" :loading="submitting" @click="submit">提交交班</el-button></el-form-item>
      </el-form>
    </el-card>
    <el-card>
      <div class="page-toolbar"><el-button @click="fetchList">刷新</el-button></div>
      <el-table :data="records" v-loading="loading" border empty-text="暂无交接班记录">
        <el-table-column prop="shift_type" label="班次" width="90" />
        <el-table-column prop="content" label="交班内容" min-width="350" show-overflow-tooltip />
        <el-table-column prop="handover_user_name" label="交班人" width="120" />
        <el-table-column prop="create_time" label="交班时间" width="170" />
        <el-table-column label="状态" width="100"><template #default="{ row }"><el-tag :type="row.status ? 'success' : 'warning'">{{ row.status_text }}</el-tag></template></el-table-column>
        <el-table-column prop="receiver_user_name" label="接班人" width="120" />
        <el-table-column label="操作" width="110"><template #default="{ row }"><el-button v-if="row.status === 0" size="small" type="success" @click="receive(row)">确认接班</el-button></template></el-table-column>
      </el-table>
    </el-card>
  </div>
</template>

<script setup>
import { onMounted, ref } from "vue";
import { ElMessage } from "element-plus";
import { createShiftHandover, getShiftHandoverList, receiveShiftHandover } from "@/api/nursing";

const form = ref({ shift_type: "白班", content: "" }); const records = ref([]); const loading = ref(false); const submitting = ref(false);
const fetchList = async () => { loading.value = true; try { const res = await getShiftHandoverList(); records.value = res.data || []; } catch (error) { ElMessage.error(error?.msg || "交接班记录加载失败"); } finally { loading.value = false; } };
const submit = async () => { if (!form.value.content.trim()) { ElMessage.warning("请填写交班内容"); return; } submitting.value = true; try { await createShiftHandover(form.value); ElMessage.success("交班记录已提交"); form.value.content = ""; await fetchList(); } catch (error) { ElMessage.error(error?.msg || "提交失败"); } finally { submitting.value = false; } };
const receive = async (row) => { try { await receiveShiftHandover({ handover_id: row.handover_id }); ElMessage.success("已确认接班"); await fetchList(); } catch (error) { ElMessage.error(error?.msg || "确认接班失败"); } };
onMounted(fetchList);
</script>
