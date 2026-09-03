<template>
  <div class="app-container">
    <vab-page-header title="运营趋势" description="基于每日预聚合事实表展示核心业务与财务指标" />
    <el-card>
      <div class="page-toolbar">
        <el-date-picker v-model="range" type="daterange" value-format="YYYY-MM-DD" start-placeholder="开始日期" end-placeholder="结束日期" />
        <el-button type="primary" @click="load">查询</el-button>
        <el-button v-if="isAdmin" :loading="refreshing" @click="refreshToday">重新汇总今日</el-button>
      </div>
      <el-row :gutter="16" style="margin: 16px 0">
        <el-col v-for="card in cards" :key="card.label" :xs="12" :sm="8" :lg="4">
          <el-statistic :title="card.label" :value="card.value" :precision="card.precision || 0" />
        </el-col>
      </el-row>
      <el-table :data="rows" v-loading="loading" empty-text="该区间尚无汇总数据">
        <el-table-column prop="date" label="日期" width="120" fixed />
        <el-table-column prop="outpatient_visits" label="门诊" />
        <el-table-column prop="emergency_visits" label="急诊" />
        <el-table-column prop="admissions" label="入院" />
        <el-table-column prop="discharges" label="出院" />
        <el-table-column prop="active_inpatients" label="在院" />
        <el-table-column prop="prescriptions" label="处方" />
        <el-table-column prop="lab_orders" label="检验" />
        <el-table-column prop="imaging_orders" label="影像" />
        <el-table-column prop="critical_labs" label="危急值" />
        <el-table-column prop="average_queue_wait_minutes" label="平均候诊(分)" width="120" />
        <el-table-column prop="net_revenue" label="净收入" width="110" />
      </el-table>
    </el-card>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from "vue";
import { useStore } from "vuex";
import { ElMessage } from "element-plus";
import { getOperationalTrend, refreshOperationalMetric } from "@/api/operations";

const store = useStore();
const loading = ref(false);
const refreshing = ref(false);
const rows = ref([]);
const range = ref([]);
const isAdmin = computed(() => store.getters["user/permissions"].includes("admin"));
const sum = (field) => rows.value.reduce((total, row) => total + Number(row[field] || 0), 0);
const cards = computed(() => [
  { label: "门诊人次", value: sum("outpatient_visits") },
  { label: "急诊人次", value: sum("emergency_visits") },
  { label: "入院人次", value: sum("admissions") },
  { label: "处方数", value: sum("prescriptions") },
  { label: "危急值", value: sum("critical_labs") },
  { label: "净收入", value: sum("net_revenue"), precision: 2 },
]);
const load = async () => {
  loading.value = true;
  try {
    const params = range.value?.length === 2 ? { date_from: range.value[0], date_to: range.value[1] } : {};
    const response = await getOperationalTrend(params);
    rows.value = response.data || [];
  } finally {
    loading.value = false;
  }
};
const refreshToday = async () => {
  refreshing.value = true;
  try {
    await refreshOperationalMetric();
    ElMessage.success("今日指标已重新汇总");
    await load();
  } finally {
    refreshing.value = false;
  }
};
onMounted(load);
</script>
