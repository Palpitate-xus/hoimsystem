<template>
  <div class="index-container">
    <el-row :gutter="20">
      <el-col :lg="6" :md="12" :sm="24" :xl="6" :xs="24" v-for="(item, index) in statCards" :key="index">
        <el-card shadow="hover" class="stat-card">
          <div class="stat-content">
            <div class="stat-icon" :style="{ background: item.color }">
              <el-icon :size="28"><component :is="item.icon" /></el-icon>
            </div>
            <div class="stat-info">
              <div class="stat-value">{{ item.value }}</div>
              <div class="stat-label">{{ item.label }}</div>
            </div>
          </div>
        </el-card>
      </el-col>
    </el-row>

    <el-row :gutter="20" style="margin-top: 20px">
      <el-col :lg="16" :md="24" :sm="24" :xl="16" :xs="24">
        <el-card shadow="never">
          <template #header>
            <span>今日门诊概览</span>
          </template>
          <el-descriptions :column="2" border>
            <el-descriptions-item label="今日挂号数">{{ todayStats.registrations }}</el-descriptions-item>
            <el-descriptions-item label="今日预约数">{{ todayStats.appointments }}</el-descriptions-item>
            <el-descriptions-item label="今日收费">¥{{ todayStats.charges }}</el-descriptions-item>
            <el-descriptions-item label="待处理处方">{{ todayStats.pendingPrescriptions }}</el-descriptions-item>
          </el-descriptions>
        </el-card>
      </el-col>
      <el-col :lg="8" :md="24" :sm="24" :xl="8" :xs="24">
        <el-card shadow="never">
          <template #header>
            <span>系统公告</span>
          </template>
          <el-timeline>
            <el-timeline-item
              v-for="(notice, index) in notices"
              :key="index"
              :type="notice.isemergency ? 'danger' : 'primary'"
              :timestamp="notice.sendtime"
            >
              {{ notice.title }}
            </el-timeline-item>
          </el-timeline>
        </el-card>
      </el-col>
    </el-row>

    <el-row :gutter="20" style="margin-top: 20px">
      <el-col :lg="24" :md="24" :sm="24" :xl="24" :xs="24">
        <el-card shadow="never">
          <template #header>
            <span>快捷入口</span>
          </template>
          <div class="quick-actions">
            <el-button type="primary" size="large" @click="goTo('/patient/appointment')">预约挂号</el-button>
            <el-button type="success" size="large" @click="goTo('/patient/registration')">现场挂号</el-button>
            <el-button type="warning" size="large" @click="goTo('/patient/charge')">缴费</el-button>
            <el-button type="info" size="large" @click="goTo('/doctor/medicalRecord')">写病历</el-button>
            <el-button type="danger" size="large" @click="goTo('/doctor/prescription')">开处方</el-button>
            <el-button type="primary" size="large" plain @click="goTo('/pharmacy/dispense')">处方审核</el-button>
          </div>
        </el-card>
      </el-col>
    </el-row>
  </div>
</template>

<script setup>
import { ref, onMounted } from "vue";
import { useRouter } from "vue-router";
import { User, FirstAidKit, Money, Document, Bell, Box, Calendar } from "@element-plus/icons-vue";
import { getNoticeList } from "@/api/admin";
import { getChargeList } from "@/api/charge";
import { getPrescriptionList } from "@/api/doctor";
import { getAppointmentList, getRegistrationList } from "@/api/patient";

const router = useRouter();

const statCards = ref([
  { label: "今日患者", value: 0, icon: "User", color: "#409EFF" },
  { label: "待处理处方", value: 0, icon: "Document", color: "#67C23A" },
  { label: "今日收费", value: "¥0", icon: "Money", color: "#E6A23C" },
  { label: "通知公告", value: 0, icon: "Bell", color: "#F56C6C" },
]);

const todayStats = ref({
  registrations: 0,
  appointments: 0,
  charges: 0,
  pendingPrescriptions: 0,
});

const notices = ref([]);

const goTo = (path) => {
  router.push(path);
};

onMounted(async () => {
  try {
    const [noticeRes, chargeRes, preRes, apptRes, regRes] = await Promise.all([
      getNoticeList(),
      getChargeList(),
      getPrescriptionList(),
      getAppointmentList(),
      getRegistrationList(),
    ]);

    notices.value = (noticeRes.data || []).slice(0, 5);
    statCards.value[3].value = (noticeRes.data || []).length;

    const charges = chargeRes.data || [];
    const todayCharge = charges
      .filter((c) => c.status === 1)
      .reduce((sum, c) => sum + (parseFloat(c.amount) || 0), 0);
    statCards.value[2].value = `¥${todayCharge.toFixed(2)}`;
    todayStats.value.charges = todayCharge.toFixed(2);

    const prescriptions = preRes.data || [];
    const pending = prescriptions.filter((p) => p.status === 0).length;
    statCards.value[1].value = pending;
    todayStats.value.pendingPrescriptions = pending;

    todayStats.value.appointments = (apptRes.data || []).length;
    todayStats.value.registrations = (regRes.data || []).length;
    statCards.value[0].value = todayStats.value.appointments + todayStats.value.registrations;
  } catch (e) {
    console.error("加载首页数据失败", e);
  }
});
</script>

<style lang="scss" scoped>
.index-container {
  padding: 0 !important;
  margin: 0 !important;
}

.stat-card {
  margin-bottom: 15px;

  .stat-content {
    display: flex;
    align-items: center;

    .stat-icon {
      width: 60px;
      height: 60px;
      border-radius: 12px;
      display: flex;
      align-items: center;
      justify-content: center;
      color: #fff;
      margin-right: 15px;
    }

    .stat-info {
      .stat-value {
        font-size: 24px;
        font-weight: 700;
        color: #2c3e50;
      }

      .stat-label {
        font-size: 14px;
        color: #7f8c8d;
        margin-top: 4px;
      }
    }
  }
}

.quick-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 15px;

  .el-button {
    min-width: 120px;
  }
}
</style>
