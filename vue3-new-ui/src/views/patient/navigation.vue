<template>
  <div class="app-container">
    <vab-page-header title="就诊导航" description="查询科室位置、联系电话和医生信息" />
    <el-card>
      <div class="page-toolbar">
        <el-input v-model="keyword" placeholder="搜索科室名称" clearable class="page-search-input" @keyup.enter="fetchDepartments" />
        <el-button type="primary" :loading="loading" @click="fetchDepartments">查询</el-button>
      </div>
      <el-row v-loading="loading" :gutter="16">
        <el-col v-for="department in departments" :key="department.department_id" :xs="24" :sm="12" :lg="8" style="margin-bottom: 16px;">
          <el-card shadow="hover" class="department-card">
            <template #header><span class="department-title">{{ department.name }}</span></template>
            <p><el-icon><Location /></el-icon> {{ department.location || "位置待补充" }}</p>
            <p><el-icon><Phone /></el-icon> {{ department.phone || "电话待补充" }}</p>
            <el-divider content-position="left">医生</el-divider>
            <div v-if="department.doctors?.length" class="doctor-list">
              <el-tag v-for="doctor in department.doctors" :key="doctor.doctor_id" effect="plain">
                {{ doctor.name }}{{ doctor.title ? ` · ${doctor.title}` : "" }}
              </el-tag>
            </div>
            <el-empty v-else description="暂无医生信息" :image-size="50" />
          </el-card>
        </el-col>
      </el-row>
      <el-empty v-if="!loading && !departments.length" description="暂无匹配科室" />
    </el-card>
  </div>
</template>

<script setup>
import { onMounted, ref } from "vue";
import { ElMessage } from "element-plus";
import { getNavigationDepartments } from "@/api/triage";

const keyword = ref("");
const departments = ref([]);
const loading = ref(false);

const fetchDepartments = async () => {
  loading.value = true;
  try {
    const res = await getNavigationDepartments(keyword.value.trim());
    departments.value = res.data || [];
  } catch (error) {
    ElMessage.error(error?.msg || "科室导航加载失败");
  } finally {
    loading.value = false;
  }
};

onMounted(fetchDepartments);
</script>

<style scoped>
.department-title { font-size: 18px; font-weight: 600; }
.department-card p { color: #606266; margin: 10px 0; }
.doctor-list { display: flex; flex-wrap: wrap; gap: 8px; }
</style>
