<template>
  <div class="app-container">
    <vab-page-header title="窗口挂号" />
    <el-card>
      <el-form :model="form" label-width="100px">
        <el-form-item label="身份证号">
          <el-input v-model="form.identity" placeholder="病人身份证号" />
        </el-form-item>
        <el-form-item label="排班ID">
          <el-input-number v-model="form.schedule_id" :min="1" />
        </el-form-item>
        <el-form-item label="医生ID">
          <el-input-number v-model="form.doctor_id" :min="1" />
        </el-form-item>
        <el-form-item label="科室ID">
          <el-input-number v-model="form.department_id" :min="1" />
        </el-form-item>
        <el-form-item label="专家号">
          <el-switch v-model="form.specialist" :active-value="1" :inactive-value="0" />
        </el-form-item>
        <el-form-item>
          <el-button type="primary" @click="submit">提交挂号</el-button>
        </el-form-item>
      </el-form>
    </el-card>
  </div>
</template>

<script setup>
import { ref } from "vue";
import { windowRegistration } from "@/api/charge";
import { ElMessage } from "element-plus";

const form = ref({ identity: "", schedule_id: 1, doctor_id: 1, department_id: 1, specialist: 0 });

const submit = async () => {
  try {
    const res = await windowRegistration(form.value);
    ElMessage.success(res.msg);
    form.value = { identity: "", schedule_id: 1, doctor_id: 1, department_id: 1, specialist: 0 };
  } catch (e) {
    ElMessage.error(e.msg || "挂号失败");
  }
};
</script>
