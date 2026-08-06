<template>
  <div class="app-container">
    <vab-page-header title="窗口预约处理" description="挂号员/收费员为患者确认预约或办理预约取消" />
    <el-card>
      <template #header><div class="page-toolbar"><el-input v-model="identity" placeholder="按身份证号查询" clearable size="small" style="width: 240px" @keyup.enter="loadList" /><el-button type="primary" size="small" @click="loadList">查询</el-button><el-button size="small" @click="identity = ''; loadList()">查看全部</el-button></div></template>
      <el-table :data="appointments" v-loading="loading" size="small" empty-text="暂无预约记录"><el-table-column prop="patient_name" label="患者" width="90" /><el-table-column prop="identity" label="身份证号" width="170" /><el-table-column prop="department_name" label="科室" width="100" /><el-table-column prop="doctor_name" label="医生" width="90" /><el-table-column prop="time" label="预约日期" width="110" /><el-table-column prop="prefer_time" label="时段" width="80" /><el-table-column label="确认状态" width="90"><template #default="{ row }"><el-tag :type="row.confirmed ? 'success' : 'warning'" size="small">{{ row.confirmed_text }}</el-tag></template></el-table-column><el-table-column label="预约状态" width="100"><template #default="{ row }"><el-tag :type="row.status === 2 ? 'info' : 'success'" size="small">{{ row.status_text }}</el-tag></template></el-table-column><el-table-column label="操作" width="160"><template #default="{ row }"><el-button v-if="row.status === 0 && !row.confirmed" size="small" type="primary" @click="confirm(row)">确认预约</el-button><el-button v-if="row.status === 0" size="small" type="danger" @click="cancel(row)">取消预约</el-button></template></el-table-column></el-table>
    </el-card>
  </div>
</template>

<script setup>
import { onMounted, ref } from "vue";
import { ElMessage, ElMessageBox } from "element-plus";
import { getWindowAppointments, confirmWindowAppointment, cancelWindowAppointment } from "@/api/charge";

const identity = ref(""); const appointments = ref([]); const loading = ref(false);
const loadList = async () => { loading.value = true; try { appointments.value = (await getWindowAppointments(identity.value.trim())).data || []; } finally { loading.value = false; } };
const confirm = async row => { await confirmWindowAppointment({ uuid: row.uuid }); ElMessage.success("预约已确认"); await loadList(); };
const cancel = async row => { await ElMessageBox.confirm("确认取消该预约吗？", "提示"); await cancelWindowAppointment({ uuid: row.uuid }); ElMessage.success("预约已取消"); await loadList(); };
onMounted(loadList);
</script>
