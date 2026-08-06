<template>
  <div class="app-container">
    <vab-page-header title="定时任务调度" description="查看库存预警、违约统计和备份任务状态，并支持管理员手动触发。" />
    <el-card>
      <div class="page-toolbar">
        <el-button type="primary" :loading="loading" @click="loadStatus">刷新状态</el-button>
        <span class="refresh-tip">后台周期：每 {{ Math.round(status.interval_seconds / 60) }} 分钟检查一次</span>
      </div>
      <el-table :data="status.jobs" v-loading="loading" empty-text="暂无任务">
        <el-table-column prop="name" label="任务">
          <template #default="{ row }">{{ jobLabels[row.name] || row.name }}</template>
        </el-table-column>
        <el-table-column prop="last_run" label="最近执行时间" />
        <el-table-column label="最近结果" min-width="260">
          <template #default="{ row }"><span>{{ formatResult(row.last_result) }}</span></template>
        </el-table-column>
        <el-table-column label="操作" width="130">
          <template #default="{ row }">
            <el-button size="small" type="primary" :loading="running === row.name" @click="runJob(row.name)">立即执行</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>
  </div>
</template>

<script setup>
import { onMounted, ref } from "vue";
import { ElMessage } from "element-plus";
import { getSchedulerStatus, runSchedulerJob } from "@/api/scheduler";

const jobLabels = { inventory_alert: "库存预警检查", breach_statistics: "违约记录统计", backup: "数据备份" };
const loading = ref(false);
const running = ref("");
const status = ref({ interval_seconds: 3600, jobs: [] });

const loadStatus = async () => {
  loading.value = true;
  try {
    const res = await getSchedulerStatus();
    status.value = { ...status.value, ...(res.data || {}) };
  } finally { loading.value = false; }
};
const formatResult = (result) => result ? JSON.stringify(result) : "尚未执行";
const runJob = async (name) => {
  running.value = name;
  try { await runSchedulerJob(name); ElMessage.success("任务执行完成"); await loadStatus(); }
  catch (e) { ElMessage.error(e.msg || "任务执行失败"); }
  finally { running.value = ""; }
};
onMounted(loadStatus);
</script>

<style scoped>
.refresh-tip { color: #909399; margin-left: 12px; font-size: 13px; }
</style>
