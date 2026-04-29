<template>
  <div class="app-container">
    <vab-page-header title="候诊队列" />
    <el-card>
      <el-table :data="list" v-loading="loading">
        <el-table-column prop="queue_id" label="队列ID" />
        <el-table-column prop="queue_number" label="排队序号" />
        <el-table-column prop="patient_name" label="患者" />
        <el-table-column prop="doctor_name" label="医生" />
        <el-table-column prop="type" label="类型">
          <template #default="{row}">
            <el-tag v-if="row.type===0">现场挂号</el-tag>
            <el-tag v-else type="success">预约</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="status" label="状态">
          <template #default="{row}">
            <el-tag v-if="row.status===0" type="warning">候诊</el-tag>
            <el-tag v-else-if="row.status===1" type="primary">叫号中</el-tag>
            <el-tag v-else-if="row.status===2" type="danger">已过号</el-tag>
            <el-tag v-else type="success">已就诊</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="200">
          <template #default="{row}">
            <el-button size="small" type="primary" @click="callNext(row)">叫号</el-button>
            <el-button size="small" @click="pass(row)">过号</el-button>
            <el-button size="small" @click="skip(row)">跳过</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>
  </div>
</template>

<script setup>
import { ref, onMounted } from "vue";
import { ElMessage } from "element-plus";
import { getQueueList, callNext, passQueue, skipQueue } from "@/api/queue";

const list = ref([]);
const loading = ref(false);

const fetchList = async () => {
  loading.value = true;
  const res = await getQueueList();
  list.value = res.data || [];
  loading.value = false;
};

const callN = async (row) => {
  try {
    await callNext({ doctor_id: row.doctor_id || 1 });
    ElMessage.success("叫号成功");
    fetchList();
  } catch (e) {
    ElMessage.error(e.msg || "叫号失败");
  }
};

const pass = async (row) => {
  try {
    await passQueue({ queue_id: row.queue_id });
    ElMessage.success("操作成功");
    fetchList();
  } catch (e) {
    ElMessage.error(e.msg || "操作失败");
  }
};

const skip = async (row) => {
  try {
    await skipQueue({ queue_id: row.queue_id });
    ElMessage.success("操作成功");
    fetchList();
  } catch (e) {
    ElMessage.error(e.msg || "操作失败");
  }
};

onMounted(fetchList);
</script>
