<template>
  <div class="app-container">
    <vab-page-header title="病案首页" description="住院患者基本信息、诊断、手术及费用汇总" />
    <el-card>
      <template #header>
        <div class="page-toolbar">
          <el-button type="primary" @click="openCreate">填写病案首页</el-button>
          <el-select v-model="statusFilter" clearable placeholder="状态" size="small" style="width: 120px" @change="loadRecords">
            <el-option label="草稿" :value="0" />
            <el-option label="已提交" :value="1" />
            <el-option label="已归档" :value="2" />
          </el-select>
          <el-button size="small" @click="loadRecords">查询</el-button>
        </div>
      </template>
      <el-table :data="records" v-loading="loading" size="small" empty-text="暂无病案首页">
        <el-table-column prop="admission_no" label="住院号" width="130" />
        <el-table-column prop="patient_name" label="患者" width="90" />
        <el-table-column prop="admission_diagnosis" label="入院诊断" show-overflow-tooltip />
        <el-table-column prop="discharge_diagnosis" label="出院诊断" show-overflow-tooltip />
        <el-table-column prop="total_fee" label="费用合计" width="100" />
        <el-table-column label="状态" width="85">
          <template #default="{ row }">
            <el-tag :type="row.status === 0 ? 'warning' : row.status === 1 ? 'success' : 'info'" size="small">{{ row.status_text }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="150">
          <template #default="{ row }">
            <el-button size="small" @click="openEdit(row)">查看/编辑</el-button>
            <el-button v-if="row.status === 0" size="small" type="success" @click="submitRecord(row)">提交</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <el-dialog v-model="dialogVisible" :title="form.home_id ? '编辑病案首页' : '填写病案首页'" width="680px">
      <el-form :model="form" label-width="100px">
        <el-form-item label="住院患者" required>
          <el-select v-model="form.admission_id" filterable placeholder="请选择住院患者" style="width: 100%" :disabled="!!form.home_id" @change="onAdmissionChange">
            <el-option v-for="item in availableAdmissions" :key="item.admission_id" :label="`${item.patient_name}（${item.admission_no}）`" :value="item.admission_id" />
          </el-select>
        </el-form-item>
        <el-form-item label="入院诊断" required>
          <el-input v-model="form.admission_diagnosis" maxlength="500" show-word-limit />
        </el-form-item>
        <el-form-item label="出院诊断" required>
          <el-input v-model="form.discharge_diagnosis" maxlength="500" show-word-limit />
        </el-form-item>
        <el-form-item label="其他诊断"><el-input v-model="form.other_diagnosis" type="textarea" :rows="2" maxlength="1000" /></el-form-item>
        <el-form-item label="手术情况"><el-input v-model="form.operation_summary" type="textarea" :rows="2" maxlength="1000" /></el-form-item>
        <el-form-item label="并发症"><el-input v-model="form.complication" maxlength="1000" /></el-form-item>
        <el-form-item label="出院情况">
          <el-select v-model="form.discharge_status" style="width: 180px">
            <el-option label="治愈" :value="0" /><el-option label="好转" :value="1" /><el-option label="未愈" :value="2" /><el-option label="死亡" :value="3" /><el-option label="转院" :value="4" />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :disabled="form.status !== 0" @click="saveRecord">保存草稿</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { onMounted, ref } from "vue";
import { ElMessage, ElMessageBox } from "element-plus";
import { getMedicalRecordHomeAdmissions, getMedicalRecordHomeList, createMedicalRecordHome, updateMedicalRecordHome, submitMedicalRecordHome } from "@/api/medicalRecordHome";

const loading = ref(false);
const records = ref([]);
const availableAdmissions = ref([]);
const statusFilter = ref();
const dialogVisible = ref(false);
const emptyForm = () => ({ home_id: "", admission_id: "", admission_diagnosis: "", discharge_diagnosis: "", other_diagnosis: "", operation_summary: "", complication: "", discharge_status: 0, status: 0 });
const form = ref(emptyForm());

const loadRecords = async () => {
  loading.value = true;
  try { records.value = (await getMedicalRecordHomeList(statusFilter.value === undefined ? {} : { status: statusFilter.value })).data || []; }
  finally { loading.value = false; }
};
const loadAdmissions = async () => { availableAdmissions.value = (await getMedicalRecordHomeAdmissions()).data || []; };
const openCreate = async () => { await loadAdmissions(); form.value = emptyForm(); dialogVisible.value = true; };
const openEdit = (row) => { form.value = { ...row }; dialogVisible.value = true; };
const onAdmissionChange = (id) => { const item = availableAdmissions.value.find(x => x.admission_id === id); if (item) form.value.admission_diagnosis = item.admission_diagnosis || ""; };
const saveRecord = async () => {
  if (!form.value.admission_id || !form.value.admission_diagnosis.trim()) return ElMessage.warning("请选择患者并填写入院诊断");
  if (form.value.home_id) await updateMedicalRecordHome(form.value); else await createMedicalRecordHome(form.value);
  ElMessage.success("保存成功"); dialogVisible.value = false; await loadRecords(); await loadAdmissions();
};
const submitRecord = async (row) => {
  if (!row.discharge_diagnosis) return ElMessage.warning("请先填写出院诊断");
  await ElMessageBox.confirm("提交后将不能继续编辑，确认提交吗？", "提示");
  await submitMedicalRecordHome({ home_id: row.home_id }); ElMessage.success("提交成功"); await loadRecords();
};
onMounted(async () => { await Promise.all([loadRecords(), loadAdmissions()]); });
</script>
