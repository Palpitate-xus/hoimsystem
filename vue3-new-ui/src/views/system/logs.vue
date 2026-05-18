<template>
  <div class="app-container">
    <vab-page-header title="操作日志" description="审计系统操作日志，支持筛选和查询" />
    <el-card>
      <el-form :inline="true" :model="queryForm" class="page-toolbar">
        <el-form-item label="操作类型">
          <el-input v-model="queryForm.action" placeholder="如：登录/新增/删除" clearable />
        </el-form-item>
        <el-form-item>
          <el-button type="primary" @click="fetchList">查询</el-button>
          <el-button @click="resetSearch">重置</el-button>
        </el-form-item>
      </el-form>

      <el-table :data="list" v-loading="loading" empty-text="暂无操作日志" border>
        <el-table-column prop="user_name" label="操作用户" width="120">
          <template #default="{row}">
            <span v-if="row.user_name">{{ row.user_name }}</span>
            <span v-else style="color:#999">匿名</span>
          </template>
        </el-table-column>
        <el-table-column prop="action" label="操作" width="140">
          <template #default="{row}">
            <el-tag :type="getActionTagType(row.action)" size="small">{{ row.action }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="target" label="对象" width="140" />
        <el-table-column prop="result" label="结果" width="80">
          <template #default="{row}">
            <el-tag v-if="row.result === '成功'" type="success" size="small">成功</el-tag>
            <el-tag v-else type="danger" size="small">失败</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="ip" label="来源IP" width="140" />
        <el-table-column prop="create_time" label="操作时间" sortable />
      </el-table>
      <el-pagination
        v-model:current-page="queryForm.page"
        v-model:page-size="queryForm.page_size"
        :total="total"
        layout="total, prev, pager, next"
        class="pagination-wrapper"
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

const getActionTagType = (action) => {
  if (!action) return "info";
  if (action.includes("登录") || action.includes("注册")) return "";
  if (action.includes("新增") || action.includes("创建")) return "success";
  if (action.includes("更新") || action.includes("编辑")) return "warning";
  if (action.includes("删除") || action.includes("取消")) return "danger";
  return "info";
};

const fetchList = async () => {
  loading.value = true;
  const res = await getLogList(queryForm.value);
  list.value = res.data?.list || [];
  total.value = res.data?.total || 0;
  loading.value = false;
};

const resetSearch = () => {
  queryForm.value = { user_id: null, action: "", start_time: "", end_time: "", page: 1, page_size: 10 };
  fetchList();
};

onMounted(fetchList);
</script>
