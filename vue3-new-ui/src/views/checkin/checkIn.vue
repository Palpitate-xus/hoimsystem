<template>
  <div class="app-container">
    <vab-page-header title="报到签到" description="预约患者到院报到签到，管理违约记录" />
    <el-card>
      <el-form :model="form" label-width="120px">
        <el-form-item label="预约ID">
          <el-input v-model="form.appointment_uuid" placeholder="请输入预约UUID" />
        </el-form-item>
        <el-form-item label="身份证号">
          <el-input v-model="form.identity" placeholder="请输入身份证号" />
        </el-form-item>
        <el-form-item>
          <el-button type="primary" @click="submit">报到</el-button>
        </el-form-item>
      </el-form>
    </el-card>
  </div>
</template>

<script setup>
import { ref } from "vue";
import { ElMessage } from "element-plus";
import { checkIn } from "@/api/checkin";

const form = ref({ appointment_uuid: "", identity: "" });

const submit = async () => {
  try {
    const res = await checkIn(form.value);
    ElMessage.success("报到成功，排队序号: " + (res.data?.queue_number || ""));
    form.value = { appointment_uuid: "", identity: "" };
  } catch (e) {
    ElMessage.error(e.msg || "报到失败");
  }
};
</script>
