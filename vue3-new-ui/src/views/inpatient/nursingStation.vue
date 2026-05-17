<template>
  <div class="app-container">
    <vab-page-header title="护士工作站" description="医嘱执行、护理记录、体温单" />
    <el-row :gutter="20">
      <el-col :span="5">
        <el-card>
          <template #header>
            <span>在院患者</span>
          </template>
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
          <el-tabs v-model="activeTab">
            <el-tab-pane label="医嘱执行" name="execution">
              <div class="page-toolbar">
                <el-select v-model="executionFilter" placeholder="状态" clearable size="small" style="width: 120px;">
                  <el-option label="待执行" :value="0" />
                  <el-option label="已执行" :value="1" />
                </el-select>
                <el-button type="primary" size="small" @click="loadExecutions">查询</el-button>
              </div>
              <el-table :data="filteredExecutions" size="small" v-loading="executionLoading" empty-text="暂无医嘱执行">
                <el-table-column prop="patient_name" label="患者" width="80" />
                <el-table-column prop="item_names" label="医嘱内容" show-overflow-tooltip />
                <el-table-column prop="order_type_text" label="类型" width="60" />
                <el-table-column prop="planned_time" label="计划时间" width="140" />
                <el-table-column prop="execution_time" label="执行时间" width="140" />
                <el-table-column label="状态" width="70">
                  <template #default="{row}">
                    <el-tag v-if="row.status===0" size="small" type="warning">{{ row.status_text }}</el-tag>
                    <el-tag v-else-if="row.status===1" size="small" type="success">{{ row.status_text }}</el-tag>
                    <el-tag v-else size="small" type="info">{{ row.status_text }}</el-tag>
                  </template>
                </el-table-column>
                <el-table-column label="操作" width="100">
                  <template #default="{row}">
                    <el-button v-if="row.status===0" size="small" type="success" @click="executeItem(row)">执行</el-button>
                  </template>
                </el-table-column>
              </el-table>
            </el-tab-pane>
            <el-tab-pane label="护理记录" name="nursing">
              <div class="page-toolbar">
                <el-button type="primary" size="small" @click="openNursingDialog()">新增护理记录</el-button>
              </div>
              <el-table :data="nursingRecords" size="small" v-loading="nursingLoading" empty-text="暂无护理记录">
                <el-table-column prop="record_time" label="记录时间" width="140" />
                <el-table-column prop="consciousness" label="意识" width="70" />
                <el-table-column prop="temperature" label="体温" width="70" />
                <el-table-column prop="pulse" label="脉搏" width="60" />
                <el-table-column prop="respiration" label="呼吸" width="60" />
                <el-table-column prop="blood_pressure" label="血压" width="80" />
                <el-table-column prop="spo2" label="血氧" width="60" />
                <el-table-column prop="intake" label="入量" width="80" />
                <el-table-column prop="output" label="出量" width="80" />
                <el-table-column prop="note" label="备注" show-overflow-tooltip />
                <el-table-column label="操作" width="80">
                  <template #default="{row}">
                    <el-button size="small" type="danger" @click="deleteNursingRecord(row)">删除</el-button>
                  </template>
                </el-table-column>
              </el-table>
            </el-tab-pane>
            <el-tab-pane label="体温单" name="temperature">
              <div class="page-toolbar">
                <el-date-picker v-model="tempDate" type="date" placeholder="选择日期" size="small" value-format="YYYY-MM-DD" />
                <el-button type="primary" size="small" @click="openTempDialog()">录入体温</el-button>
              </div>
              <el-table :data="temperatureRecords" size="small" v-loading="tempLoading" empty-text="暂无体温记录">
                <el-table-column prop="time_point" label="时间点" width="80" />
                <el-table-column prop="temperature" label="体温" width="70" />
                <el-table-column prop="pulse" label="脉搏" width="60" />
                <el-table-column prop="respiration" label="呼吸" width="60" />
                <el-table-column prop="blood_pressure" label="血压" width="80" />
                <el-table-column prop="stool_count" label="大便" width="60" />
                <el-table-column prop="weight" label="体重" width="60" />
                <el-table-column prop="intake" label="入量" width="60" />
                <el-table-column prop="output" label="出量" width="60" />
                <el-table-column prop="note" label="备注" show-overflow-tooltip />
                <el-table-column label="操作" width="80">
                  <template #default="{row}">
                    <el-button size="small" type="danger" @click="deleteTempRecord(row)">删除</el-button>
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

    <!-- 护理记录对话框 -->
    <el-dialog v-model="nursingDialogVisible" title="新增护理记录" width="500px">
      <el-form :model="nursingForm" label-width="80px">
        <el-form-item label="记录时间">
          <el-date-picker v-model="nursingForm.record_time" type="datetime" placeholder="选择时间" style="width: 100%;" value-format="YYYY-MM-DD HH:mm:ss" />
        </el-form-item>
        <el-form-item label="意识">
          <el-select v-model="nursingForm.consciousness" placeholder="选择意识状态" class="form-full-width">
            <el-option label="清醒" value="清醒" />
            <el-option label="嗜睡" value="嗜睡" />
            <el-option label="昏迷" value="昏迷" />
            <el-option label="烦躁" value="烦躁" />
          </el-select>
        </el-form-item>
        <el-row :gutter="10">
          <el-col :span="12">
            <el-form-item label="体温">
              <el-input-number v-model="nursingForm.temperature" :precision="1" :min="30" :max="45" style="width: 100%;" />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="脉搏">
              <el-input-number v-model="nursingForm.pulse" :min="0" :max="300" style="width: 100%;" />
            </el-form-item>
          </el-col>
        </el-row>
        <el-row :gutter="10">
          <el-col :span="12">
            <el-form-item label="呼吸">
              <el-input-number v-model="nursingForm.respiration" :min="0" :max="100" style="width: 100%;" />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="血氧">
              <el-input-number v-model="nursingForm.spo2" :min="0" :max="100" style="width: 100%;" />
            </el-form-item>
          </el-col>
        </el-row>
        <el-form-item label="血压">
          <el-input v-model="nursingForm.blood_pressure" placeholder="如：120/80" />
        </el-form-item>
        <el-form-item label="入量">
          <el-input v-model="nursingForm.intake" placeholder="入量描述" />
        </el-form-item>
        <el-form-item label="出量">
          <el-input v-model="nursingForm.output" placeholder="出量描述" />
        </el-form-item>
        <el-form-item label="皮肤情况">
          <el-input v-model="nursingForm.skin_condition" placeholder="皮肤情况" />
        </el-form-item>
        <el-form-item label="引流情况">
          <el-input v-model="nursingForm.drainage" placeholder="引流情况" />
        </el-form-item>
        <el-form-item label="备注">
          <el-input v-model="nursingForm.note" type="textarea" :rows="2" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="nursingDialogVisible = false">取消</el-button>
        <el-button type="primary" @click="submitNursing">确定</el-button>
      </template>
    </el-dialog>

    <!-- 体温录入对话框 -->
    <el-dialog v-model="tempDialogVisible" title="录入体温" width="500px">
      <el-form :model="tempForm" label-width="80px">
        <el-form-item label="日期">
          <el-date-picker v-model="tempForm.record_date" type="date" placeholder="选择日期" style="width: 100%;" value-format="YYYY-MM-DD" />
        </el-form-item>
        <el-form-item label="时间点">
          <el-select v-model="tempForm.time_point" placeholder="选择时间点" class="form-full-width">
            <el-option label="02:00" value="02:00" />
            <el-option label="06:00" value="06:00" />
            <el-option label="10:00" value="10:00" />
            <el-option label="14:00" value="14:00" />
            <el-option label="18:00" value="18:00" />
            <el-option label="22:00" value="22:00" />
          </el-select>
        </el-form-item>
        <el-row :gutter="10">
          <el-col :span="12">
            <el-form-item label="体温">
              <el-input-number v-model="tempForm.temperature" :precision="1" :min="30" :max="45" style="width: 100%;" />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="脉搏">
              <el-input-number v-model="tempForm.pulse" :min="0" :max="300" style="width: 100%;" />
            </el-form-item>
          </el-col>
        </el-row>
        <el-row :gutter="10">
          <el-col :span="12">
            <el-form-item label="呼吸">
              <el-input-number v-model="tempForm.respiration" :min="0" :max="100" style="width: 100%;" />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="血压">
              <el-input v-model="tempForm.blood_pressure" placeholder="120/80" />
            </el-form-item>
          </el-col>
        </el-row>
        <el-row :gutter="10">
          <el-col :span="12">
            <el-form-item label="大便次数">
              <el-input-number v-model="tempForm.stool_count" :min="0" style="width: 100%;" />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="体重(kg)">
              <el-input-number v-model="tempForm.weight" :precision="1" :min="0" style="width: 100%;" />
            </el-form-item>
          </el-col>
        </el-row>
        <el-row :gutter="10">
          <el-col :span="12">
            <el-form-item label="入量(ml)">
              <el-input-number v-model="tempForm.intake" :min="0" style="width: 100%;" />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="出量(ml)">
              <el-input-number v-model="tempForm.output" :min="0" style="width: 100%;" />
            </el-form-item>
          </el-col>
        </el-row>
        <el-form-item label="备注">
          <el-input v-model="tempForm.note" type="textarea" :rows="2" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="tempDialogVisible = false">取消</el-button>
        <el-button type="primary" @click="submitTemp">确定</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, watch } from "vue";
