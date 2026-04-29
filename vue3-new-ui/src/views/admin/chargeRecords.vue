<template>
  <div class="app-container">
    <vab-page-header title="收费记录查询" />
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
      </el-table>
    </el-card>
  </div>
</template>

<script setup>
import { ref, onMounted } from "vue";
import { getChargeList } from "@/api/charge";

const list = ref([]);
const loading = ref(false);

const fetchList = async () => {
  loading.value = true;
  const res = await getChargeList();
  list.value = res.data || [];
  loading.value = false;
};

onMounted(fetchList);
</script>
