<template>
  <div class="app-container">
    <vab-page-header title="处方查询" />
    <el-card>
      <el-table :data="paginatedList" v-loading="loading">
        <el-table-column prop="uuid" label="处方ID" />
        <el-table-column prop="doctor_name" label="医生" />
        <el-table-column prop="patient_name" label="患者" />
        <el-table-column prop="status" label="状态">
          <template #default="{row}">
            <el-tag v-if="row.status===0" type="warning">待审核</el-tag>
            <el-tag v-else-if="row.status===1" type="primary">已审核</el-tag>
            <el-tag v-else-if="row.status===2" type="success">已发药</el-tag>
            <el-tag v-else type="danger">已取消</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="create_time" label="创建时间" />
        <el-table-column label="药品明细">
          <template #default="{row}">
            <div v-for="(p, i) in row.phas" :key="i">{{ p.name }} x{{ p.number }}</div>
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
import { getPrescriptionList } from "@/api/patient";

const list = ref([]);
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
  const res = await getPrescriptionList();
  list.value = res.data || [];
  total.value = list.value.length;
  loading.value = false;
};

onMounted(fetchList);
</script>
