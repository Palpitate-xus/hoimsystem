<template>
  <div class="app-container">
    <vab-page-header title="检验质控管理" description="质控品数据录入、结果判定和趋势图查看" />
    <el-row :gutter="16" style="margin-bottom: 16px"><el-col :span="8"><el-card><div class="metric-label">质控总数</div><div class="metric-value">{{ summary.total }}</div></el-card></el-col><el-col :span="8"><el-card><div class="metric-label">不通过</div><div class="metric-value danger">{{ summary.failed }}</div></el-card></el-col><el-col :span="8"><el-card><div class="metric-label">通过率</div><div class="metric-value">{{ summary.pass_rate }}%</div></el-card></el-col></el-row>
    <el-card style="margin-bottom: 16px"><template #header><span>质控趋势图</span></template><div ref="chartRef" class="qc-chart"></div></el-card>
    <el-card>
      <template #header><div class="page-toolbar"><el-input v-model="qcName" placeholder="搜索质控品" clearable size="small" style="width: 220px" @keyup.enter="loadAll" /><el-button size="small" type="primary" @click="loadAll">查询</el-button><el-button size="small" @click="openCreate">录入质控品</el-button></div></template>
      <el-table :data="records" v-loading="loading" size="small" empty-text="暂无质控记录"><el-table-column prop="qc_name" label="质控品" width="140" /><el-table-column prop="level" label="水平" width="90" /><el-table-column prop="target_value" label="靶值" width="80" /><el-table-column prop="measured_value" label="实测值" width="90" /><el-table-column prop="unit" label="单位" width="80" /><el-table-column label="结果" width="85"><template #default="{ row }"><el-tag :type="row.pass_flag ? 'success' : 'danger'" size="small">{{ row.pass_text }}</el-tag></template></el-table-column><el-table-column prop="operator_name" label="操作人" width="90" /><el-table-column prop="remark" label="备注" show-overflow-tooltip /></el-table>
    </el-card>
    <el-dialog v-model="dialogVisible" title="录入质控品" width="520px"><el-form :model="form" label-width="90px"><el-form-item label="质控品" required><el-input v-model="form.qc_name" maxlength="100" /></el-form-item><el-form-item label="水平" required><el-input v-model="form.level" maxlength="30" placeholder="低值/中值/高值" /></el-form-item><el-form-item label="靶值" required><el-input-number v-model="form.target_value" /></el-form-item><el-form-item label="实测值" required><el-input-number v-model="form.measured_value" /></el-form-item><el-form-item label="单位"><el-input v-model="form.unit" maxlength="20" /></el-form-item><el-form-item label="备注"><el-input v-model="form.remark" maxlength="300" /></el-form-item></el-form><template #footer><el-button @click="dialogVisible = false">取消</el-button><el-button type="primary" @click="save">保存</el-button></template></el-dialog>
  </div>
</template>

<script setup>
import { nextTick, onBeforeUnmount, onMounted, ref } from "vue";
import * as echarts from "@/utils/echarts";
import { ElMessage } from "element-plus";
import { getLabQcList, createLabQc, getLabQcSummary } from "@/api/labQc";

const loading = ref(false); const records = ref([]); const qcName = ref(""); const summary = ref({ total: 0, failed: 0, pass_rate: 0 }); const dialogVisible = ref(false); const form = ref({ qc_name: "", level: "", target_value: 0, measured_value: 0, unit: "", remark: "" }); const chartRef = ref(); let chart;
const renderChart = () => { if (!chartRef.value) return; if (!chart) chart = echarts.init(chartRef.value); chart.setOption({ tooltip: { trigger: "axis" }, legend: { data: ["靶值", "实测值"] }, xAxis: { type: "category", data: records.value.map((_, i) => `第${i + 1}次`) }, yAxis: { type: "value" }, series: [{ name: "靶值", type: "line", data: records.value.map(item => item.target_value) }, { name: "实测值", type: "line", data: records.value.map(item => item.measured_value) }] }); };
const loadAll = async () => { loading.value = true; try { const [list, stats] = await Promise.all([getLabQcList({ qc_name: qcName.value }), getLabQcSummary()]); records.value = list.data || []; summary.value = stats.data || summary.value; await nextTick(); renderChart(); } finally { loading.value = false; } };
const openCreate = () => { form.value = { qc_name: "", level: "", target_value: 0, measured_value: 0, unit: "", remark: "" }; dialogVisible.value = true; };
const save = async () => { if (!form.value.qc_name.trim() || !form.value.level.trim()) return ElMessage.warning("请填写质控品和水平"); await createLabQc(form.value); ElMessage.success("质控记录已保存"); dialogVisible.value = false; await loadAll(); };
onMounted(loadAll); onBeforeUnmount(() => chart?.dispose());
</script>

<style scoped>
.metric-label { color: #909399; font-size: 13px; }.metric-value { color: #303133; font-size: 24px; font-weight: 600; margin-top: 8px; }.metric-value.danger { color: #f56c6c; }.qc-chart { width: 100%; height: 280px; }
</style>
