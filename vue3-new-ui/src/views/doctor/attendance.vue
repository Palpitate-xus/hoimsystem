<template>
  <div class="app-container">
    <vab-page-header title="医生考勤" description="每日签到签退，查看考勤记录和统计" />
    <el-row :gutter="20" style="margin-bottom: 20px;">
      <el-col :span="12">
        <el-card>
          <template #header>
            <span>今日考勤</span>
          </template>
          <div style="text-align: center; padding: 20px;">
            <el-button type="primary" size="large" @click="handleCheckIn" :disabled="checkedIn">签到</el-button>
            <el-button type="success" size="large" @click="handleCheckOut" :disabled="!checkedIn || checkedOut">签退</el-button>
          </div>
          <div v-if="todayRecord" style="margin-top: 15px;">
            <p>签到时间：{{ todayRecord.check_in_time || "未签到" }}</p>
            <p>签退时间：{{ todayRecord.check_out_time || "未签退" }}</p>
            <p>状态：<el-tag :type="statusTagType(todayRecord.status_code)">{{ todayRecord.status }}</el-tag></p>
          </div>
        </el-card>
      </el-col>
      <el-col :span="12">
        <el-card>
          <template #header>
            <span>考勤统计</span>
          </template>
          <el-descriptions :column="2" border>
            <el-descriptions-item label="正常">{{ stat.normal }}</el-descriptions-item>
            <el-descriptions-item label="迟到">{{ stat.late }}</el-descriptions-item>
            <el-descriptions-item label="早退">{{ stat.early }}</el-descriptions-item>
            <el-descriptions-item label="缺勤">{{ stat.absent }}</el-descriptions-item>
          </el-descriptions>
        </el-card>
      </el-col>
    </el-row>

    <el-card>
      <template #header>
        <span>考勤记录</span>
      </template>
      <el-form :inline="true" class="page-toolbar">
        <el-form-item label="开始日期">
          <el-date-picker v-model="searchForm.start_date" type="date" value-format="YYYY-MM-DD" />
        </el-form-item>
        <el-form-item label="结束日期">
          <el-date-picker v-model="searchForm.end_date" type="date" value-format="YYYY-MM-DD" />
        </el-form-item>
        <el-form-item>
          <el-button type="primary" @click="loadRecords">查询</el-button>
        </el-form-item>
      </el-form>
      <el-table :data="attendanceList" empty-text="暂无记录">
        <el-table-column prop="date" label="日期" sortable />
        <el-table-column prop="check_in_time" label="签到时间" />
        <el-table-column prop="check_out_time" label="签退时间" />
        <el-table-column prop="status" label="状态">
          <template #default="scope">
            <el-tag :type="statusTagType(scope.row.status_code)">{{ scope.row.status }}</el-tag>
          </template>
        </el-table-column>
      </el-table>
    </el-card>
  </div>
</template>

<script setup>
import { ref, onMounted, computed } from "vue";
import { attendanceCheckIn, attendanceCheckOut, getAttendanceList } from "@/api/doctor";
import { ElMessage } from "element-plus";

const attendanceList = ref([]);
const searchForm = ref({ start_date: "", end_date: "" });

const todayRecord = computed(() => {
  const today = new Date().toISOString().split("T")[0];
  return attendanceList.value.find(r => r.date === today);
});

const checkedIn = computed(() => !!todayRecord.value?.check_in_time);
const checkedOut = computed(() => !!todayRecord.value?.check_out_time);

const stat = computed(() => {
  const s = { normal: 0, late: 0, early: 0, absent: 0 };
  attendanceList.value.forEach(r => {
    if (r.status_code === 0) s.normal++;
    else if (r.status_code === 1) s.late++;
    else if (r.status_code === 2) s.early++;
    else if (r.status_code === 3) s.absent++;
  });
  return s;
});

const statusTagType = (code) => {
  const map = { 0: "success", 1: "warning", 2: "warning", 3: "danger" };
  return map[code] || "info";
};

const loadRecords = async () => {
  try {
    const res = await getAttendanceList(searchForm.value);
    attendanceList.value = res.data || [];
  } catch (e) {
    ElMessage.error(e.msg || "查询失败");
  }
};

const handleCheckIn = async () => {
  try {
    const res = await attendanceCheckIn();
    ElMessage.success(res.msg);
    loadRecords();
  } catch (e) {
    ElMessage.error(e.msg || "签到失败");
  }
};

const handleCheckOut = async () => {
  try {
    const res = await attendanceCheckOut();
    ElMessage.success(res.msg);
    loadRecords();
  } catch (e) {
    ElMessage.error(e.msg || "签退失败");
  }
};

onMounted(loadRecords);
</script>
