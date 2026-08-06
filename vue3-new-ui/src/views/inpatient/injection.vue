<template>
  <div class="app-container">
    <vab-page-header title="注射管理" description="查看注射医嘱并记录执行完成状态" />
    <el-card>
      <div class="page-toolbar"><el-button @click="fetchList">刷新</el-button></div>
      <el-table :data="orders" v-loading="loading" border empty-text="暂无注射医嘱">
        <el-table-column prop="patient_name" label="患者" width="100" /><el-table-column prop="pharmaceutical_name" label="药品" width="140" /><el-table-column prop="route" label="途径" width="90"><template #default="{ row }">{{ routeText(row.route) }}</template></el-table-column><el-table-column prop="dose" label="剂量" width="100" />
        <el-table-column label="状态" width="90"><template #default="{ row }"><el-tag :type="statusType(row.status)">{{ statusText(row.status) }}</el-tag></template></el-table-column>
        <el-table-column label="操作" width="220"><template #default="{ row }"><el-button v-if="row.status === 0" size="small" type="primary" @click="execute(row)">执行</el-button><el-button v-if="row.status === 1" size="small" type="success" @click="complete(row)">完成</el-button></template></el-table-column>
      </el-table>
    </el-card>
  </div>
</template>

<script setup>
import { onMounted, ref } from "vue";
import { ElMessage } from "element-plus";
import { completeInjection, executeInjection, getInjectionList } from "@/api/nursing";
const orders = ref([]); const loading = ref(false);
const routeText = (route) => ({ im: "肌注", sc: "皮下", id: "皮内" }[route] || route);
const statusText = (status) => ["待执行", "已执行", "已完成", "已取消"][status] || "未知";
const statusType = (status) => ["warning", "primary", "success", "info"][status] || "info";
const fetchList = async () => { loading.value = true; try { const res = await getInjectionList(); orders.value = res.data || []; } catch (error) { ElMessage.error(error?.msg || "注射医嘱加载失败"); } finally { loading.value = false; } };
const execute = async (row) => { try { await executeInjection({ injection_id: row.injection_id }); ElMessage.success("注射已执行"); await fetchList(); } catch (error) { ElMessage.error(error?.msg || "执行失败"); } };
const complete = async (row) => { try { await completeInjection({ injection_id: row.injection_id }); ElMessage.success("注射已完成"); await fetchList(); } catch (error) { ElMessage.error(error?.msg || "完成失败"); } };
onMounted(fetchList);
</script>
