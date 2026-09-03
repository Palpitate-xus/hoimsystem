<template>
  <div class="app-container">
    <vab-page-header title="集成可靠性中心" description="监控 LIS、PACS、医保与支付事件投递，处理重试和死信" />
    <el-row :gutter="16" style="margin-bottom: 16px">
      <el-col v-for="item in statusCards" :key="item.key" :span="6">
        <el-card><el-statistic :title="item.label" :value="counts[item.key] || 0" /></el-card>
      </el-col>
    </el-row>
    <el-card>
      <div class="page-toolbar">
        <el-select v-model="filters.destination" clearable placeholder="目标系统" style="width: 150px">
          <el-option v-for="name in ['lis', 'pacs', 'insurance', 'payment']" :key="name" :label="name.toUpperCase()" :value="name" />
        </el-select>
        <el-select v-model="filters.status" clearable placeholder="状态" style="width: 150px">
          <el-option label="待发送" value="pending" /><el-option label="重试中" value="retry" />
          <el-option label="已送达" value="delivered" /><el-option label="死信" value="dead" />
        </el-select>
        <el-button type="primary" @click="load">查询</el-button>
      </div>
      <el-table :data="rows" v-loading="loading" empty-text="暂无对接事件">
        <el-table-column prop="created_at" label="创建时间" width="180" />
        <el-table-column prop="destination" label="目标" width="100" />
        <el-table-column prop="event_type" label="事件" min-width="180" />
        <el-table-column prop="aggregate_id" label="业务标识" min-width="190" show-overflow-tooltip />
        <el-table-column prop="status" label="状态" width="100">
          <template #default="{ row }"><el-tag :type="tagType(row.status)">{{ row.status }}</el-tag></template>
        </el-table-column>
        <el-table-column prop="attempts" label="尝试" width="70" />
        <el-table-column prop="last_http_status" label="HTTP" width="75" />
        <el-table-column prop="last_error" label="最近错误" min-width="220" show-overflow-tooltip />
        <el-table-column label="操作" width="100">
          <template #default="{ row }">
            <el-button v-if="row.status !== 'delivered'" type="primary" link @click="retry(row)">重放</el-button>
          </template>
        </el-table-column>
      </el-table>
      <el-pagination v-model:current-page="page" :page-size="20" :total="total" @current-change="load" />
    </el-card>
  </div>
</template>

<script setup>
import { onMounted, ref } from "vue";
import { ElMessage, ElMessageBox } from "element-plus";
import { getIntegrationOutbox, getIntegrationReconciliation, retryIntegrationEvent } from "@/api/operations";

const rows = ref([]);
const total = ref(0);
const page = ref(1);
const loading = ref(false);
const filters = ref({ destination: "", status: "" });
const counts = ref({});
const statusCards = [
  { key: "pending", label: "待发送" }, { key: "retry", label: "重试中" },
  { key: "delivered", label: "已送达" }, { key: "dead", label: "死信" },
];
const tagType = (status) => ({ delivered: "success", dead: "danger", retry: "warning", pending: "info" }[status]);
const load = async () => {
  loading.value = true;
  try {
    const params = { page: page.value, page_size: 20 };
    if (filters.value.destination) params.destination = filters.value.destination;
    if (filters.value.status) params.status = filters.value.status;
    const [list, reconciliation] = await Promise.all([getIntegrationOutbox(params), getIntegrationReconciliation()]);
    rows.value = list.data || [];
    total.value = list.total || 0;
    counts.value = reconciliation.data?.counts || {};
  } finally {
    loading.value = false;
  }
};
const retry = async (row) => {
  await ElMessageBox.confirm(`确认重放事件 ${row.event_type}？外部系统应按事件 ID 幂等处理。`, "重放确认", { type: "warning" });
  await retryIntegrationEvent(row.event_id);
  ElMessage.success("事件已进入重试队列");
  await load();
};
onMounted(load);
</script>
