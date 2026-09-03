<template>
  <div class="app-container">
    <vab-page-header title="医保与费用控制" description="医保目录、结算、慢病登记、DRG/DIP 自动分组和费用预警" />
    <el-tabs v-model="activeTab">
      <el-tab-pane label="医保目录" name="catalog">
        <el-table :data="catalog" border empty-text="暂无目录">
          <el-table-column prop="code" label="医保编码" /><el-table-column prop="name" label="项目名称" />
          <el-table-column prop="category" label="类别" /><el-table-column prop="reimbursement_ratio" label="报销比例" />
        </el-table>
      </el-tab-pane>
      <el-tab-pane label="结算记录" name="settlement">
        <el-table :data="settlements" border empty-text="暂无结算记录">
          <el-table-column prop="patient_name" label="患者" /><el-table-column prop="insurance_no" label="医保号" />
          <el-table-column prop="total_amount" label="总金额" /><el-table-column prop="covered_amount" label="报销金额" />
          <el-table-column prop="self_amount" label="自付金额" /><el-table-column prop="status_text" label="状态" />
        </el-table>
      </el-tab-pane>
      <el-tab-pane label="慢病登记" name="chronic">
        <el-table :data="chronic" border empty-text="暂无登记">
          <el-table-column prop="patient_name" label="患者" /><el-table-column prop="disease_name" label="慢病" />
          <el-table-column prop="card_no" label="卡号" /><el-table-column prop="limit_amount" label="年度限额" />
        </el-table>
      </el-tab-pane>
      <el-tab-pane label="分组规则" name="rules">
        <div class="page-toolbar">
          <el-select v-model="ruleQuery.payment_method" clearable placeholder="支付方式" style="width: 140px" @change="loadRules">
            <el-option label="DRG" value="DRG" /><el-option label="DIP" value="DIP" />
          </el-select>
          <el-button @click="loadRules">刷新</el-button>
          <el-button v-if="canManageRules" type="primary" @click="openRule()">新增规则</el-button>
        </div>
        <el-table :data="rules" v-loading="rulesLoading" border empty-text="暂无分组规则">
          <el-table-column prop="payment_method" label="方式" width="75" /><el-table-column prop="group_code" label="组编码" width="130" />
          <el-table-column prop="group_name" label="组名称" min-width="160" /><el-table-column prop="diagnosis_prefix" label="诊断前缀" width="110" />
          <el-table-column prop="procedure_prefix" label="手术前缀" width="110" /><el-table-column prop="expected_amount" label="标准支付额" width="120" />
          <el-table-column prop="priority" label="优先级" width="80" /><el-table-column prop="version" label="版本" width="100" />
          <el-table-column label="有效期" min-width="190"><template #default="{ row }">{{ row.effective_from || "不限" }} ～ {{ row.effective_to || "不限" }}</template></el-table-column>
          <el-table-column label="状态" width="75"><template #default="{ row }"><el-tag :type="row.status === 1 ? 'success' : 'info'">{{ row.status === 1 ? "启用" : "停用" }}</el-tag></template></el-table-column>
          <el-table-column v-if="canManageRules" label="操作" width="90" fixed="right"><template #default="{ row }"><el-button link type="primary" @click="openRule(row)">编辑</el-button></template></el-table-column>
        </el-table>
        <el-pagination v-model:current-page="ruleQuery.page" v-model:page-size="ruleQuery.page_size" :total="ruleTotal" layout="total, prev, pager, next" style="margin-top: 12px" @current-change="loadRules" />
      </el-tab-pane>
      <el-tab-pane label="DRG/DIP 分析" name="drg">
        <el-descriptions v-if="drg" :column="5" border>
          <el-descriptions-item label="病例数">{{ drg.case_count }}</el-descriptions-item><el-descriptions-item label="预计金额">{{ drg.expected_amount }}</el-descriptions-item>
          <el-descriptions-item label="实际金额">{{ drg.actual_amount }}</el-descriptions-item><el-descriptions-item label="盈亏">{{ drg.profit }}</el-descriptions-item>
          <el-descriptions-item label="亏损病例">{{ drg.loss_cases }}</el-descriptions-item>
        </el-descriptions>
        <el-card shadow="never" style="margin-top: 16px">
          <template #header>病案自动分组</template>
          <el-form inline>
            <el-form-item label="病案首页ID"><el-input v-model="groupForm.home_id" placeholder="请输入已提交/归档病案首页ID" style="width: 310px" /></el-form-item>
            <el-form-item label="实际费用"><el-input-number v-model="groupForm.actual_amount" :min="0" :controls="false" /></el-form-item>
            <el-form-item><el-checkbox v-model="groupForm.force">重新分组</el-checkbox></el-form-item>
            <el-button type="primary" :loading="grouping" @click="runAutoGroup">执行自动分组</el-button>
          </el-form>
          <el-descriptions v-if="groupResult" :column="4" border>
            <el-descriptions-item label="支付方式">{{ groupResult.payment_method }}</el-descriptions-item><el-descriptions-item label="分组">{{ groupResult.group_code }} {{ groupResult.group_name }}</el-descriptions-item>
            <el-descriptions-item label="标准支付额">{{ groupResult.expected_amount }}</el-descriptions-item><el-descriptions-item label="盈亏">{{ groupResult.profit }}</el-descriptions-item>
          </el-descriptions>
        </el-card>
        <el-table :data="warnings" border style="margin-top: 16px" empty-text="暂无费用预警">
          <el-table-column prop="patient_name" label="患者" /><el-table-column prop="group_code" label="分组" />
          <el-table-column prop="actual_amount" label="实际费用" /><el-table-column prop="expected_amount" label="标准支付额" /><el-table-column prop="over_amount" label="超出金额" />
        </el-table>
      </el-tab-pane>
    </el-tabs>

    <el-dialog v-model="ruleDialog" :title="ruleForm.rule_id ? '编辑分组规则' : '新增分组规则'" width="680px">
      <el-form :model="ruleForm" label-width="100px"><el-row :gutter="16">
        <el-col :span="12"><el-form-item label="支付方式"><el-select v-model="ruleForm.payment_method" style="width: 100%"><el-option label="DRG" value="DRG" /><el-option label="DIP" value="DIP" /></el-select></el-form-item></el-col>
        <el-col :span="12"><el-form-item label="版本"><el-input v-model="ruleForm.version" /></el-form-item></el-col>
        <el-col :span="12"><el-form-item label="组编码"><el-input v-model="ruleForm.group_code" /></el-form-item></el-col>
        <el-col :span="12"><el-form-item label="组名称"><el-input v-model="ruleForm.group_name" /></el-form-item></el-col>
        <el-col :span="12"><el-form-item label="诊断前缀"><el-input v-model="ruleForm.diagnosis_prefix" placeholder="如 J15" /></el-form-item></el-col>
        <el-col :span="12"><el-form-item label="手术前缀"><el-input v-model="ruleForm.procedure_prefix" placeholder="选填" /></el-form-item></el-col>
        <el-col :span="12"><el-form-item label="标准支付额"><el-input-number v-model="ruleForm.expected_amount" :min="0" :precision="2" :controls="false" style="width: 100%" /></el-form-item></el-col>
        <el-col :span="12"><el-form-item label="优先级"><el-input-number v-model="ruleForm.priority" :min="-1000" :max="1000" style="width: 100%" /></el-form-item></el-col>
        <el-col :span="12"><el-form-item label="生效日期"><el-date-picker v-model="ruleForm.effective_from" value-format="YYYY-MM-DD" style="width: 100%" /></el-form-item></el-col>
        <el-col :span="12"><el-form-item label="失效日期"><el-date-picker v-model="ruleForm.effective_to" value-format="YYYY-MM-DD" style="width: 100%" /></el-form-item></el-col>
        <el-col :span="12"><el-form-item label="状态"><el-switch v-model="ruleForm.status" :active-value="1" :inactive-value="0" /></el-form-item></el-col>
      </el-row></el-form>
      <template #footer><el-button @click="ruleDialog = false">取消</el-button><el-button type="primary" :loading="ruleSaving" @click="submitRule">保存</el-button></template>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from "vue";
