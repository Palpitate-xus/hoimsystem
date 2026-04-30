<template>
  <div class="app-container">
    <vab-page-header title="随访管理" />
    <el-card>
      <el-button type="primary" @click="handleAdd">新增随访计划</el-button>
      <el-table :data="paginatedList" v-loading="loading" style="margin-top: 15px">
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
        <el-table-column label="操作" width="200">
          <template #default="{row}">
            <el-button size="small" @click="handleView(row)">查看</el-button>
            <el-button v-if="row.status===0" size="small" type="primary" @click="handleRecord(row)">记录</el-button>
          </template>
        </el-table-column>
      </el-table>
      <el-pagination
        v-model:current-page="currentPage"
        v-model:page-size="pageSize"
        :page-sizes="[10, 20, 50, 100]"
        layout="total, sizes, prev, pager, next, jumper"
        :total="total"
        style="margin-top: 15px; justify-content: flex-end;"
      />

    </el-card>

    <el-dialog v-model="dialogVisible" title="新增随访计划" width="600px">
      <el-form :model="form" label-width="100px">
        <el-form-item label="患者">
          <el-select v-model="form.patient_id" placeholder="请选择患者" style="width:100%">
            <el-option v-for="p in patientOptions" :key="p.id" :label="p.name" :value="p.id" />
          </el-select>
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

    <el-dialog v-model="detailVisible" title="随访详情" width="600px">
      <el-descriptions :column="1" border>
        <el-descriptions-item label="患者">{{ detail.patient_name }}</el-descriptions-item>
        <el-descriptions-item label="计划日期">{{ detail.plan_date }}</el-descriptions-item>
        <el-descriptions-item label="随访内容">{{ detail.content }}</el-descriptions-item>
        <el-descriptions-item label="状态">
          <el-tag v-if="detail.status===0" type="warning">待随访</el-tag>
          <el-tag v-else type="success">已完成</el-tag>
        </el-descriptions-item>
        <el-descriptions-item label="随访结果">{{ detail.result || "—" }}</el-descriptions-item>
        <el-descriptions-item label="患者反馈">{{ detail.patient_feedback || "—" }}</el-descriptions-item>
      </el-descriptions>
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
import { ref, onMounted, computed } from "vue";
import { ElMessage } from "element-plus";
import { getFollowUpList, createFollowUpPlan, recordFollowUp } from "@/api/followup";
import { getPatientList } from "@/api/admin";

const list = ref([]);
const currentPage = ref(1);
const pageSize = ref(10);
const total = ref(0);
const paginatedList = computed(() => {
  const start = (currentPage.value - 1) * pageSize.value;
  return list.value.slice(start, start + pageSize.value);
});

const loading = ref(false);
const dialogVisible = ref(false);
const recordVisible = ref(false);
const detailVisible = ref(false);
const form = ref({});
const recordForm = ref({});
const detail = ref({});
const patientOptions = ref([]);

const fetchList = async () => {
  loading.value = true;
  const res = await getFollowUpList();
  list.value = res.data || [];
  total.value = list.value.length;
  loading.value = false;
};

const handleAdd = () => {
  form.value = { patient_id: null };
  dialogVisible.value = true;
};

const loadPatients = async () => {
  const res = await getPatientList();
  patientOptions.value = res.data || [];
};

onMounted(() => {
  fetchList();
  loadPatients();
});

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

const handleView = (row) => {
  detail.value = { ...row };
  detailVisible.value = true;
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

</script>
