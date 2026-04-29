<template>
  <div class="app-container">
    <vab-page-header title="健康档案" />
    <el-card>
      <el-descriptions title="基本信息" :column="2" border>
        <el-descriptions-item label="姓名">{{ profile.name }}</el-descriptions-item>
        <el-descriptions-item label="性别">{{ profile.sex }}</el-descriptions-item>
        <el-descriptions-item label="身份证号">{{ profile.identity }}</el-descriptions-item>
        <el-descriptions-item label="生日">{{ profile.birthday }}</el-descriptions-item>
        <el-descriptions-item label="手机号">{{ profile.phone }}</el-descriptions-item>
        <el-descriptions-item label="地址">{{ profile.address }}</el-descriptions-item>
        <el-descriptions-item label="过敏史">{{ profile.allergy_history }}</el-descriptions-item>
      </el-descriptions>
    </el-card>

    <el-card style="margin-top: 20px">
      <template #header>就诊记录</template>
      <el-table :data="visits" v-loading="loading">
        <el-table-column prop="visit_time" label="就诊时间" />
        <el-table-column prop="doctor_name" label="医生" />
        <el-table-column prop="department" label="科室" />
        <el-table-column prop="diagnosis" label="诊断" />
      </el-table>
    </el-card>
  </div>
</template>

<script setup>
import { ref, onMounted } from "vue";
import { getHealthProfile, getVisitRecords } from "@/api/patient";

const profile = ref({});
const visits = ref([]);
const loading = ref(false);

onMounted(async () => {
  const p = await getHealthProfile();
  profile.value = p.data || {};
  loading.value = true;
  const v = await getVisitRecords();
  visits.value = v.data || [];
  loading.value = false;
});
</script>
