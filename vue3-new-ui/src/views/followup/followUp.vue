<template>
  <div class="app-container">
    <vab-page-header title="随访管理" />
    <el-card>
      <el-button type="primary" @click="handleAdd">新增随访计划</el-button>
      <el-table :data="list" v-loading="loading" style="margin-top: 15px">
        <el-table-column prop="id" label="ID" />
        <el-table-column prop="patient_name" label="患者" />
        <el-table-column prop="plan_date" label="计划日期" />
        <el-table-column prop="content" label="随访内容" show-overflow-tooltip />
        <el-table-column prop="status" label="状态">
          <template #default="{row}">
            <el-tag v-if="row.status===0" type="warning">待随访</el-tag>
            <el-tag v-else type="success">已完成</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="180">
          <template #default="{row}">
            <el-button v-if="row.status===0" size="small" type="primary" @click="handleRecord(row)">记录</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <el-dialog v-model="dialogVisible" title="新增随访计划" width="600px">
      <el-form :model="form" label-width="100px">
        <el-form-item label="患者ID">
          <el-input-number v-model="form.patient_id" :min="1" />
        </el-form-item>
        <el-form-item label="计划日期">
          <el-date-picker v-model="form.plan_date" type="date" value-format="YYYY-MM-DD" />
        </el-form-item>
        <el-form-item label="随访内容">
          <el-input v-model="form.content" type="textarea" :rows="3" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible=false">取消</el-button>
        <el-button type="primary" @click="submit">确定</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="recordVisible" title="记录随访结果" width="600px">
      <el-form :model="recordForm" label-width="100px">
        <el-form-item label="随访结果">
          <el-input v-model="recordForm.result" type="textarea" :rows="3" />
        </el-form-item>
        <el-form-item label="患者反馈">
          <el-input v-model="recordForm.patient_feedback" type="textarea" :rows="3" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="recordVisible=false">取消</el-button>
        <el-button type="primary" @click="submitRecord">确定</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, onMounted } from "vue";
import { ElMessage } from "element-plus";
import { getFollowUpList, createFollowUpPlan, recordFollowUp } from "@/api/followup";

const list = ref([]);
const loading = ref(false);
const dialogVisible = ref(false);
const recordVisible = ref(false);
const form = ref({});
const recordForm = ref({});

const fetchList = async () => {
  loading.value = true;
  const res = await getFollowUpList();
  list.value = res.data || [];
  loading.value = false;
};

const handleAdd = () => {
  form.value = { patient_id: 1 };
  dialogVisible.value = true;
};

const submit = async () => {
  try {
    await createFollowUpPlan(form.value);
    ElMessage.success("创建成功");
    dialogVisible.value = false;
    fetchList();
  } catch (e) {
    ElMessage.error(e.msg || "创建失败");
  }
};

const handleRecord = (row) => {
  recordForm.value = { follow_up_id: row.id, result: "", patient_feedback: "" };
  recordVisible.value = true;
};

const submitRecord = async () => {
  try {
    await recordFollowUp(recordForm.value);
    ElMessage.success("记录成功");
    recordVisible.value = false;
    fetchList();
  } catch (e) {
    ElMessage.error(e.msg || "记录失败");
  }
};

onMounted(fetchList);
</script>
