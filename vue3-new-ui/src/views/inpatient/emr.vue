<template>
  <div class="app-container">
    <vab-page-header title="结构化电子病历" description="病历书写、病程记录、查房记录、病历质控" />
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
              <span>{{ currentPatient.patient_name }} - {{ currentPatient.bed_no }}床</span>
              <div>
                <el-button type="primary" size="small" @click="openRecordDialog()">书写病历</el-button>
                <el-button type="success" size="small" @click="openProgressDialog()">病程记录</el-button>
                <el-button type="warning" size="small" @click="openRoundDialog()">查房记录</el-button>
              </div>
            </div>
          </template>
          <el-tabs v-model="activeTab">
            <el-tab-pane label="病历列表" name="records">
              <el-table :data="recordList" size="small" v-loading="recordLoading">
                <el-table-column prop="record_type_text" label="类型" width="80" />
                <el-table-column prop="chief_complaint" label="主诉" show-overflow-tooltip />
                <el-table-column prop="diagnosis" label="诊断" show-overflow-tooltip />
                <el-table-column label="状态" width="70">
                  <template #default="{row}">
                    <el-tag v-if="row.status===0" size="small">{{ row.status_text }}</el-tag>
                    <el-tag v-else-if="row.status===1" type="success" size="small">{{ row.status_text }}</el-tag>
                    <el-tag v-else type="info" size="small">{{ row.status_text }}</el-tag>
                  </template>
                </el-table-column>
                <el-table-column prop="doctor_name" label="医生" width="80" />
                <el-table-column prop="create_time" label="时间" width="140" />
                <el-table-column label="操作" width="150">
                  <template #default="{row}">
                    <el-button size="small" @click="showRecordDetail(row)">查看</el-button>
                    <el-button v-if="row.status===0" size="small" type="primary" @click="signRecord(row)">签名</el-button>
                  </template>
                </el-table-column>
              </el-table>
            </el-tab-pane>
            <el-tab-pane label="病程记录" name="progress">
              <el-table :data="progressNotes" size="small">
                <el-table-column prop="note_date" label="日期" width="100" />
                <el-table-column prop="content" label="内容" show-overflow-tooltip />
                <el-table-column prop="doctor_name" label="医生" width="80" />
                <el-table-column prop="record_time" label="记录时间" width="140" />
                <el-table-column label="操作" width="80">
                  <template #default="{row}">
                    <el-button size="small" type="danger" @click="deleteProgress(row)">删除</el-button>
                  </template>
                </el-table-column>
              </el-table>
            </el-tab-pane>
            <el-tab-pane label="查房记录" name="round">
              <el-table :data="wardRounds" size="small">
                <el-table-column prop="round_type_text" label="类型" width="100" />
                <el-table-column prop="content" label="查房意见" show-overflow-tooltip />
                <el-table-column prop="doctor_name" label="查房医生" width="80" />
                <el-table-column prop="round_time" label="时间" width="140" />
                <el-table-column label="操作" width="80">
                  <template #default="{row}">
                    <el-button size="small" type="danger" @click="deleteRound(row)">删除</el-button>
                  </template>
                </el-table-column>
              </el-table>
            </el-tab-pane>
          </el-tabs>
        </el-card>
        <el-card v-else style="text-align: center; padding: 60px; color: #999;">
          <div>请从左侧选择一个在院患者</div>
        </el-card>
      </el-col>
    </el-row>

    <!-- 书写病历对话框 -->
    <el-dialog v-model="recordDialogVisible" title="书写病历" width="700px">
      <el-form :model="recordForm" label-width="100px">
        <el-form-item label="病历类型">
          <el-radio-group v-model="recordForm.record_type">
            <el-radio-button :label="0">入院记录</el-radio-button>
            <el-radio-button :label="1">首次病程</el-radio-button>
            <el-radio-button :label="2">日常病程</el-radio-button>
            <el-radio-button :label="3">出院记录</el-radio-button>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="主诉">
          <el-input v-model="recordForm.chief_complaint" placeholder="患者最主要的症状/体征及其持续时间" />
        </el-form-item>
        <el-form-item label="现病史">
          <el-input v-model="recordForm.present_illness" type="textarea" :rows="3" placeholder="疾病的发生、发展、诊疗经过" />
        </el-form-item>
        <el-form-item label="既往史">
          <el-input v-model="recordForm.past_history" type="textarea" :rows="2" />
        </el-form-item>
        <el-form-item label="个人史">
          <el-input v-model="recordForm.personal_history" />
        </el-form-item>
        <el-form-item label="家族史">
          <el-input v-model="recordForm.family_history" />
        </el-form-item>
        <el-form-item label="体格检查">
          <el-input v-model="recordForm.physical_exam" type="textarea" :rows="3" />
        </el-form-item>
        <el-form-item label="辅助检查">
          <el-input v-model="recordForm.auxiliary_exam" type="textarea" :rows="2" />
        </el-form-item>
        <el-form-item label="初步诊断">
          <el-input v-model="recordForm.diagnosis" />
        </el-form-item>
        <el-form-item label="诊疗计划">
          <el-input v-model="recordForm.treatment_plan" type="textarea" :rows="2" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="recordDialogVisible = false">取消</el-button>
        <el-button type="primary" @click="submitRecord">保存</el-button>
      </template>
    </el-dialog>

    <!-- 病历详情对话框 -->
    <el-dialog v-model="detailDialogVisible" title="病历详情" width="700px">
      <el-descriptions :column="1" border size="small" v-if="currentRecordDetail">
        <el-descriptions-item label="病历类型">{{ currentRecordDetail.record_type_text }}</el-descriptions-item>
        <el-descriptions-item label="患者">{{ currentRecordDetail.patient_name }}</el-descriptions-item>
        <el-descriptions-item label="主管医生">{{ currentRecordDetail.doctor_name }}</el-descriptions-item>
        <el-descriptions-item label="状态">
          <el-tag v-if="currentRecordDetail.status===0" size="small">{{ currentRecordDetail.status_text }}</el-tag>
          <el-tag v-else-if="currentRecordDetail.status===1" type="success" size="small">{{ currentRecordDetail.status_text }}</el-tag>
          <el-tag v-else type="info" size="small">{{ currentRecordDetail.status_text }}</el-tag>
        </el-descriptions-item>
        <el-descriptions-item label="主诉">{{ currentRecordDetail.chief_complaint || '-' }}</el-descriptions-item>
        <el-descriptions-item label="现病史">{{ currentRecordDetail.present_illness || '-' }}</el-descriptions-item>
        <el-descriptions-item label="既往史">{{ currentRecordDetail.past_history || '-' }}</el-descriptions-item>
        <el-descriptions-item label="个人史">{{ currentRecordDetail.personal_history || '-' }}</el-descriptions-item>
        <el-descriptions-item label="家族史">{{ currentRecordDetail.family_history || '-' }}</el-descriptions-item>
        <el-descriptions-item label="体格检查">{{ currentRecordDetail.physical_exam || '-' }}</el-descriptions-item>
        <el-descriptions-item label="辅助检查">{{ currentRecordDetail.auxiliary_exam || '-' }}</el-descriptions-item>
        <el-descriptions-item label="初步诊断">{{ currentRecordDetail.diagnosis || '-' }}</el-descriptions-item>
        <el-descriptions-item label="诊疗计划">{{ currentRecordDetail.treatment_plan || '-' }}</el-descriptions-item>
      </el-descriptions>
    </el-dialog>

    <!-- 病程记录对话框 -->
    <el-dialog v-model="progressDialogVisible" title="新增病程记录" width="500px">
      <el-form :model="progressForm" label-width="80px">
        <el-form-item label="日期" required>
          <el-date-picker v-model="progressForm.note_date" type="date" placeholder="选择日期" style="width: 100%;" value-format="YYYY-MM-DD" />
        </el-form-item>
        <el-form-item label="内容" required>
          <el-input v-model="progressForm.content" type="textarea" :rows="4" placeholder="记录患者病情变化、诊疗措施及效果" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="progressDialogVisible = false">取消</el-button>
        <el-button type="primary" @click="submitProgress">保存</el-button>
      </template>
    </el-dialog>

    <!-- 查房记录对话框 -->
    <el-dialog v-model="roundDialogVisible" title="新增查房记录" width="500px">
      <el-form :model="roundForm" label-width="100px">
        <el-form-item label="查房类型">
          <el-radio-group v-model="roundForm.round_type">
            <el-radio-button :label="0">主任医师</el-radio-button>
            <el-radio-button :label="1">副主任医师</el-radio-button>
            <el-radio-button :label="2">主治医师</el-radio-button>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="查房意见" required>
          <el-input v-model="roundForm.content" type="textarea" :rows="4" placeholder="查房医生意见、指示" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="roundDialogVisible = false">取消</el-button>
        <el-button type="primary" @click="submitRound">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from "vue";
