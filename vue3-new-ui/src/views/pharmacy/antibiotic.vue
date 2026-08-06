<template>
  <div class="app-container">
    <vab-page-header title="抗菌药物管理" description="分级目录、越级审批和使用强度统计" />
    <el-tabs v-model="activeTab">
      <el-tab-pane label="分级目录" name="grade">
        <el-table :data="grades" v-loading="loading" border empty-text="暂无抗菌药物">
          <el-table-column prop="name" label="药品名称" />
          <el-table-column prop="level_text" label="等级" />
        </el-table>
      </el-tab-pane>
      <el-tab-pane label="越级审批" name="approval">
        <el-table :data="approvals" v-loading="loading" border empty-text="暂无审批记录">
          <el-table-column prop="drug_name" label="药品" />
          <el-table-column prop="patient_name" label="患者" />
          <el-table-column prop="reason" label="申请理由" show-overflow-tooltip />
          <el-table-column prop="status_text" label="状态" />
          <el-table-column prop="applicant_name" label="申请人" />
        </el-table>
      </el-tab-pane>
      <el-tab-pane label="使用统计" name="stats">
        <div class="page-toolbar"><el-button type="primary" @click="loadStats">刷新统计</el-button></div>
        <el-descriptions v-if="submission" :column="3" border>
          <el-descriptions-item label="抗菌药处方数">{{ submission.antibiotic_prescriptions }}</el-descriptions-item>
          <el-descriptions-item label="有检验申请数">{{ submission.with_lab_orders }}</el-descriptions-item>
          <el-descriptions-item label="送检率">{{ submission.submission_rate }}%</el-descriptions-item>
        </el-descriptions>
        <el-table :data="ddds" border style="margin-top:16px" empty-text="暂无用药数据">
          <el-table-column prop="drug_name" label="药品" />
          <el-table-column prop="total_units" label="使用数量" />
          <el-table-column prop="prescription_count" label="处方数" />
          <el-table-column prop="patient_days" label="患者数" />
        </el-table>
      </el-tab-pane>
    </el-tabs>
  </div>
</template>

<script setup>
import { onMounted, ref } from "vue";
import { ElMessage } from "element-plus";
import { getAntibioticApprovals, getAntibioticDdds, getAntibioticGrades, getAntibioticSubmissionRate } from "@/api/antibiotic";

const activeTab = ref("grade");
const loading = ref(false);
const grades = ref([]);
const approvals = ref([]);
const ddds = ref([]);
const submission = ref(null);
const loadData = async () => {
  loading.value = true;
  try {
    const [gradeRes, approvalRes] = await Promise.all([getAntibioticGrades(), getAntibioticApprovals()]);
    grades.value = gradeRes.data || [];
    approvals.value = approvalRes.data || [];
    await loadStats();
  } catch (e) { ElMessage.error(e.msg || "加载抗菌药物数据失败"); } finally { loading.value = false; }
};
const loadStats = async () => {
  const [dddsRes, submissionRes] = await Promise.all([getAntibioticDdds({}), getAntibioticSubmissionRate({})]);
  ddds.value = dddsRes.data || [];
  submission.value = submissionRes.data || null;
};
onMounted(loadData);
</script>
