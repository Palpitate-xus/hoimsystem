<template>
  <div class="app-container">
    <vab-page-header title="日结对账" />
    <el-card>
      <el-form :inline="true">
        <el-form-item label="日期">
          <el-date-picker v-model="date" type="date" value-format="YYYY-MM-DD" />
        </el-form-item>
        <el-form-item>
          <el-button type="primary" @click="query">查询</el-button>
        </el-form-item>
      </el-form>

      <el-descriptions v-if="result.date" :column="3" border>
        <el-descriptions-item label="日期">{{ result.date }}</el-descriptions-item>
        <el-descriptions-item label="总收入">{{ result.total_income }}</el-descriptions-item>
        <el-descriptions-item label="总退费">{{ result.total_refund }}</el-descriptions-item>
        <el-descriptions-item label="待缴费">{{ result.total_pending }}</el-descriptions-item>
        <el-descriptions-item label="缴费笔数">{{ result.count_paid }}</el-descriptions-item>
        <el-descriptions-item label="退费笔数">{{ result.count_refund }}</el-descriptions-item>
        <el-descriptions-item label="待缴笔数">{{ result.count_pending }}</el-descriptions-item>
        <el-descriptions-item label="总笔数">{{ result.record_count }}</el-descriptions-item>
      </el-descriptions>
    </el-card>
  </div>
</template>

<script setup>
import { ref, onMounted } from "vue";
import { dailySettlement } from "@/api/charge";
import { ElMessage } from "element-plus";

const date = ref("");
const result = ref({});

const query = async () => {
  try {
    const res = await dailySettlement({ date: date.value });
    result.value = res.data || {};
  } catch (e) {
    ElMessage.error(e.msg || "查询失败");
  }
};

onMounted(() => {
  date.value = new Date().toISOString().split("T")[0];
  query();
});
</script>