import { useStore } from "vuex";
import { ElMessage } from "element-plus";
import { autoGroupDrg, getChronicRegistrations, getDrgAnalysis, getDrgRules, getInsuranceCatalog, getInsuranceSettlements, getInsuranceWarnings, saveDrgRule } from "@/api/insurance";

const store = useStore();
const activeTab = ref("catalog");
const catalog = ref([]); const settlements = ref([]); const chronic = ref([]); const drg = ref(null); const warnings = ref([]);
const rules = ref([]); const ruleTotal = ref(0); const rulesLoading = ref(false); const ruleDialog = ref(false); const ruleSaving = ref(false);
const grouping = ref(false); const groupResult = ref(null);
const ruleQuery = reactive({ payment_method: "", page: 1, page_size: 20 });
const groupForm = reactive({ home_id: "", actual_amount: null, force: false });
const ruleForm = reactive({});
const canManageRules = computed(() => (store.getters["user/permissions"] || []).some((role) => ["admin", "super_admin", "director"].includes(role)));

function resetRule(row = null) {
  Object.keys(ruleForm).forEach((key) => delete ruleForm[key]);
  Object.assign(ruleForm, row || { payment_method: "DRG", group_code: "", group_name: "", diagnosis_prefix: "", procedure_prefix: "", expected_amount: 0, priority: 0, version: new Date().getFullYear().toString(), effective_from: null, effective_to: null, status: 1 });
}
async function loadRules() {
  rulesLoading.value = true;
  try { const response = await getDrgRules(ruleQuery); rules.value = response.data || []; ruleTotal.value = response.total || 0; }
  finally { rulesLoading.value = false; }
}
async function load() {
  try {
    const [a, b, c, d, e] = await Promise.all([getInsuranceCatalog(), getInsuranceSettlements(), getChronicRegistrations(), getDrgAnalysis(), getInsuranceWarnings()]);
    catalog.value = a.data || []; settlements.value = b.data || []; chronic.value = c.data || []; drg.value = d.data || null; warnings.value = e.data || [];
    await loadRules();
  } catch (error) { ElMessage.error(error.msg || "获取医保数据失败"); }
}
function openRule(row = null) { resetRule(row ? { ...row } : null); ruleDialog.value = true; }
async function submitRule() {
  if (![ruleForm.group_code, ruleForm.group_name, ruleForm.diagnosis_prefix, ruleForm.version].every(Boolean)) { ElMessage.warning("请完整填写组编码、组名称、诊断前缀和版本"); return; }
  ruleSaving.value = true;
  try {
    const response = await saveDrgRule({ ...ruleForm });
    if (response.code === 200) { ElMessage.success("分组规则已保存"); ruleDialog.value = false; await loadRules(); }
  } finally { ruleSaving.value = false; }
}
async function runAutoGroup() {
  if (!groupForm.home_id) { ElMessage.warning("请输入病案首页ID"); return; }
  grouping.value = true;
  try {
    const response = await autoGroupDrg({ ...groupForm });
    if (response.code === 200) { groupResult.value = response.data; ElMessage.success(response.msg || "自动分组完成"); const summary = await getDrgAnalysis(); drg.value = summary.data; }
  } finally { grouping.value = false; }
}
onMounted(load);
</script>
