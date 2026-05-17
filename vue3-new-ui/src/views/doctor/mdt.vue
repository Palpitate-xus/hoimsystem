<template>
  <div class="app-container">
    <vab-page-header title="多学科会诊" description="发起和参与多学科联合会诊申请" />
    <el-card>
      <div class="page-toolbar">
        <el-button type="primary" @click="handleAdd">新增会诊</el-button>
      </div>
      <el-table :data="tableData" v-loading="loading" border empty-text="暂无记录">
        <el-table-column prop="patient_name" label="患者姓名" width="120" />
        <el-table-column prop="diagnosis" label="初步诊断" show-overflow-tooltip />
        <el-table-column label="参与科室" min-width="220">
          <template #default="scope">
            <el-tag
              v-for="(name, idx) in scope.row.department_names"
              :key="idx"
              type="primary"
              effect="light"
              style="margin-right: 4px; margin-bottom: 2px;"
            >
              {{ name }}
            </el-tag>
            <span v-if="!scope.row.department_names || scope.row.department_names.length === 0" style="color:#999">-</span>
          </template>
        </el-table-column>
        <el-table-column prop="status_text" label="状态" width="100">
          <template #default="scope">
            <el-tag
              :type="scope.row.status === 2 ? 'success' : scope.row.status === 1 ? 'warning' : 'info'"
              size="small"
            >
              {{ scope.row.status_text }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="result" label="会诊结果" show-overflow-tooltip />
        <el-table-column prop="create_time" label="创建时间" width="160" />
        <el-table-column label="操作" width="120">
          <template #default="scope">
            <el-button
              v-if="scope.row.status === 2 && !scope.row.result"
              size="small"
              type="primary"
              @click="handleUpdateResult(scope.row)"
            >录入结果</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <el-dialog v-model="dialogVisible" title="新增会诊" width="540px">
      <el-form :model="form" label-width="100px" class="dialog-form">
        <el-form-item label="患者">
          <el-select v-model="form.patient_id" placeholder="请选择患者" filterable class="form-full-width">
            <el-option v-for="p in patients" :key="p.patient_id" :label="p.name" :value="p.patient_id" />
          </el-select>
        </el-form-item>
        <el-form-item label="初步诊断">
          <el-input v-model="form.diagnosis" type="textarea" :rows="3" placeholder="请输入初步诊断" />
        </el-form-item>
        <el-form-item label="参与科室">
          <el-select
            v-model="form.department_ids"
            multiple
            collapse-tags
            collapse-tags-tooltip
            placeholder="请选择参与会诊的科室"
            class="form-full-width"
          >
            <el-option
              v-for="d in departments"
              :key="d.id"
              :label="d.name"
              :value="d.id"
            />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" @click="submitForm">确定</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="resultDialogVisible" title="录入会诊结果" width="500px">
      <el-form :model="resultForm" label-width="100px" class="dialog-form">
        <el-form-item label="会诊结果">
          <el-input v-model="resultForm.result" type="textarea" :rows="4" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="resultDialogVisible = false">取消</el-button>
        <el-button type="primary" @click="submitResult">确定</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, onMounted } from "vue";
import { ElMessage } from "element-plus";
import { createMdt, getMdtList, updateMdt } from "@/api/mdt";
import { getDepartmentList, getPatientList } from "@/api/admin";

const tableData = ref([]);
const loading = ref(false);
const dialogVisible = ref(false);
const resultDialogVisible = ref(false);
const departments = ref([]);
const patients = ref([]);

const form = ref({
  patient_id: "",
  diagnosis: "",
  department_ids: [],
});
const resultForm = ref({
  mdt_id: "",
  result: "",
});

const fetchList = async () => {
  loading.value = true;
  try {
    const res = await getMdtList();
    tableData.value = res.data || res || [];
  } catch (error) {
    ElMessage.error("获取会诊列表失败");
  }
  loading.value = false;
};

const fetchDepartments = async () => {
  try {
    const res = await getDepartmentList();
    departments.value = res.data || res || [];
  } catch (e) {
    console.error("获取科室失败", e);
  }
};

const fetchPatients = async () => {
  try {
    const res = await getPatientList();
    patients.value = res.data || [];
  } catch (e) {
    console.error("获取患者失败", e);
  }
};

const handleAdd = () => {
  form.value = { patient_id: "", diagnosis: "", department_ids: [] };
  dialogVisible.value = true;
};

const submitForm = async () => {
  try {
    const payload = {
      patient_id: form.value.patient_id,
      diagnosis: form.value.diagnosis,
      department_ids: JSON.stringify(form.value.department_ids),
    };
    await createMdt(payload);
    ElMessage.success("新增成功");
    dialogVisible.value = false;
    fetchList();
  } catch (error) {
    ElMessage.error("新增失败");
  }
};

const handleUpdateResult = (row) => {
  resultForm.value = { mdt_id: row.mdt_id, result: row.result || "" };
  resultDialogVisible.value = true;
};

const submitResult = async () => {
  try {
    await updateMdt(resultForm.value);
    ElMessage.success("结果录入成功");
    resultDialogVisible.value = false;
    fetchList();
  } catch (error) {
    ElMessage.error("结果录入失败");
  }
};

onMounted(() => {
  fetchList();
  fetchDepartments();
  fetchPatients();
});
</script>
