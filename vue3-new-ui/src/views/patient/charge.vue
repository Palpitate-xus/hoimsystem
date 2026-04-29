<template>
  <div class="app-container">
    <vab-page-header title="缴费管理" />
    <el-card>
      <el-table :data="list" v-loading="loading">
        <el-table-column prop="id" label="ID" />
        <el-table-column prop="charge_time" label="创建时间" />
        <el-table-column prop="time" label="缴费时间" />
        <el-table-column prop="pre_id" label="处方ID" />
        <el-table-column prop="amount" label="金额" />
        <el-table-column prop="status" label="状态">
          <template #default="{row}">
            <el-tag v-if="row.status===0" type="warning">未缴费</el-tag>
            <el-tag v-else-if="row.status===1" type="success">已缴费</el-tag>
            <el-tag v-else type="danger">已退费</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="120">
          <template #default="{row}">
            <el-button v-if="row.status===0" size="small" type="primary" @click="pay(row)">缴费</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>
  </div>
</template>

<script setup>
import { ref, onMounted } from "vue";
import { ElMessage } from "element-plus";
import { getChargeList, commitCharge } from "@/api/charge";

const list = ref([]);
const loading = ref(false);

const fetchList = async () => {
  loading.value = true;
  const res = await getChargeList();
  list.value = res.data || [];
  loading.value = false;
};

const pay = async (row) => {
  try {
    await commitCharge({ id: row.id });
    ElMessage.success("缴费成功");
    fetchList();
  } catch (e) {
    ElMessage.error(e.msg || "缴费失败");
  }
};

onMounted(fetchList);
</script>
