<template>
  <div class="app-container">
    <vab-page-header title="健康档案" description="查看和管理个人健康档案信息" />
    <el-card>
      <el-descriptions title="基本信息" :column="2" border>
        <el-descriptions-item label="姓名">{{ profile.name }}</el-descriptions-item>
        <el-descriptions-item label="性别">{{ profile.sex }}</el-descriptions-item>
        <el-descriptions-item label="身份证号">{{ profile.identity }}</el-descriptions-item>
        <el-descriptions-item label="生日">{{ profile.birthday }}</el-descriptions-item>
        <el-descriptions-item label="手机号">{{ profile.phone }}</el-descriptions-item>
        <el-descriptions-item label="地址">{{ profile.address }}</el-descriptions-item>
        <el-descriptions-item label="过敏史">{{ profile.allergy_history }}</el-descriptions-item>
      </el-descriptions>
    </el-card>

    <el-card style="margin-top: 20px">
      <template #header>就诊记录</template>
      <div class="page-toolbar">
        <el-input
          v-model="searchQuery"
          placeholder="搜索..."
          clearable
          class="page-search-input"
        ></el-input>
        <el-button type="primary" @click="fetchVisits">搜索</el-button>
      </div>
      <el-table :data="paginatedVisits" v-loading="loading" empty-text="暂无记录">
        <el-table-column prop="visit_time" label="就诊时间"  sortable />
        <el-table-column prop="doctor_name" label="医生"  sortable />
        <el-table-column prop="department" label="科室"  sortable />
        <el-table-column prop="diagnosis" label="诊断"  sortable />
      </el-table>
      <el-pagination
        v-model:current-page="currentPage"
        v-model:page-size="pageSize"
        :page-sizes="[10, 20, 50, 100]"
        layout="total, sizes, prev, pager, next, jumper"
        :total="visits.length"
        class="pagination-wrapper"
      />

    </el-card>
  </div>
</template>

<script setup>
import { ref, onMounted, computed } from "vue";
import { getHealthProfile, getVisitRecords } from "@/api/patient";

const profile = ref({});
const visits = ref([]);
const searchQuery = ref("");
const loading = ref(false);
const currentPage = ref(1);
const pageSize = ref(10);
const total = ref(0);

const paginatedVisits = computed(() => {
  const start = (currentPage.value - 1) * pageSize.value;
  return visits.value.slice(start, start + pageSize.value);
});

const fetchVisits = async () => {
  loading.value = true;
  const v = await getVisitRecords(searchQuery.value);
  visits.value = v.data || [];
  total.value = visits.value.length;
  loading.value = false;
};

onMounted(async () => {
  const p = await getHealthProfile();
  profile.value = p.data || {};
  fetchVisits();
});
</script>
