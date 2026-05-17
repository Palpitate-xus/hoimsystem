<template>
  <div class="app-container">
    <vab-page-header title="住院费用管理" description="住院费用明细、日清单、费用结算" />
    <el-row :gutter="20">
      <el-col :span="5">
        <el-card>
          <template #header><span>在院患者</span></template>
          <el-input v-model="patientKeyword" placeholder="搜索患者" clearable size="small" style="margin-bottom: 10px;" />
          <el-table :data="filteredInpatients" size="small" highlight-current-row @current-change="onPatientSelect" empty-text="暂无在院患者">
            <el-table-column prop="bed_no" label="床号" width="60" />
            <el-table-column prop="patient_name" label="姓名" width="80" />
            <el-table-column prop="admission_diagnosis" label="诊断" show-overflow-tooltip />
          </el-table>
        </el-card>
      </el-col>
      <el-col :span="19">
        <el-card v-if="currentPatient">
          <template #header>
            <div style="display: flex; justify-content: space-between; align-items: center;">
              <span>{{ currentPatient.patient_name }} - 费用管理</span>
              <el-button type="primary" size="small" @click="loadDailyBill">刷新日清单</el-button>
            </div>
          </template>
          <el-row :gutter="20" style="margin-bottom: 20px;">
            <el-col :span="6">
              <el-statistic title="总费用" :value="dailyBill.total_amount" prefix="¥" />
            </el-col>
            <el-col :span="6">
              <el-statistic title="押金" :value="dailyBill.deposit_amount" prefix="¥" />
            </el-col>
            <el-col :span="6">
              <el-statistic title="余额" :value="dailyBill.balance" prefix="¥" />
            </el-col>
            <el-col :span="6">
              <el-statistic title="未结算" :value="dailyBill.unsettled_amount" prefix="¥" />
            </el-col>
          </el-row>
          <div class="page-toolbar">
            <el-button type="success" size="small" @click="settleAll" :disabled="dailyBill.unsettled_amount <= 0">全部结算</el-button>
          </div>
          <el-tabs>
            <el-tab-pane label="费用明细">
              <el-table :data="chargeList" size="small" v-loading="chargeLoading" empty-text="暂无费用明细">
                <el-table-column prop="item_name" label="项目名称" />
                <el-table-column prop="item_type" label="类型" width="80" />
                <el-table-column prop="quantity" label="数量" width="70" />
                <el-table-column prop="unit_price" label="单价" width="80"><template #default="{row}">¥{{ row.unit_price }}</template></el-table-column>
                <el-table-column prop="total_amount" label="金额" width="80"><template #default="{row}">¥{{ row.total_amount }}</template></el-table-column>
                <el-table-column prop="charge_date" label="日期" width="100" />
                <el-table-column label="状态" width="70">
                  <template #default="{row}">
                    <el-tag v-if="row.status===0" size="small" type="warning">{{ row.status_text }}</el-tag>
                    <el-tag v-else-if="row.status===1" size="small" type="success">{{ row.status_text }}</el-tag>
                    <el-tag v-else size="small" type="info">{{ row.status_text }}</el-tag>
                  </template>
                </el-table-column>
                <el-table-column label="操作" width="80">
                  <template #default="{row}">
                    <el-button v-if="row.status===0" size="small" type="danger" @click="refundCharge(row)">退费</el-button>
                  </template>
                </el-table-column>
              </el-table>
            </el-tab-pane>
            <el-tab-pane label="日清单">
              <el-table :data="dailyBill.daily_list" size="small" empty-text="暂无日清单">
                <el-table-column prop="charge_date" label="日期" />
                <el-table-column prop="amount" label="金额"><template #default="{row}">¥{{ row.amount }}</template></el-table-column>
              </el-table>
            </el-tab-pane>
          </el-tabs>
        </el-card>
        <el-card v-else style="text-align: center; padding: 60px; color: #999;">
          <div>请从左侧选择一个在院患者</div>
        </el-card>
      </el-col>
    </el-row>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from "vue";
import { ElMessage, ElMessageBox } from "element-plus";
import { getInpatientList } from "@/api/admission";
import { getInpatientChargeList, getDailyBill, settleCharges, refundCharge as apiRefundCharge } from "@/api/inpatientCharge";

const inpatients = ref([]);
const patientKeyword = ref("");
const currentPatient = ref(null);
const chargeList = ref([]);
const chargeLoading = ref(false);
const dailyBill = ref({ total_amount: 0, deposit_amount: 0, balance: 0, unsettled_amount: 0, daily_list: [] });

const filteredInpatients = computed(() => {
  if (!patientKeyword.value) return inpatients.value;
  const kw = patientKeyword.value.toLowerCase();
  return inpatients.value.filter(p => p.patient_name.toLowerCase().includes(kw));
});

const loadInpatients = async () => {
  const res = await getInpatientList({});
  inpatients.value = res.data || [];
};

const onPatientSelect = async (row) => {
  if (!row) return;
  currentPatient.value = row;
  await loadCharges(row.admission_id);
  await loadDailyBill(row.admission_id);
};

const loadCharges = async (admissionId) => {
  chargeLoading.value = true;
  const res = await getInpatientChargeList({ admission_id: admissionId });
  chargeList.value = res.data || [];
  chargeLoading.value = false;
};

const loadDailyBill = async (admissionId) => {
  const id = admissionId || currentPatient.value?.admission_id;
  if (!id) return;
  const res = await getDailyBill({ admission_id: id });
  dailyBill.value = res.data || { total_amount: 0, deposit_amount: 0, balance: 0, unsettled_amount: 0, daily_list: [] };
};

const settleAll = async () => {
  try {
    await ElMessageBox.confirm("确定结算所有未结算费用？", "提示", { type: "warning" });
    await settleCharges({ admission_id: currentPatient.value.admission_id });
    ElMessage.success("结算成功");
    loadCharges(currentPatient.value.admission_id);
    loadDailyBill(currentPatient.value.admission_id);
  } catch (e) {
    if (e !== "cancel") ElMessage.error(e.msg || "操作失败");
  }
};

const refundCharge = async (row) => {
  try {
    await ElMessageBox.confirm("确定退费？", "提示", { type: "warning" });
    await apiRefundCharge({ charge_id: row.charge_id });
    ElMessage.success("退费成功");
    loadCharges(currentPatient.value.admission_id);
    loadDailyBill(currentPatient.value.admission_id);
  } catch (e) {
    if (e !== "cancel") ElMessage.error(e.msg || "操作失败");
  }
};

onMounted(() => {
  loadInpatients();
});
</script>