import { ElMessage, ElMessageBox } from "element-plus";
import { getInpatientList } from "@/api/admission";
import { getExecutionList, executeOrder } from "@/api/inpatientOrder";
import { getNursingRecordList, createNursingRecord, deleteNursingRecord as apiDeleteNursing } from "@/api/nursing";
import { getTemperatureRecordList, createTemperatureRecord, deleteTemperatureRecord as apiDeleteTemp } from "@/api/nursing";

const inpatients = ref([]);
const patientKeyword = ref("");
const currentPatient = ref(null);
const activeTab = ref("execution");

const executions = ref([]);
const executionLoading = ref(false);
const executionFilter = ref("");

const nursingRecords = ref([]);
const nursingLoading = ref(false);
const nursingDialogVisible = ref(false);
const nursingForm = ref({});

const temperatureRecords = ref([]);
const tempLoading = ref(false);
const tempDate = ref("");
const tempDialogVisible = ref(false);
const tempForm = ref({ time_point: "06:00" });

const filteredInpatients = computed(() => {
  if (!patientKeyword.value) return inpatients.value;
  const kw = patientKeyword.value.toLowerCase();
  return inpatients.value.filter(p => p.patient_name.toLowerCase().includes(kw));
});

const filteredExecutions = computed(() => {
  if (executionFilter.value === "" || executionFilter.value === undefined || executionFilter.value === null) return executions.value;
  return executions.value.filter(e => e.status === executionFilter.value);
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
  await loadExecutions();
  await loadNursingRecords();
  await loadTemperatureRecords();
};

const loadExecutions = async () => {
  executionLoading.value = true;
  const res = await getExecutionList({ order_id: undefined });
  executions.value = (res.data || []).filter(e => e.patient_name === currentPatient.value.patient_name);
  executionLoading.value = false;
};

const loadNursingRecords = async () => {
  nursingLoading.value = true;
  const res = await getNursingRecordList({ admission_id: currentPatient.value.admission_id });
  nursingRecords.value = res.data || [];
  nursingLoading.value = false;
};

const loadTemperatureRecords = async () => {
  tempLoading.value = true;
  const params = { admission_id: currentPatient.value.admission_id };
  if (tempDate.value) params.record_date = tempDate.value;
  const res = await getTemperatureRecordList(params);
  temperatureRecords.value = res.data || [];
  tempLoading.value = false;
};

const executeItem = async (row) => {
  try {
    await executeOrder({ order_id: row.order_id, status: 1 });
    ElMessage.success("执行成功");
    loadExecutions();
  } catch (e) {
    ElMessage.error(e.msg || "操作失败");
  }
};

const openNursingDialog = () => {
  nursingForm.value = { record_time: new Date().toISOString().slice(0, 19).replace("T", " ") };
  nursingDialogVisible.value = true;
};

const submitNursing = async () => {
  if (!currentPatient.value) return;
  try {
    await createNursingRecord({ ...nursingForm.value, admission_id: currentPatient.value.admission_id, patient_id: currentPatient.value.patient_id });
    ElMessage.success("记录成功");
    nursingDialogVisible.value = false;
    loadNursingRecords();
  } catch (e) {
    ElMessage.error(e.msg || "操作失败");
  }
};

const deleteNursingRecord = async (row) => {
  try {
    await ElMessageBox.confirm("确定删除该护理记录？", "提示", { type: "warning" });
    await apiDeleteNursing({ record_id: row.record_id });
    ElMessage.success("删除成功");
    loadNursingRecords();
  } catch (e) {
    if (e !== "cancel") ElMessage.error(e.msg || "操作失败");
  }
};

const openTempDialog = () => {
  tempForm.value = { time_point: "06:00", record_date: new Date().toISOString().slice(0, 10) };
  tempDialogVisible.value = true;
};

const submitTemp = async () => {
  if (!currentPatient.value) return;
  try {
    await createTemperatureRecord({ ...tempForm.value, admission_id: currentPatient.value.admission_id, patient_id: currentPatient.value.patient_id });
    ElMessage.success("录入成功");
    tempDialogVisible.value = false;
    loadTemperatureRecords();
  } catch (e) {
    ElMessage.error(e.msg || "操作失败");
  }
};

const deleteTempRecord = async (row) => {
  try {
    await ElMessageBox.confirm("确定删除该体温记录？", "提示", { type: "warning" });
    await apiDeleteTemp({ temp_id: row.temp_id });
    ElMessage.success("删除成功");
    loadTemperatureRecords();
  } catch (e) {
    if (e !== "cancel") ElMessage.error(e.msg || "操作失败");
  }
};

watch(tempDate, () => {
  if (currentPatient.value) loadTemperatureRecords();
});

onMounted(() => {
  loadInpatients();
});
</script>
