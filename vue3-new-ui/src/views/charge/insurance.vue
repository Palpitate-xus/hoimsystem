<template>
  <div class="app-container">
    <vab-page-header title="医保与费用控制" description="医保目录、结算、慢病登记、DRG/DIP 分析和费用预警" />
    <el-tabs v-model="activeTab">
      <el-tab-pane label="医保目录" name="catalog"><el-table :data="catalog" border empty-text="暂无目录"><el-table-column prop="code" label="医保编码" /><el-table-column prop="name" label="项目名称" /><el-table-column prop="category" label="类别" /><el-table-column prop="reimbursement_ratio" label="报销比例" /></el-table></el-tab-pane>
      <el-tab-pane label="结算记录" name="settlement"><el-table :data="settlements" border empty-text="暂无结算记录"><el-table-column prop="patient_name" label="患者" /><el-table-column prop="insurance_no" label="医保号" /><el-table-column prop="total_amount" label="总金额" /><el-table-column prop="covered_amount" label="报销金额" /><el-table-column prop="self_amount" label="自付金额" /><el-table-column prop="status_text" label="状态" /></el-table></el-tab-pane>
      <el-tab-pane label="慢病登记" name="chronic"><el-table :data="chronic" border empty-text="暂无登记"><el-table-column prop="patient_name" label="患者" /><el-table-column prop="disease_name" label="慢病" /><el-table-column prop="card_no" label="卡号" /><el-table-column prop="limit_amount" label="年度限额" /></el-table></el-tab-pane>
      <el-tab-pane label="DRG/DIP 分析" name="drg"><el-descriptions v-if="drg" :column="4" border><el-descriptions-item label="病例数">{{ drg.case_count }}</el-descriptions-item><el-descriptions-item label="预计金额">{{ drg.expected_amount }}</el-descriptions-item><el-descriptions-item label="实际金额">{{ drg.actual_amount }}</el-descriptions-item><el-descriptions-item label="盈亏">{{ drg.profit }}</el-descriptions-item></el-descriptions><el-table :data="warnings" border style="margin-top:16px" empty-text="暂无费用预警"><el-table-column prop="patient_name" label="患者" /><el-table-column prop="group_code" label="分组" /><el-table-column prop="actual_amount" label="实际费用" /><el-table-column prop="over_amount" label="超出金额" /></el-table></el-tab-pane>
    </el-tabs>
  </div>
</template>

<script setup>
import { onMounted, ref } from "vue";
import { ElMessage } from "element-plus";
import { getChronicRegistrations, getDrgAnalysis, getInsuranceCatalog, getInsuranceSettlements, getInsuranceWarnings } from "@/api/insurance";

const activeTab = ref("catalog"); const catalog = ref([]); const settlements = ref([]); const chronic = ref([]); const drg = ref(null); const warnings = ref([]);
const load = async () => { try { const [a, b, c, d, e] = await Promise.all([getInsuranceCatalog(), getInsuranceSettlements(), getChronicRegistrations(), getDrgAnalysis(), getInsuranceWarnings()]); catalog.value = a.data || []; settlements.value = b.data || []; chronic.value = c.data || []; drg.value = d.data || null; warnings.value = e.data || []; } catch (error) { ElMessage.error(error.msg || "获取医保数据失败"); } };
onMounted(load);
</script>
