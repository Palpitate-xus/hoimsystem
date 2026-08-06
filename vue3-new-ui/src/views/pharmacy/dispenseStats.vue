<template>
  <div class="app-container">
    <vab-page-header title="发药统计" description="按处方创建日期统计已发药和已退药处方" />
    <el-card>
      <div class="page-toolbar">
        <el-date-picker v-model="dateRange" type="daterange" value-format="YYYY-MM-DD" start-placeholder="开始日期" end-placeholder="结束日期" />
        <el-button type="primary" :loading="loading" @click="fetchStats">查询</el-button>
      </div>
      <el-row :gutter="16" style="margin-bottom: 18px;">
        <el-col :xs="24" :sm="12"><el-statistic title="发药处方数" :value="summary.prescription_count" /></el-col>
        <el-col :xs="24" :sm="12"><el-statistic title="发药总数量" :value="summary.item_count" /></el-col>
      </el-row>
      <el-row :gutter="16">
        <el-col :xs="24" :lg="12">
          <el-card shadow="never"><template #header>按药品汇总</template><el-table :data="byDrug" border empty-text="暂无数据"><el-table-column prop="name" label="药品" /><el-table-column prop="quantity" label="数量" /><el-table-column prop="prescription_count" label="涉及处方数" /></el-table></el-card>
        </el-col>
        <el-col :xs="24" :lg="12">
          <el-card shadow="never"><template #header>按日期汇总</template><el-table :data="byDate" border empty-text="暂无数据"><el-table-column prop="date" label="日期" /><el-table-column prop="prescription_count" label="处方数" /><el-table-column prop="item_count" label="药品数量" /></el-table></el-card>
        </el-col>
      </el-row>
    </el-card>
  </div>
</template>

<script setup>
import { onMounted, ref } from "vue";
import { ElMessage } from "element-plus";
import { getDispenseStats } from "@/api/pharmacy";

const dateRange = ref([]);
const loading = ref(false);
const summary = ref({ prescription_count: 0, item_count: 0 });
const byDrug = ref([]);
const byDate = ref([]);

const fetchStats = async () => {
  loading.value = true;
  try {
    const params = {};
    if (dateRange.value?.length === 2) { params.start_date = dateRange.value[0]; params.end_date = dateRange.value[1]; }
    const res = await getDispenseStats(params);
    summary.value = res.data?.summary || { prescription_count: 0, item_count: 0 };
    byDrug.value = res.data?.by_drug || [];
    byDate.value = res.data?.by_date || [];
  } catch (error) {
    ElMessage.error(error?.msg || "发药统计加载失败");
  } finally { loading.value = false; }
};

onMounted(fetchStats);
</script>
