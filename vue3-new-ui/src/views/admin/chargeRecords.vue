<template>
  <div class="app-container">
    <vab-page-header title="收费记录查询" description="查询全院收费记录和退费明细" />
    <el-card>
      <div class="page-toolbar">
        <el-input
          v-model="searchQuery"
          placeholder="搜索..."
          clearable
          class="page-search-input"
        ></el-input>
        <el-button type="primary" @click="fetchList">搜索</el-button>
      </div>
      <el-table :data="paginatedList" v-loading="loading">
        <el-table-column prop="id" label="ID"  sortable />
        <el-table-column prop="charge_time" label="创建时间"  sortable />
        <el-table-column prop="time" label="缴费时间"  sortable />
        <el-table-column prop="pre_id" label="处方ID" />
        <el-table-column prop="amount" label="金额"  sortable />
        <el-table-column prop="status" label="状态">
          <template #default="{row}">
            <el-tag v-if="row.status===0" type="warning">未缴费</el-tag>
            <el-tag v-else-if="row.status===1" type="success">已缴费</el-tag>
            <el-tag v-else type="danger">已退费</el-tag>
          </template>
        </el-table-column>
      </el-table>
      <el-pagination
        v-model:current-page="currentPage"
        v-model:page-size="pageSize"
        :page-sizes="[10, 20, 50, 100]"
        layout="total, sizes, prev, pager, next, jumper"
        :total="total"
        class="pagination-wrapper"
      />

    </el-card>
  </div>
</template>

<script setup>
import { ref, onMounted, computed } from "vue";
import { getChargeList } from "@/api/charge";

const list = ref([]);
const searchQuery = ref("");
const currentPage = ref(1);
const pageSize = ref(10);
const total = ref(0);
const paginatedList = computed(() => {
  const start = (currentPage.value - 1) * pageSize.value;
  return list.value.slice(start, start + pageSize.value);
});

const loading = ref(false);

const fetchList = async () => {
  loading.value = true;
  const res = await getChargeList(searchQuery.value);
  list.value = res.data || [];
  total.value = list.value.length;
  loading.value = false;
};

onMounted(fetchList);
</script>
