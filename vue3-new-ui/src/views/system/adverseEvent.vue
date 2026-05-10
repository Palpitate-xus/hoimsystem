<template>
  <div class="app-container">
    <vab-page-header title="不良事件上报" />
    <el-card>
      <div style="margin-bottom: 16px;">
        <el-button type="primary" @click="handleAdd">新增不良事件</el-button>
      </div>
      <el-table :data="tableData" v-loading="loading" border>
        <el-table-column prop="event_type" label="事件类型" />
        <el-table-column prop="patient_name" label="患者姓名" />
        <el-table-column prop="description" label="描述" show-overflow-tooltip />
        <el-table-column prop="severity_text" label="严重程度" />
        <el-table-column prop="status_text" label="状态" />
        <el-table-column label="操作" width="200">
          <template #default="scope">
            <el-button
              v-if="scope.row.status === 1"
              size="small"
              type="warning"
              @click="handleUpdateStatus(scope.row.id, 2)"
            >确认</el-button>
            <el-button
              v-if="scope.row.status === 2"
              size="small"
              type="success"
              @click="handleUpdateStatus(scope.row.id, 3)"
            >处理</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <el-dialog v-model="dialogVisible" title="新增不良事件" width="500px">
      <el-form :model="form" label-width="100px">
        <el-form-item label="事件类型">
          <el-select v-model="form.event_type" placeholder="请选择事件类型">
            <el-option label="用药错误" value="用药错误" />
            <el-option label="跌倒/坠床" value="跌倒/坠床" />
            <el-option label="手术并发症" value="手术并发症" />
            <el-option label="院内感染" value="院内感染" />
            <el-option label="设备故障" value="设备故障" />
            <el-option label="其他" value="其他" />
          </el-select>
        </el-form-item>
        <el-form-item label="患者ID">
          <el-input v-model="form.patient_id" />
        </el-form-item>
        <el-form-item label="描述">
          <el-input v-model="form.description" type="textarea" :rows="3" />
        </el-form-item>
        <el-form-item label="严重程度">
          <el-radio-group v-model="form.severity">
            <el-radio :label="1">轻度</el-radio>
            <el-radio :label="2">中度</el-radio>
            <el-radio :label="3">重度</el-radio>
          </el-radio-group>
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
import { createAdverseEvent, getAdverseEventList, updateEventStatus } from "@/api/adverseEvent";

const tableData = ref([]);
const loading = ref(false);
const dialogVisible = ref(false);
const form = ref({
  event_type: "",
  patient_id: "",
  description: "",
  severity: 1,
});

const fetchList = async () => {
  loading.value = true;
  try {
    const res = await getAdverseEventList();
    tableData.value = res.data || res;
  } catch (error) {
    ElMessage.error("获取不良事件列表失败");
  }
  loading.value = false;
};

const handleAdd = () => {
  form.value = { event_type: "", patient_id: "", description: "", severity: 1 };
  dialogVisible.value = true;
};

const submitForm = async () => {
  try {
    await createAdverseEvent(form.value);
    ElMessage.success("新增成功");
    dialogVisible.value = false;
    fetchList();
  } catch (error) {
    ElMessage.error("新增失败");
  }
};

const handleUpdateStatus = async (id, status) => {
  try {
    await updateEventStatus({ id, status });
    ElMessage.success("状态更新成功");
    fetchList();
  } catch (error) {
    ElMessage.error("状态更新失败");
  }
};

onMounted(() => {
  fetchList();
});
</script>
