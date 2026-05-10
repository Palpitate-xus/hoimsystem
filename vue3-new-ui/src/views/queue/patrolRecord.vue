<template>
  <div class="app-container">
    <vab-page-header title="候诊巡视记录" />
    <el-card>
      <el-button type="primary" @click="dialogVisible = true">新增巡视记录</el-button>
      <el-table :data="patrolList" style="margin-top: 15px;">
        <el-table-column prop="patrol_id" label="ID" width="60" />
        <el-table-column prop="nurse_name" label="护士" />
        <el-table-column prop="patient_name" label="病人" />
        <el-table-column prop="content" label="巡视内容" />
        <el-table-column prop="status" label="状态">
          <template #default="{row}">
            <el-tag v-if="row.status === 0" type="success">正常</el-tag>
            <el-tag v-else-if="row.status === 1" type="warning">需关注</el-tag>
            <el-tag v-else type="danger">急诊绿色通道</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="create_time" label="记录时间" sortable />
      </el-table>
    </el-card>

    <el-dialog v-model="dialogVisible" title="新增巡视记录" width="500px">
      <el-form :model="form" label-width="80px">
        <el-form-item label="病人ID">
          <el-input-number v-model="form.patient_id" :min="1" />
        </el-form-item>
        <el-form-item label="巡视内容">
          <el-input v-model="form.content" type="textarea" rows="3" />
        </el-form-item>
        <el-form-item label="状态">
          <el-select v-model="form.status">
            <el-option label="正常" :value="0" />
            <el-option label="需关注" :value="1" />
            <el-option label="急诊绿色通道" :value="2" />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" @click="submit">提交</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, onMounted } from "vue";
import { getPatrolList, createPatrolRecord } from "@/api/queue";
import { ElMessage } from "element-plus";

const patrolList = ref([]);
const dialogVisible = ref(false);
const form = ref({ patient_id: null, content: "", status: 0 });

const loadData = async () => {
  try {
    const res = await getPatrolList();
    patrolList.value = res.data || [];
  } catch (e) {
    ElMessage.error(e.msg || "查询失败");
  }
};

const submit = async () => {
  try {
    await createPatrolRecord(form.value);
    ElMessage.success("记录成功");
    dialogVisible.value = false;
    form.value = { patient_id: null, content: "", status: 0 };
    loadData();
  } catch (e) {
    ElMessage.error(e.msg || "提交失败");
  }
};

onMounted(loadData);
</script>
