<template>
  <div class="app-container">
    <vab-page-header title="病历查询" />
    <el-card>
      <el-table :data="list" v-loading="loading">
        <el-table-column prop="uuid" label="病历ID" />
        <el-table-column prop="consultation_time" label="就诊时间" />
        <el-table-column prop="doctor_name" label="医生" />
        <el-table-column prop="symptom" label="症状" show-overflow-tooltip />
        <el-table-column prop="result" label="诊断结果" show-overflow-tooltip />
        <el-table-column label="操作" width="120">
          <template #default="{row}">
            <el-button size="small" @click="viewDetail(row)">查看</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <el-dialog v-model="dialogVisible" title="病历详情" width="600px">
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
import { ref, onMounted } from "vue";
import { getMedicalRecordList, getMedicalRecordDetail } from "@/api/patient";

const list = ref([]);
const loading = ref(false);
const dialogVisible = ref(false);
const detail = ref({});

const fetchList = async () => {
  loading.value = true;
  const res = await getMedicalRecordList();
  list.value = res.data || [];
  loading.value = false;
};

const viewDetail = async (row) => {
  const res = await getMedicalRecordDetail({ medical_record_id: row.uuid });
  detail.value = res.data || {};
  dialogVisible.value = true;
};

onMounted(fetchList);
</script>
