<template>
  <div class="app-container">
    <vab-page-header title="手术麻醉管理" description="手术申请、排台、麻醉记录管理" />
    <el-card>
      <template #header>
        <div class="page-toolbar">
          <el-button type="primary" @click="openApplyDialog()">手术申请</el-button>
          <el-button type="success" @click="openScheduleDialog()">手术排台</el-button>
          <el-select v-model="filterStatus" placeholder="状态" clearable style="width: 120px;" size="small">
            <el-option label="待审批" :value="0" />
            <el-option label="已批准" :value="1" />
            <el-option label="已排台" :value="2" />
            <el-option label="已完成" :value="3" />
          </el-select>
          <el-input v-model="keyword" placeholder="搜索手术/患者" clearable size="small" style="width: 200px;" />
          <el-button type="primary" size="small" @click="loadApplications">查询</el-button>
        </div>
      </template>
      <el-table :data="applications" size="small" v-loading="loading" empty-text="暂无记录">
        <el-table-column prop="patient_name" label="患者" width="80" />
        <el-table-column prop="surgery_name" label="手术名称" />
        <el-table-column prop="surgery_level_text" label="级别" width="70" />
        <el-table-column prop="anesthesia_type" label="麻醉方式" width="90" />
        <el-table-column prop="scheduled_date" label="计划日期" width="100" />
        <el-table-column prop="doctor_name" label="申请医生" width="80" />
        <el-table-column label="状态" width="80">
          <template #default="{row}">
            <el-tag v-if="row.status===0" size="small">{{ row.status_text }}</el-tag>
            <el-tag v-else-if="row.status===1" type="success" size="small">{{ row.status_text }}</el-tag>
            <el-tag v-else-if="row.status===2" type="warning" size="small">{{ row.status_text }}</el-tag>
            <el-tag v-else type="info" size="small">{{ row.status_text }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="200">
          <template #default="{row}">
            <el-button v-if="row.status===0" size="small" type="primary" @click="approveApp(row)">审批</el-button>
            <el-button v-if="row.status===1" size="small" @click="openScheduleDialog(row)">排台</el-button>
            <el-button v-if="row.status===2" size="small" type="success" @click="openAnesthesiaDialog(row)">麻醉</el-button>
            <el-button size="small" type="danger" @click="cancelApp(row)">取消</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <el-card style="margin-top: 20px;">
      <template #header><span>手术排台列表</span></template>
      <el-table :data="schedules" size="small" empty-text="暂无记录">
        <el-table-column prop="patient_name" label="患者" width="80" />
        <el-table-column prop="surgery_name" label="手术名称" />
        <el-table-column prop="operating_room" label="手术室" width="80" />
        <el-table-column prop="surgery_date" label="日期" width="100" />
        <el-table-column prop="surgeon_name" label="主刀" width="80" />
        <el-table-column prop="anesthesiologist_name" label="麻醉医生" width="80" />
        <el-table-column label="状态" width="70">
          <template #default="{row}">
            <el-tag v-if="row.status===0" size="small">{{ row.status_text }}</el-tag>
            <el-tag v-else-if="row.status===1" type="warning" size="small">{{ row.status_text }}</el-tag>
            <el-tag v-else type="success" size="small">{{ row.status_text }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="150">
          <template #default="{row}">
            <el-button v-if="row.status===0" size="small" type="primary" @click="startSurgeryFn(row)">开始</el-button>
            <el-button v-if="row.status===1" size="small" type="success" @click="completeSurgeryFn(row)">完成</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <el-dialog v-model="applyDialogVisible" title="手术申请" width="500px">
      <el-form :model="applyForm" label-width="100px">
        <el-form-item label="患者" required>
          <el-select v-model="applyForm.patient_id" placeholder="选择在院患者" filterable class="form-full-width" @change="onPatientChange">
            <el-option v-for="p in inpatients" :key="p.patient_id" :label="p.patient_name + ' (' + p.bed_no + '床)'" :value="p.patient_id" />
          </el-select>
        </el-form-item>
        <el-form-item label="手术名称" required>
          <el-input v-model="applyForm.surgery_name" />
        </el-form-item>
        <el-form-item label="手术级别">
          <el-radio-group v-model="applyForm.surgery_level">
            <el-radio-button :label="1">一级</el-radio-button>
            <el-radio-button :label="2">二级</el-radio-button>
            <el-radio-button :label="3">三级</el-radio-button>
            <el-radio-button :label="4">四级</el-radio-button>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="麻醉方式">
          <el-select v-model="applyForm.anesthesia_type" class="form-full-width">
            <el-option label="全身麻醉" value="全身麻醉" />
            <el-option label="椎管内麻醉" value="椎管内麻醉" />
            <el-option label="局部麻醉" value="局部麻醉" />
            <el-option label="神经阻滞" value="神经阻滞" />
          </el-select>
        </el-form-item>
        <el-form-item label="计划日期">
          <el-date-picker v-model="applyForm.scheduled_date" type="date" placeholder="选择日期" style="width: 100%;" value-format="YYYY-MM-DD" />
        </el-form-item>
        <el-form-item label="术前诊断">
          <el-input v-model="applyForm.preop_diagnosis" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="applyDialogVisible = false">取消</el-button>
        <el-button type="primary" @click="submitApply">提交</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="scheduleDialogVisible" title="手术排台" width="500px">
      <el-form :model="scheduleForm" label-width="100px">
        <el-form-item label="手术申请" required>
          <el-select v-model="scheduleForm.application_id" placeholder="选择已批准的手术申请" class="form-full-width">
            <el-option v-for="a in approvedApps" :key="a.application_id" :label="a.patient_name + ' - ' + a.surgery_name" :value="a.application_id" />
          </el-select>
        </el-form-item>
        <el-form-item label="手术室">
          <el-input v-model="scheduleForm.operating_room" placeholder="如：手术室1" />
        </el-form-item>
        <el-form-item label="手术日期">
          <el-date-picker v-model="scheduleForm.surgery_date" type="date" placeholder="选择日期" style="width: 100%;" value-format="YYYY-MM-DD" />
        </el-form-item>
        <el-form-item label="主刀医生">
          <el-select v-model="scheduleForm.surgeon_id" placeholder="选择医生" class="form-full-width">
            <el-option v-for="d in doctors" :key="d.doctor_id" :label="d.name" :value="d.doctor_id" />
          </el-select>
        </el-form-item>
        <el-form-item label="麻醉医生">
          <el-select v-model="scheduleForm.anesthesiologist_id" placeholder="选择医生" class="form-full-width">
            <el-option v-for="d in doctors" :key="d.doctor_id" :label="d.name" :value="d.doctor_id" />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="scheduleDialogVisible = false">取消</el-button>
        <el-button type="primary" @click="submitSchedule">确定</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="anesthesiaDialogVisible" title="麻醉记录" width="600px">
      <el-form :model="anesthesiaForm" label-width="100px">
        <el-form-item label="入室时间">
          <el-date-picker v-model="anesthesiaForm.enter_time" type="datetime" placeholder="选择时间" style="width: 100%;" value-format="YYYY-MM-DD HH:mm:ss" />
        </el-form-item>
        <el-form-item label="麻醉方法">
          <el-input v-model="anesthesiaForm.anesthesia_method" />
        </el-form-item>
        <el-form-item label="出血量(ml)">
          <el-input-number v-model="anesthesiaForm.blood_loss" :min="0" style="width: 100%;" />
        </el-form-item>
        <el-form-item label="尿量(ml)">
          <el-input-number v-model="anesthesiaForm.urine_output" :min="0" style="width: 100%;" />
        </el-form-item>
        <el-form-item label="输液量(ml)">
          <el-input-number v-model="anesthesiaForm.fluid_input" :min="0" style="width: 100%;" />
        </el-form-item>
        <el-form-item label="出室时间">
          <el-date-picker v-model="anesthesiaForm.leave_time" type="datetime" placeholder="选择时间" style="width: 100%;" value-format="YYYY-MM-DD HH:mm:ss" />
        </el-form-item>
        <el-form-item label="并发症">
          <el-input v-model="anesthesiaForm.complications" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="anesthesiaDialogVisible = false">取消</el-button>
        <el-button type="primary" @click="submitAnesthesia">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from "vue";
import { ElMessage, ElMessageBox } from "element-plus";
import { getSurgeryApplicationList, createSurgeryApplication, approveSurgeryApplication, cancelSurgeryApplication, getSurgeryScheduleList, createSurgerySchedule, startSurgery, completeSurgery, createAnesthesiaRecord } from "@/api/surgery";
import { getInpatientList } from "@/api/admission";
import { getDoctorList } from "@/api/admin";

const applications = ref([]);
const schedules = ref([]);
const loading = ref(false);
const keyword = ref("");
const filterStatus = ref("");
const inpatients = ref([]);
const doctors = ref([]);
const currentScheduleId = ref("");

const applyDialogVisible = ref(false);
const applyForm = ref({ surgery_level: 1, anesthesia_type: "局部麻醉" });
const scheduleDialogVisible = ref(false);
const scheduleForm = ref({});
const anesthesiaDialogVisible = ref(false);
const anesthesiaForm = ref({});

const approvedApps = computed(() => applications.value.filter(a => a.status === 1));

const loadApplications = async () => {
  loading.value = true;
  const params = {};
  if (filterStatus.value !== "") params.status = filterStatus.value;
  if (keyword.value) params.keyword = keyword.value;
  const res = await getSurgeryApplicationList(params);
  applications.value = res.data || [];
  loading.value = false;
};

const loadSchedules = async () => {
  const res = await getSurgeryScheduleList({});
  schedules.value = res.data || [];
};

const loadInpatients = async () => {
  const res = await getInpatientList({});
  inpatients.value = res.data || [];
};

const loadDoctors = async () => {
  const res = await getDoctorList();
  doctors.value = res.data || [];
};

const onPatientChange = (pid) => {
  const p = inpatients.value.find(x => x.patient_id === pid);
  if (p) {
    applyForm.value.admission_id = p.admission_id;
    applyForm.value.doctor_id = p.doctor_id;
    applyForm.value.preop_diagnosis = p.admission_diagnosis || "";
  }
};

const openApplyDialog = () => {
  applyForm.value = { surgery_level: 1, anesthesia_type: "局部麻醉" };
  applyDialogVisible.value = true;
};

const submitApply = async () => {
  if (!applyForm.value.patient_id || !applyForm.value.surgery_name) {
    ElMessage.warning("请填写完整信息");
    return;
  }
  try {
    await createSurgeryApplication(applyForm.value);
    ElMessage.success("申请成功");
    applyDialogVisible.value = false;
    loadApplications();
  } catch (e) {
    ElMessage.error(e.msg || "操作失败");
  }
};

const approveApp = async (row) => {
  try {
    await approveSurgeryApplication({ application_id: row.application_id });
    ElMessage.success("审批成功");
    loadApplications();
  } catch (e) {
    ElMessage.error(e.msg || "操作失败");
  }
};

const cancelApp = async (row) => {
  try {
    await ElMessageBox.confirm("确定取消该手术申请？", "提示", { type: "warning" });
    await cancelSurgeryApplication({ application_id: row.application_id });
    ElMessage.success("取消成功");
    loadApplications();
    loadSchedules();
  } catch (e) {
    if (e !== "cancel") ElMessage.error(e.msg || "操作失败");
  }
};

const openScheduleDialog = () => {
  scheduleForm.value = {};
  scheduleDialogVisible.value = true;
};

const submitSchedule = async () => {
  if (!scheduleForm.value.application_id) {
    ElMessage.warning("请选择手术申请");
    return;
  }
  try {
    await createSurgerySchedule(scheduleForm.value);
    ElMessage.success("排台成功");
    scheduleDialogVisible.value = false;
    loadApplications();
    loadSchedules();
  } catch (e) {
    ElMessage.error(e.msg || "操作失败");
  }
};

const startSurgeryFn = async (row) => {
  try {
    await startSurgery({ schedule_id: row.schedule_id });
    ElMessage.success("手术已开始");
    loadSchedules();
  } catch (e) {
    ElMessage.error(e.msg || "操作失败");
  }
};

const completeSurgeryFn = async (row) => {
  try {
    await completeSurgery({ schedule_id: row.schedule_id });
    ElMessage.success("手术已完成");
    loadSchedules();
  } catch (e) {
    ElMessage.error(e.msg || "操作失败");
  }
};

const openAnesthesiaDialog = (row) => {
  currentScheduleId.value = row.schedule_id || "";
  anesthesiaForm.value = {};
  anesthesiaDialogVisible.value = true;
};

const submitAnesthesia = async () => {
  if (!currentScheduleId.value) return;
  try {
    await createAnesthesiaRecord({ schedule_id: currentScheduleId.value, ...anesthesiaForm.value });
    ElMessage.success("记录成功");
    anesthesiaDialogVisible.value = false;
  } catch (e) {
    ElMessage.error(e.msg || "操作失败");
  }
};

onMounted(() => {
  loadApplications();
  loadSchedules();
  loadInpatients();
  loadDoctors();
});
</script>
