<template>
  <div class="app-container">
    <vab-page-header title="检验科管理" />
    <el-tabs v-model="activeTab">
      <el-tab-pane label="待处理申请" name="pending">
        <el-table :data="pendingList" v-loading="loading">
          <el-table-column prop="id" label="申请单ID" />
          <el-table-column prop="patient_name" label="患者" />
          <el-table-column prop="check_type" label="检查类型" />
          <el-table-column prop="create_time" label="申请时间" />
          <el-table-column label="操作" width="120">
            <template #default="{row}">
              <el-button size="small" type="primary" @click="handleResult(row)">录入结果</el-button>
            </template>
          </el-table-column>
        </el-table>
      </el-tab-pane>
      <el-tab-pane label="检查结果" name="results">
        <el-table :data="resultList" v-loading="loading2">
          <el-table-column prop="id" label="结果ID" />
          <el-table-column prop="check_name" label="检查名称" />
          <el-table-column prop="check_time" label="检查时间" />
          <el-table-column prop="result" label="结果" />
          <el-table-column prop="abnormal_flag" label="是否异常">
            <template #default="{row}">
              <el-tag v-if="row.abnormal_flag" type="danger">异常</el-tag>
              <el-tag v-else type="success">正常</el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="technician_name" label="技师" />
        </el-table>
      </el-tab-pane>
    </el-tabs>

    <el-dialog v-model="dialogVisible" title="录入检查结果" width="600px">
      <el-form :model="form" label-width="100px">
        <el-form-item label="申请单ID">
          <el-input v-model="form.lab_order_id" disabled />
        </el-form-item>
        <el-form-item label="样本编号">
          <el-input v-model="form.sample_id" />
        </el-form-item>
        <el-form-item label="检查结果">
          <el-input v-model="form.result" type="textarea" :rows="3" />
        </el-form-item>
        <el-form-item label="是否异常">
          <el-switch v-model="form.abnormal_flag" :active-value="1" :inactive-value="0" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible=false">取消</el-button>
        <el-button type="primary" @click="submit">确定</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, onMounted } from "vue";
import { ElMessage } from "element-plus";
import { getPendingLabOrders, getLabResultList, createLabResult } from "@/api/lab";

const activeTab = ref("pending");
const pendingList = ref([]);
const resultList = ref([]);
const loading = ref(false);
const loading2 = ref(false);
const dialogVisible = ref(false);
const form = ref({});

const fetchPending = async () => {
  loading.value = true;
  const res = await getPendingLabOrders();
  pendingList.value = res.data || [];
  loading.value = false;
};

const fetchResults = async () => {
  loading2.value = true;
  const res = await getLabResultList();
  resultList.value = res.data || [];
  loading2.value = false;
};

const handleResult = (row) => {
  form.value = { lab_order_id: row.id, sample_id: "", result: "", abnormal_flag: 0 };
  dialogVisible.value = true;
};

const submit = async () => {
  try {
    await createLabResult(form.value);
    ElMessage.success("录入成功");
    dialogVisible.value = false;
    fetchPending();
    fetchResults();
  } catch (e) {
    ElMessage.error(e.msg || "录入失败");
  }
};

onMounted(() => {
  fetchPending();
  fetchResults();
});
</script>
