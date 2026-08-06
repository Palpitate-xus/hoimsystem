<template>
  <div class="app-container">
    <vab-page-header title="排队进度" description="实时查看当前候诊序号和预计等待时间" />
    <el-alert title="预计等待时间按每位患者10分钟估算，实际情况以现场叫号为准" type="info" :closable="false" />
    <el-table :data="items" v-loading="loading" border empty-text="当前没有候诊记录" style="margin-top:16px">
      <el-table-column prop="doctor_name" label="医生" />
      <el-table-column prop="queue_number" label="我的序号" />
      <el-table-column prop="ahead_count" label="前面还有" />
      <el-table-column prop="estimated_wait_minutes" label="预计等待（分钟）" />
      <el-table-column prop="status_text" label="状态" />
    </el-table>
    <el-button style="margin-top:16px" @click="load">刷新进度</el-button>
  </div>
</template>

<script setup>
import { onMounted, ref } from "vue";
import { ElMessage } from "element-plus";
import { getQueueProgress } from "@/api/queue";

const items = ref([]); const loading = ref(false);
const load = async () => { loading.value = true; try { const response = await getQueueProgress(); items.value = response.data || []; } catch (error) { ElMessage.error(error.msg || "获取排队进度失败"); } finally { loading.value = false; } };
onMounted(load);
</script>
