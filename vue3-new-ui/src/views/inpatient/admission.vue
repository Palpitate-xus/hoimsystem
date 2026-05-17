<template>
  <div class="app-container">
    <vab-page-header title="入院登记管理" description="办理患者入院登记、床位分配和退院" />
    <el-card>
      <template #header>
        <div class="page-toolbar">
          <el-button type="primary" @click="openAdmissionDialog()">办理入院</el-button>
          <el-input v-model="keyword" placeholder="搜索患者/住院号" clearable style="width: 200px;" />
          <el-select v-model="filterStatus" placeholder="状态" clearable style="width: 120px;">
            <el-option label="在院" :value="1" />
            <el-option label="已出院" :value="2" />
            <el-option label="待入院" :value="0" />
          </el-select>
          <el-button type="primary" @click="loadAdmissions">查询</el-button>
        </div>
      </template>
      <el-tabs v-model="activeTab">
        <el-tab-pane label="在院患者" name="inpatient">
          <el-table :data="inpatientList" size="small" v-loading="loading" empty-text="暂无记录">
            <el-table-column prop="admission_no" label="住院号" width="130" />
            <el-table-column prop="patient_name" label="患者" width="80" />
            <el-table-column prop="patient_sex" label="性别" width="50" />
            <el-table-column prop="patient_identity" label="身份证号" width="160" />
            <el-table-column prop="department_name" label="科室" width="80" />
            <el-table-column prop="ward_name" label="病区" width="100" />
            <el-table-column prop="bed_no" label="床位" width="70" />
            <el-table-column prop="doctor_name" label="主管医生" width="80" />
            <el-table-column prop="admission_diagnosis" label="入院诊断" show-overflow-tooltip />
            <el-table-column prop="admission_time" label="入院时间" width="140" />
            <el-table-column prop="days" label="住院天数" width="80">
              <template #default="{row}">
                <el-tag size="small" type="warning">{{ row.days }}天</el-tag>
              </template>
            </el-table-column>
            <el-table-column label="操作" width="200" fixed="right">
              <template #default="{row}">
                <el-button size="small" @click="showDetail(row)">详情</el-button>
                <el-button size="small" type="primary" @click="openTransferBed(row)">换床</el-button>
                <el-button size="small" type="danger" @click="doDischarge(row)">出院</el-button>
              </template>
            </el-table-column>
          </el-table>
        </el-tab-pane>
        <el-tab-pane label="全部记录" name="all">
          <el-table :data="admissionList" size="small" v-loading="loading" empty-text="暂无记录">
            <el-table-column prop="admission_no" label="住院号" width="130" />
            <el-table-column prop="patient_name" label="患者" width="80" />
            <el-table-column prop="patient_sex" label="性别" width="50" />
            <el-table-column prop="status_text" label="状态" width="70">
              <template #default="{row}">
                <el-tag v-if="row.status===1" type="success" size="small">{{ row.status_text }}</el-tag>
                <el-tag v-else-if="row.status===2" type="info" size="small">{{ row.status_text }}</el-tag>
                <el-tag v-else size="small">{{ row.status_text }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="ward_name" label="病区" width="100" />
            <el-table-column prop="bed_no" label="床位" width="70" />
            <el-table-column prop="admission_time" label="入院时间" width="140" />
            <el-table-column prop="discharge_time" label="出院时间" width="140" />
            <el-table-column label="操作" width="120" fixed="right">
              <template #default="{row}">
                <el-button size="small" @click="showDetail(row)">详情</el-button>
              </template>
            </el-table-column>
          </el-table>
        </el-tab-pane>
      </el-tabs>
    </el-card>

    <!-- 入院登记对话框 -->
    <el-dialog v-model="admissionDialogVisible" title="办理入院登记" width="600px">
      <el-form :model="admissionForm" label-width="100px">
        <el-form-item label="患者" required>
          <el-select v-model="admissionForm.patient_id" placeholder="选择患者" filterable class="form-full-width" @change="onPatientChange">
            <el-option v-for="p in patients" :key="p.patient_id" :label="p.name + ' (' + p.identity + ')'" :value="p.patient_id" />
          </el-select>
        </el-form-item>
        <el-form-item label="入院类型">
          <el-radio-group v-model="admissionForm.admission_type">
            <el-radio-button :label="0">门诊入院</el-radio-button>
            <el-radio-button :label="1">急诊入院</el-radio-button>
            <el-radio-button :label="2">转诊入院</el-radio-button>
            <el-radio-button :label="3">预约入院</el-radio-button>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="主管医生" required>
          <el-select v-model="admissionForm.doctor_id" placeholder="选择医生" class="form-full-width">
            <el-option v-for="d in doctors" :key="d.doctor_id" :label="d.name" :value="d.doctor_id" />
          </el-select>
        </el-form-item>
        <el-form-item label="科室" required>
          <el-select v-model="admissionForm.department_id" placeholder="选择科室" class="form-full-width" @change="onDeptChange">
            <el-option v-for="d in departments" :key="d.department_id" :label="d.name" :value="d.department_id" />
          </el-select>
        </el-form-item>
        <el-form-item label="病区" required>
          <el-select v-model="admissionForm.ward_id" placeholder="选择病区" class="form-full-width" @change="onWardChange">
            <el-option v-for="w in wardOptions" :key="w.ward_id" :label="w.name" :value="w.ward_id" />
          </el-select>
        </el-form-item>
        <el-form-item label="床位" required>
          <el-select v-model="admissionForm.bed_id" placeholder="选择床位" class="form-full-width">
            <el-option v-for="b in availableBeds" :key="b.bed_id" :label="b.bed_no + ' (' + b.room_no + ' ' + b.bed_type + ')'" :value="b.bed_id" />
          </el-select>
        </el-form-item>
        <el-form-item label="入院诊断">
          <el-input v-model="admissionForm.admission_diagnosis" type="textarea" :rows="2" placeholder="入院诊断" />
        </el-form-item>
        <el-form-item label="主诉">
          <el-input v-model="admissionForm.chief_complaint" type="textarea" :rows="2" placeholder="患者主诉" />
        </el-form-item>
        <el-form-item label="现病史">
          <el-input v-model="admissionForm.present_illness" type="textarea" :rows="2" placeholder="现病史" />
        </el-form-item>
        <el-form-item label="既往史">
          <el-input v-model="admissionForm.past_history" type="textarea" :rows="2" placeholder="既往史" />
        </el-form-item>
        <el-form-item label="入院押金">
          <el-input-number v-model="admissionForm.deposit_amount" :min="0" :precision="2" style="width: 100%;" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="admissionDialogVisible = false">取消</el-button>
        <el-button type="primary" @click="submitAdmission">确定</el-button>
      </template>
    </el-dialog>

    <!-- 详情对话框 -->
    <el-dialog v-model="detailDialogVisible" title="入院详情" width="700px">
      <el-descriptions :column="2" border size="small" v-if="currentDetail">
        <el-descriptions-item label="住院号">{{ currentDetail.admission_no }}</el-descriptions-item>
        <el-descriptions-item label="状态">
          <el-tag v-if="currentDetail.status===1" type="success">{{ currentDetail.status_text }}</el-tag>
          <el-tag v-else-if="currentDetail.status===2" type="info">{{ currentDetail.status_text }}</el-tag>
          <el-tag v-else>{{ currentDetail.status_text }}</el-tag>
        </el-descriptions-item>
        <el-descriptions-item label="患者">{{ currentDetail.patient_name }}</el-descriptions-item>
        <el-descriptions-item label="性别">{{ currentDetail.patient_sex }}</el-descriptions-item>
        <el-descriptions-item label="身份证号">{{ currentDetail.patient_identity }}</el-descriptions-item>
        <el-descriptions-item label="电话">{{ currentDetail.patient_phone }}</el-descriptions-item>
        <el-descriptions-item label="主管医生">{{ currentDetail.doctor_name }}</el-descriptions-item>
        <el-descriptions-item label="科室">{{ currentDetail.department_name }}</el-descriptions-item>
        <el-descriptions-item label="病区">{{ currentDetail.ward_name }}</el-descriptions-item>
        <el-descriptions-item label="床位">{{ currentDetail.bed_no }} ({{ currentDetail.room_no }})</el-descriptions-item>
        <el-descriptions-item label="入院时间">{{ currentDetail.admission_time }}</el-descriptions-item>
        <el-descriptions-item label="出院时间">{{ currentDetail.discharge_time || '-' }}</el-descriptions-item>
        <el-descriptions-item label="入院诊断" :span="2">{{ currentDetail.admission_diagnosis || '-' }}</el-descriptions-item>
        <el-descriptions-item label="主诉" :span="2">{{ currentDetail.chief_complaint || '-' }}</el-descriptions-item>
        <el-descriptions-item label="现病史" :span="2">{{ currentDetail.present_illness || '-' }}</el-descriptions-item>
        <el-descriptions-item label="既往史" :span="2">{{ currentDetail.past_history || '-' }}</el-descriptions-item>
        <el-descriptions-item label="入院押金" :span="2">¥{{ currentDetail.deposit_amount }}</el-descriptions-item>
      </el-descriptions>
    </el-dialog>

    <!-- 换床对话框 -->
    <el-dialog v-model="transferDialogVisible" title="换床" width="400px">
      <el-form label-width="80px">
        <el-form-item label="当前床位">
          <el-input :model-value="transferRow ? transferRow.bed_no : ''" disabled />
        </el-form-item>
        <el-form-item label="新床位" required>
          <el-select v-model="newBedId" placeholder="选择新床位" class="form-full-width">
            <el-option v-for="b in availableBeds" :key="b.bed_id" :label="b.bed_no + ' (' + b.room_no + ' ' + b.bed_type + ')'" :value="b.bed_id" />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="transferDialogVisible = false">取消</el-button>
        <el-button type="primary" @click="submitTransfer">确定</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, onMounted, watch } from "vue";
