<template>
  <div class="app-container">
    <vab-page-header title="系统监控" description="查看在线用户、接口请求量、错误率和响应性能" />
    <div class="page-toolbar"><el-button type="primary" :loading="loading" @click="loadSummary">刷新监控</el-button><span class="refresh-tip">统计窗口：{{ summary.window }}</span></div>
    <el-row :gutter="16" style="margin-bottom: 16px"><el-col :span="6"><el-card><div class="metric-label">近24小时请求</div><div class="metric-value">{{ summary.total_requests }}</div></el-card></el-col><el-col :span="6"><el-card><div class="metric-label">在线用户(15分钟)</div><div class="metric-value">{{ summary.online_users }}</div></el-card></el-col><el-col :span="6"><el-card><div class="metric-label">错误率</div><div class="metric-value danger">{{ summary.error_rate }}%</div></el-card></el-col><el-col :span="6"><el-card><div class="metric-label">平均响应</div><div class="metric-value">{{ summary.average_response_time_ms }} ms</div></el-card></el-col></el-row>
    <el-row :gutter="16"><el-col :span="12"><el-card><template #header><span>热点接口</span></template><el-table :data="summary.top_endpoints" size="small" empty-text="暂无数据"><el-table-column prop="path" label="接口" show-overflow-tooltip /><el-table-column prop="count" label="次数" width="80" /></el-table></el-card></el-col><el-col :span="12"><el-card><template #header><span>近期错误</span></template><el-table :data="summary.recent_errors" size="small" empty-text="暂无错误"><el-table-column prop="path" label="接口" show-overflow-tooltip /><el-table-column prop="status_code" label="状态码" width="80" /><el-table-column prop="username" label="用户" width="90" /></el-table></el-card></el-col></el-row>
  </div>
</template>

<script setup>
import { onMounted, ref } from "vue";
import { getMonitorSummary } from "@/api/monitor";

const loading = ref(false); const summary = ref({ window: "24h", total_requests: 0, failed_requests: 0, error_rate: 0, online_users: 0, average_response_time_ms: 0, top_endpoints: [], recent_errors: [] });
const loadSummary = async () => { loading.value = true; try { const res = await getMonitorSummary(); summary.value = { ...summary.value, ...(res.data || {}) }; } finally { loading.value = false; } };
onMounted(loadSummary);
</script>

<style scoped>
.refresh-tip { color: #909399; margin-left: 12px; font-size: 13px; }.metric-label { color: #909399; font-size: 13px; }.metric-value { color: #303133; font-size: 24px; font-weight: 600; margin-top: 8px; }.metric-value.danger { color: #f56c6c; }
</style>