import { ElMessage, ElMessageBox } from "element-plus";
import { getInpatientList } from "@/api/admission";
import { getStructuredRecordList, createStructuredRecord, getStructuredRecordDetail, signMedicalRecord, getProgressNoteList, createProgressNote, deleteProgressNote, getWardRoundList, createWardRound, deleteWardRound } from "@/api/emr";

const inpatients = ref([]);
const patientKeyword = ref("");
const currentPatient = ref(null);
const activeTab = ref("records");

const recordList = ref([]);
const recordLoading = ref(false);
const progressNotes = ref([]);
const wardRounds = ref([]);

const recordDialogVisible = ref(false);
const recordForm = ref({ record_type: 0 });
const detailDialogVisible = ref(false);
const currentRecordDetail = ref(null);
const progressDialogVisible = ref(false);
const progressForm = ref({ note_date: "" });
const roundDialogVisible = ref(false);
const roundForm = ref({ round_type: 2 });

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
  await loadAllData();
};

const loadAllData = async () => {
  if (!currentPatient.value) return;
  await loadRecords();
  await loadProgressNotes();
  await loadWardRounds();
};

const loadRecords = async () => {
  recordLoading.value = true;
  const res = await getStructuredRecordList({ admission_id: currentPatient.value.admission_id });
  recordList.value = res.data || [];
  recordLoading.value = false;
};

