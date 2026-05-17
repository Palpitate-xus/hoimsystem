<template>
  <div class="app-container">
    <vab-page-header title="违约记录" description="查看患者预约挂号违约记录和处理情况" />
    <el-card>
      <el-form :inline="true" class="page-toolbar">
        <el-form-item label="患者姓名">
          <el-input v-model="searchKeyword" placeholder="输入患者姓名筛选" clearable style="width:200px" @keyup.enter="loadData" />
        </el-form-item>
        <el-form-item>
          <el-button type="primary" @click="loadData">查询</el-button>
          <el-button @click="resetSearch">重置</el-button>
        </el-form-item>
      </el-form>

      <el-alert
        v-if="breachList.length > 0"
        :title="`共 ${breachList.length} 条违约记录`"
        type="warning"
        :closable="false"
        show-icon
        style="margin-bottom: 12px;"
      />
      <el-alert
        v-else
        title="暂无违约记录"
        type="success"
        :closable="false"
        show-icon
        style="margin-bottom: 12px;"
      />

      <el-table :data="filteredList" v-loading="loading" border empty-text="暂无数据">
        <el-table-column prop="patient_name" label="患者姓名" min-width="120">
          <template #default="scope">
            <el-tag type="info" effect="plain">{{ scope.row.patient_name || "-" }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="breach_type" label="违约类型" width="130">
          <template #default="scope">
            <el-tag type="danger">{{ scope.row.breach_type }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="breach_time" label="违约时间" sortable width="180" />
        <el-table-column label="操作" width="100">
          <template #default="scope">
            <el-button size="small" link type="primary" @click="showDetail(scope.row)">详情</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <el-dialog v-model="detailVisible" title="违约记录详情" width="500px">
      <el-descriptions :column="1" border>
        <el-descriptions-item label="患者姓名">{{ currentRow.patient_name }}</el-descriptions-item>
        <el-descriptions-item label="违约类型">
          <el-tag type="danger">{{ currentRow.breach_type }}</el-tag>
        </el-descriptions-item>
        <el-descriptions-item label="违约时间">{{ currentRow.breach_time }}</el-descriptions-item>
      </el-descriptions>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, onMounted, computed } from "vue";
import { getBreachList } from "@/api/checkin";
import { ElMessage } from "element-plus";

const breachList = ref([]);
const searchKeyword = ref("");
const loading = ref(false);
const detailVisible = ref(false);
const currentRow = ref({});

const filteredList = computed(() => {
  if (!searchKeyword.value) return breachList.value;
  const kw = searchKeyword.value.toLowerCase();
  return breachList.value.filter(
    (item) =>
      (item.patient_name && item.patient_name.toLowerCase().includes(kw)) ||
      String(item.patient_id || "").includes(kw)
  );
});

const loadData = async () => {
  loading.value = true;
  try {
    const params = /^\d+$/.test(searchKeyword.value) ? parseInt(searchKeyword.value) : null;
    const res = await getBreachList(params);
    breachList.value = res.data || [];
  } catch (e) {
    ElMessage.error(e.msg || "查询失败");
  }
  loading.value = false;
};

const resetSearch = () => {
  searchKeyword.value = "";
  loadData();
};

const showDetail = (row) => {
  currentRow.value = row;
  detailVisible.value = true;
};

onMounted(loadData);
</script>
