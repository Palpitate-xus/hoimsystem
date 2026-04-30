<template>
  <div class="app-container">
    <vab-page-header title="收费记录查询" />
    <el-card>
      
      <el-input
        v-model="searchQuery"
        placeholder="搜索..."
        clearable
        style="width: 200px; margin-left: 10px;"
      ></el-input>
      <el-table :data="paginatedList" v-loading="loading">
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
      <el-pagination
        v-model:current-page="currentPage"
        v-model:page-size="pageSize"
        :page-sizes="[10, 20, 50, 100]"
        layout="total, sizes, prev, pager, next, jumper"
        :total="total"
        style="margin-top: 15px; justify-content: flex-end;"
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
const filteredList = computed(() => {
  if (!searchQuery.value) return list.value;
  const kw = searchQuery.value.toLowerCase();
  return list.value.filter((item) =>
    Object.values(item).some((val) =>
      String(val ?? "").toLowerCase().includes(kw)
    )
  );
});

const paginatedList = computed(() => {
  const start = (currentPage.value - 1) * pageSize.value;
  return filteredList.value.slice(start, start + pageSize.value);
});

const loading = ref(false);

const fetchList = async () => {
  loading.value = true;
  const res = await getChargeList();
  list.value = res.data || [];
  total.value = filteredList.value.length;
  loading.value = false;
};

onMounted(fetchList);
</script>
