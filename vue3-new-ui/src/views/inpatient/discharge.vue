<template>
  <div class="app-container">
    <vab-page-header title="出院结算" description="办理患者出院、查看出院记录和费用汇总" />
    <el-row :gutter="20">
      <el-col :span="8">
        <el-card>
          <template #header>
            <div style="display: flex; justify-content: space-between; align-items: center;">
              <span>在院患者</span>
              <el-input v-model="patientKeyword" placeholder="搜索" clearable size="small" style="width: 120px;" />
            </div>
          </template>
          <el-table :data="filteredInpatients" size="small" highlight-current-row @current-change="onPatientSelect" empty-text="暂无在院患者">
            <el-table-column prop="bed_no" label="床号" width="60" />
            <el-table-column prop="patient_name" label="姓名" width="80" />
            <el-table-column prop="admission_diagnosis" label="诊断" show-overflow-tooltip />
            <el-table-column prop="days" label="天数" width="60" />
          </el-table>
        </el-card>
      </el-col>
      <el-col :span="16">
        <el-card v-if="currentPatient">
          <template #header>
            <div style="display: flex; justify-content: space-between; align-items: center;">
              <span>{{ currentPatient.patient_name }} - 出院信息</span>
              <el-button type="danger" @click="openDischargeDialog">办理出院</el-button>
            </div>
          </template>
          <el-row :gutter="20" style="margin-bottom: 20px;">
            <el-col :span="6"><el-statistic title="住院天数" :value="currentPatient.days" /></el-col>
            <el-col :span="6"><el-statistic title="总费用" :value="dailyBill.total_amount" prefix="¥" /></el-col>
            <el-col :span="6"><el-statistic title="押金" :value="dailyBill.deposit_amount" prefix="¥" /></el-col>
            <el-col :span="6"><el-statistic title="应退/补" :value="dailyBill.refund" prefix="¥" /></el-col>
          </el-row>
          <el-descriptions :column="2" border size="small">
            <el-descriptions-item label="住院号">{{ currentPatient.admission_no }}</el-descriptions-item>
            <el-descriptions-item label="入院时间">{{ currentPatient.admission_time }}</el-descriptions-item>
            <el-descriptions-item label="主管医生">{{ currentPatient.doctor_name }}</el-descriptions-item>
            <el-descriptions-item label="科室">{{ currentPatient.department_name }}</el-descriptions-item>
            <el-descriptions-item label="病区">{{ currentPatient.ward_name }}</el-descriptions-item>
            <el-descriptions-item label="床位">{{ currentPatient.bed_no }}</el-descriptions-item>
            <el-descriptions-item label="入院诊断" :span="2">{{ currentPatient.admission_diagnosis || '-' }}</el-descriptions-item>
          </el-descriptions>
        </el-card>
        <el-card v-else style="text-align: center; padding: 60px; color: #999;">
          <div>请从左侧选择一个在院患者</div>
        </el-card>
      </el-col>
    </el-row>

    <!-- 出院对话框 -->
    <el-dialog v-model="dischargeDialogVisible" title="办理出院" width="500px">
      <el-form :model="dischargeForm" label-width="100px">
        <el-form-item label="患者">{{ currentPatient?.patient_name }}</el-form-item>
        <el-form-item label="出院诊断">
          <el-input v-model="dischargeForm.discharge_diagnosis" type="textarea" :rows="2" />
        </el-form-item>
        <el-form-item label="诊疗经过">
          <el-input v-model="dischargeForm.treatment_summary" type="textarea" :rows="3" />
        </el-form-item>
        <el-form-item label="出院情况">
          <el-radio-group v-model="dischargeForm.discharge_status">
            <el-radio-button :label="0">治愈</el-radio-button>
            <el-radio-button :label="1">好转</el-radio-button>
            <el-radio-button :label="2">未愈</el-radio-button>
            <el-radio-button :label="3">死亡</el-radio-button>
            <el-radio-button :label="4">转院</el-radio-button>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="出院医嘱">
          <el-input v-model="dischargeForm.discharge_instruction" type="textarea" :rows="2" />
        </el-form-item>
        <el-form-item label="随访计划">
          <el-input v-model="dischargeForm.follow_up_plan" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dischargeDialogVisible = false">取消</el-button>
        <el-button type="danger" @click="submitDischarge">确认出院</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from "vue";
import { ElMessage, ElMessageBox } from "element-plus";
import { getInpatientList } from "@/api/admission";
import { getDailyBill } from "@/api/inpatientCharge";
import { doDischarge as apiDoDischarge } from "@/api/discharge";

const inpatients = ref([]);
const patientKeyword = ref("");
const currentPatient = ref(null);
const dailyBill = ref({ total_amount: 0, deposit_amount: 0, refund: 0 });
const dischargeDialogVisible = ref(false);
const dischargeForm = ref({ discharge_status: 0 });

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
  const res = await getDailyBill({ admission_id: row.admission_id });
  const d = res.data || { total_amount: 0, deposit_amount: 0 };
  dailyBill.value = { ...d, refund: d.deposit_amount - d.total_amount };
};

const openDischargeDialog = () => {
  dischargeForm.value = { discharge_diagnosis: currentPatient.value.admission_diagnosis, discharge_status: 0 };
  dischargeDialogVisible.value = true;
};

const submitDischarge = async () => {
  try {
    await ElMessageBox.confirm(`确定为患者 ${currentPatient.value.patient_name} 办理出院？`, "提示", { type: "warning" });
    const res = await apiDoDischarge({ admission_id: currentPatient.value.admission_id, ...dischargeForm.value });
    ElMessage.success(`出院成功，总费用：¥${res.data?.total_amount || 0}，应退：¥${res.data?.refund_amount || 0}`);
    dischargeDialogVisible.value = false;
    currentPatient.value = null;
    dailyBill.value = { total_amount: 0, deposit_amount: 0, refund: 0 };
    loadInpatients();
  } catch (e) {
    if (e !== "cancel") ElMessage.error(e.msg || "操作失败");
  }
};

onMounted(() => {
  loadInpatients();
});
</script>
