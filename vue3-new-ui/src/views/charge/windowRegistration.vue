<template>
  <div class="app-container">
    <vab-page-header title="窗口挂号" description="收费窗口代患者办理现场挂号" />
    <el-card>
      <el-steps :active="step" finish-status="success" simple style="margin-bottom: 20px;">
        <el-step title="验证患者" />
        <el-step title="选择号源" />
        <el-step title="挂号成功" />
      </el-steps>

      <!-- Step 1: 输入身份证号 -->
      <div v-if="step === 0" style="max-width: 400px; margin: 0 auto; text-align: center;">
        <el-input
          v-model="form.identity"
          placeholder="请输入患者身份证号"
          size="large"
          clearable
          @keyup.enter="verifyPatient"
        />
        <el-button type="primary" size="large" style="margin-top: 16px; width: 100%;" @click="verifyPatient" :loading="loading">
          查询患者
        </el-button>
      </div>

      <!-- Step 2: 选择号源 -->
      <div v-if="step === 1">
        <div style="margin-bottom: 12px; display: flex; justify-content: space-between; align-items: center;">
          <span style="font-weight: bold;">患者: {{ patientName }}</span>
          <el-button link type="primary" @click="step = 0">重新输入</el-button>
        </div>
        <el-empty v-if="schedules.length === 0" description="今日暂无可用号源" />
        <el-radio-group v-model="selectedSchedule" v-else>
          <el-card
            v-for="s in schedules"
            :key="s.schedule_id"
            shadow="hover"
            style="margin-bottom: 10px; cursor: pointer;"
            :class="selectedSchedule === s.schedule_id ? 'selected-card' : ''"
            @click="selectedSchedule = s.schedule_id"
          >
            <div style="display: flex; justify-content: space-between; align-items: center;">
              <div>
                <div style="font-size: 15px; font-weight: bold;">
                  {{ s.department_name }} - {{ s.doctor_name }}
                  <el-tag size="small" :type="s.specialist === 1 ? 'danger' : 'info'" style="margin-left: 8px;">
                    {{ s.specialist === 1 ? '专家号' : '普通号' }}
                  </el-tag>
                </div>
                <div style="color: #666; font-size: 13px; margin-top: 4px;">
                  余号: {{ s.number }} | 时段: {{ s.time }}
                </div>
              </div>
              <el-radio :label="s.schedule_id" />
            </div>
          </el-card>
        </el-radio-group>
        <div v-if="schedules.length > 0" style="text-align: center; margin-top: 16px;">
          <el-button type="primary" size="large" @click="submit" :disabled="!selectedSchedule" :loading="submitting">
            确认挂号
          </el-button>
        </div>
      </div>

      <!-- Step 3: 成功 -->
      <div v-if="step === 2" style="text-align: center; margin-top: 40px;">
        <el-result icon="success" title="挂号成功">
          <template #sub-title>
            <p>患者 {{ patientName }} 挂号成功</p>
          </template>
          <template #extra>
            <el-button type="primary" @click="reset">继续挂号</el-button>
          </template>
        </el-result>
      </div>
    </el-card>
  </div>
</template>

<script setup>
import { ref, onMounted } from "vue";
import { ElMessage } from "element-plus";
import { windowRegistration } from "@/api/charge";
import { getScheduleList } from "@/api/doctor";

const step = ref(0);
const form = ref({ identity: "" });
const patientName = ref("");
const schedules = ref([]);
const selectedSchedule = ref(null);
const loading = ref(false);
const submitting = ref(false);

const verifyPatient = async () => {
  if (!form.value.identity.trim()) {
    ElMessage.warning("请输入身份证号");
    return;
  }
  loading.value = true;
  try {
    const res = await getScheduleList();
    if (res.code === 200) {
      schedules.value = (res.data || []).filter(s => s.number > 0);
      patientName.value = "患者";
      step.value = 1;
      selectedSchedule.value = null;
    }
  } catch (e) {
    ElMessage.error(e.msg || "查询失败");
  }
  loading.value = false;
};

const submit = async () => {
  if (!selectedSchedule.value) {
    ElMessage.warning("请选择一个号源");
    return;
  }
  const s = schedules.value.find(x => x.schedule_id === selectedSchedule.value);
  if (!s) return;
  submitting.value = true;
  try {
    const res = await windowRegistration({
      identity: form.value.identity.trim(),
      schedule_id: s.schedule_id,
      doctor_id: s.doctor_id,
      department_id: s.department_id,
      specialist: s.specialist,
    });
    if (res.code === 200) {
      step.value = 2;
      ElMessage.success("挂号成功");
    } else {
      ElMessage.error(res.msg || "挂号失败");
    }
  } catch (e) {
    ElMessage.error(e.msg || "挂号失败");
  }
  submitting.value = false;
};

const reset = () => {
  step.value = 0;
  form.value.identity = "";
  patientName.value = "";
  schedules.value = [];
  selectedSchedule.value = null;
};

onMounted(() => {});
</script>

<style scoped>
.selected-card {
  border: 2px solid #409eff;
  background-color: #f0f9ff;
}
</style>
