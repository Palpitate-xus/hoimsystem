<template>
  <div class="app-container">
    <vab-page-header title="操作日志" description="审计系统操作日志，支持筛选和查询" />
    <el-card>
      <el-form :inline="true" :model="queryForm" class="page-toolbar">
        <el-form-item label="用户ID">
          <el-input-number v-model="queryForm.user_id" :min="1" />
        </el-form-item>
        <el-form-item label="操作类型">
          <el-input v-model="queryForm.action" />
        </el-form-item>
        <el-form-item>
          <el-button type="primary" @click="fetchList">查询</el-button>
        </el-form-item>
      </el-form>

      <el-table :data="list" v-loading="loading" empty-text="暂无记录">
        <el-table-column prop="log_id" label="日志ID" />
        <el-table-column prop="user_name" label="用户" />
        <el-table-column prop="action" label="操作"  sortable />
        <el-table-column prop="target" label="对象"  sortable />
        <el-table-column prop="result" label="结果"  sortable />
        <el-table-column prop="ip" label="IP" />
        <el-table-column prop="create_time" label="时间"  sortable />
      </el-table>
      <el-pagination
        v-model:current-page="queryForm.page"
        v-model:page-size="queryForm.page_size"
        :total="total"
        layout="total, prev, pager, next"
        @current-change="fetchList"
      />
    </el-card>
  </div>
</template>

<script setup>
import { ref, onMounted } from "vue";
import { getLogList } from "@/api/system";

const list = ref([]);
const loading = ref(false);
const total = ref(0);
const queryForm = ref({ user_id: null, action: "", start_time: "", end_time: "", page: 1, page_size: 10 });

const fetchList = async () => {
  loading.value = true;
  const res = await getLogList(queryForm.value);
  list.value = res.data?.list || [];
  total.value = res.data?.total || 0;
  loading.value = false;
};

onMounted(fetchList);
</script>
