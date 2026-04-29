<template>
  <div class="app-container">
    <vab-page-header title="就诊评价" />
    <el-card>
      <el-form :model="form" label-width="100px">
        <el-form-item label="医生ID">
          <el-input-number v-model="form.doctor_id" :min="1" />
        </el-form-item>
        <el-form-item label="就诊记录ID">
          <el-input v-model="form.visit_id" />
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
import { ref } from "vue";
import { ElMessage } from "element-plus";
import { createReview } from "@/api/patient";

const form = ref({ doctor_id: 1, visit_id: "", score: 5, comment: "" });

const submit = async () => {
  try {
    await createReview(form.value);
    ElMessage.success("评价成功");
    form.value = { doctor_id: 1, visit_id: "", score: 5, comment: "" };
  } catch (e) {
    ElMessage.error(e.msg || "评价失败");
  }
};
</script>
