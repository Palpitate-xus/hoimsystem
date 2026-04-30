<template>
  <div class="app-container">
    <vab-page-header title="病历管理" />
    <el-card>
      <el-button type="primary" @click="handleAdd">新增病历</el-button>
      
      <el-input
        v-model="searchQuery"
        placeholder="搜索..."
        clearable
        style="width: 200px; margin-left: 10px;"
      ></el-input>
      <el-button type="primary" @click="fetchList" style="margin-left: 10px;">搜索</el-button>
      <el-table :data="paginatedList" v-loading="loading" style="margin-top: 15px">
        <el-table-column prop="uuid" label="病历ID"  sortable />
        <el-table-column prop="consultation_time" label="就诊时间"  sortable />
        <el-table-column prop="patient_name" label="患者"  sortable />
        <el-table-column prop="symptom" label="症状" show-overflow-tooltip  sortable />
        <el-table-column prop="result" label="诊断结果" show-overflow-tooltip  sortable />
        <el-table-column label="操作" width="180">
          <template #default="{row}">
            <el-button size="small" @click="handleEdit(row)">编辑</el-button>
            <el-button size="small" @click="viewDetail(row)">详情</el-button>
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

    <el-dialog v-model="dialogVisible" :title="isEdit?'编辑病历':'新增病历'" width="600px">
      <el-form :model="form" label-width="100px">
        <el-form-item label="患者">
          <el-select v-model="form.patient_id" placeholder="请选择患者" style="width:100%" filterable>
            <el-option v-for="p in patientOptions" :key="p.id" :label="p.name" :value="p.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="症状">
          <el-input v-model="form.symptom" type="textarea" :rows="3" />
        </el-form-item>
        <el-form-item label="诊断结果">
          <el-input v-model="form.result" type="textarea" :rows="3" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible=false">取消</el-button>
        <el-button type="primary" @click="submit">确定</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="detailVisible" title="病历详情" width="600px">
      <el-descriptions :column="1" border>
        <el-descriptions-item label="病历ID">{{ detail.uuid }}</el-descriptions-item>
        <el-descriptions-item label="就诊时间">{{ detail.consultation_time }}</el-descriptions-item>
        <el-descriptions-item label="医生">{{ detail.doctor_name }}</el-descriptions-item>
        <el-descriptions-item label="患者">{{ detail.patient_name }}</el-descriptions-item>
        <el-descriptions-item label="症状">{{ detail.symptom }}</el-descriptions-item>
        <el-descriptions-item label="诊断结果">{{ detail.result }}</el-descriptions-item>
      </el-descriptions>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, onMounted, computed } from "vue";
import { ElMessage } from "element-plus";
import { getMedicalRecordList, createMedicalRecord, updateMedicalRecord, getMedicalRecordDetail } from "@/api/doctor";
import { getPatientList } from "@/api/admin";

const list = ref([]);
const searchQuery = ref("");
const currentPage = ref(1);
const pageSize = ref(10);
const total = ref(0);
const paginatedList = computed(() => {
  const start = (currentPage.value - 1) * pageSize.value;
  return list.value.slice(start, start + pageSize.value);
});

const loading = ref(false);
const dialogVisible = ref(false);
const detailVisible = ref(false);
const isEdit = ref(false);
const form = ref({});
const detail = ref({});
const patientOptions = ref([]);

const fetchList = async () => {
  loading.value = true;
  const res = await getMedicalRecordList(searchQuery.value);
  list.value = res.data || [];
  total.value = list.value.length;
  loading.value = false;
};

const handleAdd = () => {
  isEdit.value = false;
  form.value = { patient_id: null, symptom: "", result: "" };
  dialogVisible.value = true;
};

const handleEdit = (row) => {
  isEdit.value = true;
  form.value = { ...row, medical_record_id: row.uuid };
  dialogVisible.value = true;
};

const submit = async () => {
  try {
    if (isEdit.value) {
      await updateMedicalRecord(form.value);
    } else {
      await createMedicalRecord(form.value);
    }
    ElMessage.success("操作成功");
    dialogVisible.value = false;
    fetchList();
  } catch (e) {
    ElMessage.error(e.msg || "操作失败");
  }
};

const viewDetail = async (row) => {
  const res = await getMedicalRecordDetail({ medical_record_id: row.uuid });
  detail.value = res.data || {};
  detailVisible.value = true;
};

const loadPatients = async () => {
  const res = await getPatientList(searchQuery.value);
  patientOptions.value = res.data || [];
};

onMounted(() => {
  fetchList();
  loadPatients();
});
</script>
