<template>
  <div class="app-container">
    <vab-page-header title="双向转诊" description="查看转诊申请状态和转诊记录" />
    <el-card>
      <div class="page-toolbar">
        <el-button type="primary" @click="handleAdd">新增转诊</el-button>
      </div>
      <el-table :data="tableData" v-loading="loading" border>
        <el-table-column prop="patient_name" label="患者姓名" />
        <el-table-column prop="from_department" label="转出科室" />
        <el-table-column prop="to_department" label="转入科室" />
        <el-table-column prop="referral_type" label="转诊类型" />
        <el-table-column prop="status_text" label="状态" />
        <el-table-column label="操作" width="200">
          <template #default="scope">
            <el-button
              v-if="scope.row.status === 1"
              size="small"
              type="success"
              @click="handleUpdateStatus(scope.row.id, 2)"
            >接收</el-button>
            <el-button
              v-if="scope.row.status === 1"
              size="small"
              type="danger"
              @click="handleUpdateStatus(scope.row.id, 3)"
            >退回</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <el-dialog v-model="dialogVisible" title="新增转诊" width="500px">
      <el-form :model="form" label-width="120px" class="dialog-form">
        <el-form-item label="患者">
          <el-input v-model="form.patient_id" placeholder="输入患者姓名或身份证号" />
        </el-form-item>
        <el-form-item label="转出科室">
          <el-select v-model="form.from_department_id" placeholder="请选择转出科室">
            <el-option v-for="item in departmentList" :key="item.department_id" :label="item.department_name" :value="item.department_id" />
          </el-select>
        </el-form-item>
        <el-form-item label="转入科室">
          <el-select v-model="form.to_department_id" placeholder="请选择转入科室">
            <el-option v-for="item in departmentList" :key="item.department_id" :label="item.department_name" :value="item.department_id" />
          </el-select>
        </el-form-item>
        <el-form-item label="转诊类型">
          <el-radio-group v-model="form.referral_type">
            <el-radio label="门诊转诊">门诊转诊</el-radio>
            <el-radio label="住院转诊">住院转诊</el-radio>
            <el-radio label="急诊转诊">急诊转诊</el-radio>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="转诊原因">
          <el-input v-model="form.reason" type="textarea" :rows="3" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" @click="submitForm">确定</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, onMounted } from "vue";
import { ElMessage } from "element-plus";
import { createReferral, getReferralList, updateReferralStatus } from "@/api/referral";
import { getDepartmentList } from "@/api/admin";

const tableData = ref([]);
const loading = ref(false);
const dialogVisible = ref(false);
const departmentList = ref([]);
const form = ref({
  patient_id: "",
  from_department_id: "",
  to_department_id: "",
  referral_type: "门诊转诊",
  reason: "",
});

const fetchList = async () => {
  loading.value = true;
  try {
    const res = await getReferralList();
    tableData.value = res.data || res;
  } catch (error) {
    ElMessage.error("获取转诊列表失败");
  }
  loading.value = false;
};

const handleAdd = () => {
  form.value = { patient_id: "", from_department_id: "", to_department_id: "", referral_type: "门诊转诊", reason: "" };
  dialogVisible.value = true;
};

const submitForm = async () => {
  try {
    await createReferral(form.value);
    ElMessage.success("新增成功");
    dialogVisible.value = false;
    fetchList();
  } catch (error) {
    ElMessage.error("新增失败");
  }
};

const handleUpdateStatus = async (id, status) => {
  try {
    await updateReferralStatus({ id, status });
    ElMessage.success("状态更新成功");
    fetchList();
  } catch (error) {
    ElMessage.error("状态更新失败");
  }
};

const fetchDepartmentList = async () => {
  try {
    const res = await getDepartmentList();
    departmentList.value = res.data || res || [];
  } catch (error) {
    ElMessage.error("获取科室列表失败");
  }
};

onMounted(() => {
  fetchList();
  fetchDepartmentList();
});
</script>