const loadProgressNotes = async () => {
  const res = await getProgressNoteList({ admission_id: currentPatient.value.admission_id });
  progressNotes.value = res.data || [];
};

const loadWardRounds = async () => {
  const res = await getWardRoundList({ admission_id: currentPatient.value.admission_id });
  wardRounds.value = res.data || [];
};

const openRecordDialog = () => {
  recordForm.value = { record_type: 0 };
  recordDialogVisible.value = true;
};

const submitRecord = async () => {
  if (!currentPatient.value) return;
  try {
    await createStructuredRecord({
      ...recordForm.value,
      admission_id: currentPatient.value.admission_id,
      patient_id: currentPatient.value.patient_id,
      doctor_id: currentPatient.value.doctor_id,
    });
    ElMessage.success("保存成功");
    recordDialogVisible.value = false;
    loadRecords();
  } catch (e) {
    ElMessage.error(e.msg || "操作失败");
  }
};

const showRecordDetail = async (row) => {
  const res = await getStructuredRecordDetail({ record_id: row.record_id });
  currentRecordDetail.value = res.data;
  detailDialogVisible.value = true;
};

const signRecord = async (row) => {
  try {
    await ElMessageBox.confirm("确定签名？签名后病历不可修改。", "提示", { type: "warning" });
    await signMedicalRecord({ record_id: row.record_id });
    ElMessage.success("签名成功");
    loadRecords();
  } catch (e) {
    if (e !== "cancel") ElMessage.error(e.msg || "操作失败");
  }
};

const openProgressDialog = () => {
  progressForm.value = { note_date: new Date().toISOString().slice(0, 10) };
  progressDialogVisible.value = true;
};

const submitProgress = async () => {
  if (!currentPatient.value) return;
  try {
    await createProgressNote({
      ...progressForm.value,
      admission_id: currentPatient.value.admission_id,
      patient_id: currentPatient.value.patient_id,
      doctor_id: currentPatient.value.doctor_id,
    });
    ElMessage.success("保存成功");
    progressDialogVisible.value = false;
    loadProgressNotes();
  } catch (e) {
    ElMessage.error(e.msg || "操作失败");
  }
};

const deleteProgress = async (row) => {
  try {
    await ElMessageBox.confirm("确定删除该病程记录？", "提示", { type: "warning" });
    await deleteProgressNote({ note_id: row.note_id });
    ElMessage.success("删除成功");
    loadProgressNotes();
  } catch (e) {
    if (e !== "cancel") ElMessage.error(e.msg || "操作失败");
  }
};

const openRoundDialog = () => {
  roundForm.value = { round_type: 2 };
  roundDialogVisible.value = true;
};

const submitRound = async () => {
  if (!currentPatient.value) return;
  try {
    await createWardRound({
      ...roundForm.value,
      admission_id: currentPatient.value.admission_id,
      patient_id: currentPatient.value.patient_id,
      doctor_id: currentPatient.value.doctor_id,
    });
    ElMessage.success("保存成功");
    roundDialogVisible.value = false;
    loadWardRounds();
  } catch (e) {
    ElMessage.error(e.msg || "操作失败");
  }
};

const deleteRound = async (row) => {
  try {
    await ElMessageBox.confirm("确定删除该查房记录？", "提示", { type: "warning" });
    await deleteWardRound({ round_id: row.round_id });
    ElMessage.success("删除成功");
    loadWardRounds();
  } catch (e) {
    if (e !== "cancel") ElMessage.error(e.msg || "操作失败");
  }
};

onMounted(() => {
  loadInpatients();
});
</script>
