<template>
  <div class="app-container">
    <vab-page-header title="就诊导航" description="查询科室位置、联系电话和医生信息" />
    <el-card>
      <div class="page-toolbar">
        <el-input v-model="keyword" placeholder="搜索科室名称" clearable class="page-search-input" @keyup.enter="fetchDepartments" />
        <el-button type="primary" :loading="loading" @click="fetchDepartments">查询</el-button>
      </div>
      <el-card shadow="never" class="route-card">
        <template #header><span>院内路线指引</span></template>
        <div class="route-toolbar">
          <el-select v-model="routeStart" placeholder="选择起点" clearable filterable><el-option v-for="item in departments" :key="`start-${item.department_id}`" :label="item.name" :value="item.department_id" /></el-select>
          <span class="route-arrow">→</span>
          <el-select v-model="routeEnd" placeholder="选择终点" clearable filterable><el-option v-for="item in departments" :key="`end-${item.department_id}`" :label="item.name" :value="item.department_id" /></el-select>
          <el-button type="success" @click="buildRoute">生成路线</el-button>
        </div>
        <el-alert v-if="routeResult" :title="routeResult.title" :description="routeResult.description" type="info" show-icon :closable="false" />
        <el-timeline v-if="routeResult?.steps?.length" class="route-steps">
          <el-timeline-item v-for="(step, index) in routeResult.steps" :key="`${step.from_node_id}-${step.to_node_id}`">
            {{ index + 1 }}. {{ step.instruction }}（{{ step.distance }} 米）
          </el-timeline-item>
        </el-timeline>
      </el-card>
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
    <el-card class="faq-card">
      <template #header><div class="faq-header"><span>常见问题</span><div><el-input v-model="faqKeyword" placeholder="搜索问题" clearable size="small" style="width: 200px" @keyup.enter="fetchFaq" /><el-button size="small" type="primary" @click="fetchFaq">查询</el-button></div></div></template>
      <el-collapse v-if="faqs.length" v-model="activeFaq">
        <el-collapse-item v-for="faq in faqs" :key="faq.faq_id" :name="String(faq.faq_id)" :title="faq.question"><div class="faq-answer">{{ faq.answer }}</div></el-collapse-item>
      </el-collapse>
      <el-empty v-else description="暂无常见问题" :image-size="60" />
    </el-card>
  </div>
</template>

<script setup>
import { onMounted, ref } from "vue";
import { ElMessage } from "element-plus";
import { getNavigationDepartments, getNavigationFaq, getNavigationRoute } from "@/api/triage";

const keyword = ref("");
const departments = ref([]);
const loading = ref(false);
const faqKeyword = ref("");
const faqs = ref([]);
const activeFaq = ref("");
const routeStart = ref(null);
const routeEnd = ref(null);
const routeResult = ref(null);

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
const buildRoute = async () => {
  if (!routeStart.value || !routeEnd.value) return ElMessage.warning("请选择起点和终点");
  if (routeStart.value === routeEnd.value) return ElMessage.warning("起点和终点不能相同");
  const start = departments.value.find(item => item.department_id === routeStart.value);
  const end = departments.value.find(item => item.department_id === routeEnd.value);
  try {
    const res = await getNavigationRoute(routeStart.value, routeEnd.value);
    routeResult.value = {
      title: `${start.name} → ${end.name}`,
      description: `最短路线约 ${res.data.total_distance} 米，请按以下步骤行走。`,
      steps: res.data.steps || [],
    };
  } catch (error) {
    routeResult.value = {
      title: `${start.name} → ${end.name}`,
      description: "该院区尚未配置完整路线图，请根据现场指示牌确认楼栋和楼层，或联系导诊台。",
      steps: [],
    };
  }
};
const fetchFaq = async () => {
  try {
    const res = await getNavigationFaq(faqKeyword.value.trim());
    faqs.value = res.data || [];
  } catch (error) {
    ElMessage.error(error?.msg || "常见问题加载失败");
  }
};
onMounted(fetchFaq);
</script>

<style scoped>
.department-title { font-size: 18px; font-weight: 600; }
.department-card p { color: #606266; margin: 10px 0; }
.doctor-list { display: flex; flex-wrap: wrap; gap: 8px; }
.faq-card { margin-top: 16px; }
.faq-header { display: flex; align-items: center; justify-content: space-between; }
.faq-answer { color: #606266; line-height: 1.8; white-space: pre-wrap; }
.route-card { margin-bottom: 16px; }.route-toolbar { display: flex; align-items: center; gap: 10px; }.route-toolbar .el-select { width: 220px; }.route-arrow { color: #909399; font-size: 20px; }.route-steps { margin: 16px 8px 0; }
</style>
