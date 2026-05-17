<template>
  <div class="app-container">
    <vab-page-header title="报到签到" description="预约患者到院报到签到，管理违约记录" />

    <el-card>
      <el-steps :active="step" finish-status="success" simple>
        <el-step title="验证身份" />
        <el-step title="选择预约" />
        <el-step title="报到成功" />
      </el-steps>

      <!-- Step 1: 输入身份证号 -->
      <div v-if="step === 0" style="margin-top: 20px; text-align: center; max-width: 500px; margin-left: auto; margin-right: auto;">
        <el-form :model="form" label-width="0">
          <el-form-item>
            <el-input
              v-model="form.identity"
              placeholder="请输入患者身份证号"
              size="large"
              clearable
              style="width: 100%"
              @keyup.enter="queryAppointments"
            >
              <template #prefix>
                <el-icon><User /></el-icon>
              </template>
            </el-input>
          </el-form-item>
          <el-form-item>
            <el-button type="primary" size="large" style="width: 100%" @click="queryAppointments" :loading="loading">
              查询预约
            </el-button>
          </el-form-item>
        </el-form>
      </div>

      <!-- Step 2: 选择预约 -->
      <div v-if="step === 1" style="margin-top: 20px;">
        <div style="margin-bottom: 12px; display: flex; justify-content: space-between; align-items: center;">
          <span style="font-weight: bold;">请选择要报到的预约</span>
          <el-button link type="primary" @click="step = 0">返回重填</el-button>
        </div>
        <el-empty v-if="appointments.length === 0" description="暂无待报到预约" />
        <el-card
          v-for="(appt, idx) in appointments"
          :key="idx"
          shadow="hover"
          style="margin-bottom: 12px; cursor: pointer;"
          :class="selectedUuid === appt.uuid ? 'selected-card' : ''"
          @click="selectedUuid = appt.uuid"
        >
          <div style="display: flex; justify-content: space-between; align-items: center;">
            <div>
              <div style="font-size: 16px; font-weight: bold; margin-bottom: 4px;">
                {{ appt.department_name }} - {{ appt.doctor_name }}
              </div>
              <div style="color: #666; font-size: 14px;">
                预约日期: {{ appt.time }} {{ appt.appointment_time }}
                <el-tag size="small" :type="appt.specialist === '专家号' ? 'danger' : 'info'" style="margin-left: 8px;">
                  {{ appt.specialist }}
                </el-tag>
              </div>
            </div>
            <el-radio v-model="selectedUuid" :label="appt.uuid" size="large" />
          </div>
        </el-card>
        <div v-if="appointments.length > 0" style="text-align: center; margin-top: 16px;">
          <el-button type="primary" size="large" @click="submitCheckIn" :disabled="!selectedUuid" :loading="submitting">
            确认报到
          </el-button>
        </div>
      </div>

      <!-- Step 3: 报到成功 -->
      <div v-if="step === 2" style="margin-top: 40px; text-align: center;">
        <el-result icon="success" title="报到成功">
          <template #sub-title>
            <p>您的排队序号为: <span style="font-size: 24px; color: #f56c6c; font-weight: bold;">{{ queueNumber }}</span></p>
            <p style="color: #999; margin-top: 8px;">请前往候诊区等待叫号</p>
          </template>
          <template #extra>
            <el-button type="primary" @click="reset">继续报到</el-button>
          </template>
        </el-result>
      </div>
    </el-card>
  </div>
</template>

<script setup>
import { ref } from "vue";
import { ElMessage } from "element-plus";
import { User } from "@element-plus/icons-vue";
import { checkIn, getAppointmentsForCheckin } from "@/api/checkin";

const step = ref(0);
const form = ref({ identity: "" });
const appointments = ref([]);
const selectedUuid = ref("");
const queueNumber = ref(0);
const loading = ref(false);
const submitting = ref(false);

const queryAppointments = async () => {
  if (!form.value.identity.trim()) {
    ElMessage.warning("请输入身份证号");
    return;
  }
  loading.value = true;
  try {
    const res = await getAppointmentsForCheckin(form.value.identity.trim());
    if (res.code === 200) {
      appointments.value = res.data || [];
      step.value = 1;
      selectedUuid.value = "";
    } else {
      ElMessage.error(res.msg || "查询失败");
    }
  } catch (e) {
    ElMessage.error(e.msg || "查询失败");
  }
  loading.value = false;
};

const submitCheckIn = async () => {
  if (!selectedUuid.value) {
    ElMessage.warning("请选择一个预约");
    return;
  }
  submitting.value = true;
  try {
    const res = await checkIn({ appointment_uuid: selectedUuid.value, identity: form.value.identity.trim() });
    if (res.code === 200) {
      queueNumber.value = res.data?.queue_number || 0;
      step.value = 2;
      ElMessage.success("报到成功");
    } else {
      ElMessage.error(res.msg || "报到失败");
    }
  } catch (e) {
    ElMessage.error(e.msg || "报到失败");
  }
  submitting.value = false;
};

const reset = () => {
  step.value = 0;
  form.value.identity = "";
  appointments.value = [];
  selectedUuid.value = "";
  queueNumber.value = 0;
};
</script>

<style scoped>
.selected-card {
  border: 2px solid #409eff;
  background-color: #f0f9ff;
}
</style>