import { ElMessage, ElMessageBox } from "element-plus";
import { getAdmissionList, createAdmission, getAdmissionDetail, updateAdmission, getInpatientList, getAvailableBeds } from "@/api/admission";
import { getPatientList, getDoctorList, getDepartmentList } from "@/api/admin";
import { getWardList } from "@/api/ward";
import { doDischarge as apiDoDischarge } from "@/api/discharge";

const activeTab = ref("inpatient");
const admissionList = ref([]);
const inpatientList = ref([]);
const loading = ref(false);
const keyword = ref("");
const filterStatus = ref(null);

const patients = ref([]);
const doctors = ref([]);
const departments = ref([]);
const wards = ref([]);
const wardOptions = ref([]);
const availableBeds = ref([]);

const admissionDialogVisible = ref(false);
const admissionForm = ref({ admission_type: 0, deposit_amount: 0 });
const detailDialogVisible = ref(false);
const currentDetail = ref(null);
const transferDialogVisible = ref(false);
const transferRow = ref(null);
const newBedId = ref(null);

const loadAdmissions = async () => {
  loading.value = true;
  const params = { keyword: keyword.value || undefined };
  if (filterStatus.value !== null && filterStatus.value !== "") {
    params.status = filterStatus.value;
  }
  const res = await getAdmissionList(params);
  admissionList.value = res.data || [];
  if (activeTab.value === "inpatient") {
    const r2 = await getInpatientList({});
    inpatientList.value = r2.data || [];
  }
  loading.value = false;
};

