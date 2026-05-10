<template>
  <div class="app-container">
    <vab-page-header title="多学科会诊" />
    <el-card>
      <div style="margin-bottom: 16px;">
        <el-button type="primary" @click="handleAdd">新增会诊</el-button>
      </div>
      <el-table :data="tableData" v-loading="loading" border>
        <el-table-column prop="patient_name" label="患者姓名" />
        <el-table-column prop="diagnosis" label="初步诊断" show-overflow-tooltip />
        <el-table-column prop="department_ids" label="参与科室" show-overflow-tooltip />
        <el-table-column prop="status_text" label="状态" />
        <el-table-column prop="result" label="会诊结果" show-overflow-tooltip />
        <el-table-column label="操作" width="200">
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

    <el-dialog v-model="dialogVisible" title="新增会诊" width="500px">
      <el-form :model="form" label-width="100px">
        <el-form-item label="患者ID">
          <el-input v-model="form.patient_id" />
        </el-form-item>
        <el-form-item label="初步诊断">
          <el-input v-model="form.diagnosis" type="textarea" :rows="3" />
        </el-form-item>
        <el-form-item label="参与科室">
          <el-input v-model="form.department_ids" placeholder="多个科室ID用逗号分隔" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" @click="submitForm">确定</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="resultDialogVisible" title="录入会诊结果" width="500px">
      <el-form :model="resultForm" label-width="100px">
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

const tableData = ref([]);
const loading = ref(false);
const dialogVisible = ref(false);
const resultDialogVisible = ref(false);
const form = ref({
  patient_id: "",
  diagnosis: "",
  department_ids: "",
});
const resultForm = ref({
  id: "",
  result: "",
});

const fetchList = async () => {
  loading.value = true;
  try {
    const res = await getMdtList();
    tableData.value = res.data || res;
  } catch (error) {
    ElMessage.error("获取会诊列表失败");
  }
  loading.value = false;
};

const handleAdd = () => {
  form.value = { patient_id: "", diagnosis: "", department_ids: "" };
  dialogVisible.value = true;
};

const submitForm = async () => {
  try {
    await createMdt(form.value);
    ElMessage.success("新增成功");
    dialogVisible.value = false;
    fetchList();
  } catch (error) {
    ElMessage.error("新增失败");
  }
};

const handleUpdateResult = (row) => {
  resultForm.value = { id: row.id, result: row.result || "" };
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
});
</script>
