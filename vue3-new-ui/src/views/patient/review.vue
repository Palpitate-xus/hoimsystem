<template>
  <div class="app-container">
    <vab-page-header title="就诊评价" />
    <el-card>
      <el-form :model="form" label-width="100px">
        <el-form-item label="医生">
          <el-select v-model="form.doctor_id" placeholder="请选择医生" style="width:100%">
            <el-option v-for="d in doctorOptions" :key="d.id" :label="d.name" :value="d.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="就诊记录">
          <el-select v-model="form.visit_id" placeholder="请选择就诊记录" style="width:100%">
            <el-option v-for="v in visitOptions" :key="v.medical_record_id" :label="v.visit_time + ' - ' + v.doctor_name + ' - ' + v.diagnosis" :value="v.medical_record_id" />
          </el-select>
        </el-form-item>
        <el-form-item label="评分">
          <el-rate v-model="form.score" :max="5" />
        </el-form-item>
        <el-form-item label="评价内容">
          <el-input v-model="form.comment" type="textarea" :rows="3" />
        </el-form-item>
        <el-form-item>
          <el-button type="primary" @click="submit">提交评价</el-button>
        </el-form-item>
      </el-form>
    </el-card>
  </div>
</template>

<script setup>
import { ref, onMounted } from "vue";
import { ElMessage } from "element-plus";
import { createReview, getVisitRecords } from "@/api/patient";
import { getDoctorList } from "@/api/admin";

const form = ref({ doctor_id: null, visit_id: "", score: 5, comment: "" });
const doctorOptions = ref([]);
const visitOptions = ref([]);

const submit = async () => {
  try {
    await createReview(form.value);
    ElMessage.success("评价成功");
    form.value = { doctor_id: null, visit_id: "", score: 5, comment: "" };
  } catch (e) {
    ElMessage.error(e.msg || "评价失败");
  }
};

const loadDoctors = async () => {
  const res = await getDoctorList();
  doctorOptions.value = res.data || [];
};

const loadVisits = async () => {
  const res = await getVisitRecords();
  visitOptions.value = res.data || [];
};

onMounted(() => {
  loadDoctors();
  loadVisits();
});
</script>