const loadPatients = async () => {
  const res = await getPatientList();
  patients.value = res.data || [];
};

const loadDoctors = async () => {
  const res = await getDoctorList();
  doctors.value = res.data || [];
};

const loadDepartments = async () => {
  const res = await getDepartmentList();
  departments.value = res.data || [];
};

const loadWards = async () => {
  const res = await getWardList();
  wards.value = res.data || [];
};

const onDeptChange = (deptId) => {
  admissionForm.value.department_id = deptId;
  wardOptions.value = wards.value.filter(w => w.department_id === deptId);
  admissionForm.value.ward_id = null;
  admissionForm.value.bed_id = null;
};

const onWardChange = async (wardId) => {
  admissionForm.value.ward_id = wardId;
  const res = await getAvailableBeds({ ward_id: wardId });
  availableBeds.value = res.data || [];
  admissionForm.value.bed_id = null;
};

const onPatientChange = (pid) => {
  const p = patients.value.find(x => x.patient_id === pid);
  if (p) {
    admissionForm.value.past_history = p.allergy_history || "";
  }
};

const openAdmissionDialog = () => {
  admissionForm.value = { admission_type: 0, deposit_amount: 1000 };
  wardOptions.value = [];
  availableBeds.value = [];
  admissionDialogVisible.value = true;
};

const submitAdmission = async () => {
  if (!admissionForm.value.patient_id) { ElMessage.warning("请选择患者"); return; }
  if (!admissionForm.value.doctor_id) { ElMessage.warning("请选择主管医生"); return; }
  if (!admissionForm.value.department_id) { ElMessage.warning("请选择科室"); return; }
  if (!admissionForm.value.ward_id) { ElMessage.warning("请选择病区"); return; }
  if (!admissionForm.value.bed_id) { ElMessage.warning("请选择床位"); return; }
  try {
    await createAdmission(admissionForm.value);
    ElMessage.success("入院登记成功");
    admissionDialogVisible.value = false;
    loadAdmissions();
  } catch (e) {
    ElMessage.error(e.msg || "操作失败");
  }
};

const showDetail = async (row) => {
  const res = await getAdmissionDetail({ admission_id: row.admission_id });
  currentDetail.value = res.data;
  detailDialogVisible.value = true;
};

const openTransferBed = async (row) => {
  transferRow.value = row;
  newBedId.value = null;
  const res = await getAvailableBeds({ ward_id: row.ward_id });
  availableBeds.value = (res.data || []).filter(b => b.bed_id !== row.bed_id);
  transferDialogVisible.value = true;
};

const submitTransfer = async () => {
  if (!newBedId.value) { ElMessage.warning("请选择新床位"); return; }
  try {
    await updateAdmission({ admission_id: transferRow.value.admission_id, bed_id: newBedId.value });
    ElMessage.success("换床成功");
    transferDialogVisible.value = false;
    loadAdmissions();
  } catch (e) {
    ElMessage.error(e.msg || "操作失败");
  }
};

const doDischarge = async (row) => {
  try {
    await ElMessageBox.confirm(`确定为患者 ${row.patient_name} 办理出院？`, "提示", { type: "warning" });
    const res = await apiDoDischarge({ admission_id: row.admission_id });
    ElMessage.success(`出院成功，总费用：¥${res.data?.total_amount || 0}，应退：¥${res.data?.refund_amount || 0}`);
    loadAdmissions();
  } catch (e) {
    if (e !== "cancel") ElMessage.error(e.msg || "操作失败");
  }
};

watch(activeTab, () => {
  loadAdmissions();
});

onMounted(() => {
  loadAdmissions();
  loadPatients();
  loadDoctors();
  loadDepartments();
  loadWards();
});
</script>
