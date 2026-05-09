<template>
  <div class="app-container">
    <vab-page-header title="违约记录" />
    <el-form :inline="true">
      <el-form-item label="病人ID">
        <el-input v-model="searchPatientId" placeholder="输入病人ID筛选" clearable style="width:180px" />
      </el-form-item>
      <el-form-item>
        <el-button type="primary" @click="loadData">查询</el-button>
      </el-form-item>
    </el-form>

    <el-alert v-if="breachList.length > 0" :title="`共 ${breachList.length} 条违约记录`" type="warning" :closable="false" show-icon />
    <el-alert v-else title="暂无违约记录" type="success" :closable="false" show-icon />

    <el-table :data="breachList" style="margin-top:15px">
      <el-table-column prop="breach_id" label="违约ID" width="280" />
      <el-table-column prop="patient_name" label="病人姓名" />
      <el-table-column prop="patient_id" label="病人ID" />
      <el-table-column prop="breach_type" label="违约类型">
        <template #default="scope">
          <el-tag type="danger">{{ scope.row.breach_type }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="breach_time" label="违约时间" sortable />
      <el-table-column prop="registration_id" label="关联预约ID" width="280" />
    </el-table>
  </div>
</template>

<script setup>
import { ref, onMounted } from "vue";
import { getBreachList } from "@/api/checkin";
import { ElMessage } from "element-plus";

const breachList = ref([]);
const searchPatientId = ref("");

const loadData = async () => {
  try {
    const params = searchPatientId.value ? parseInt(searchPatientId.value) : null;
    const res = await getBreachList(params);
    breachList.value = res.data || [];
  } catch (e) {
    ElMessage.error(e.msg || "查询失败");
  }
};

onMounted(loadData);
</script>
