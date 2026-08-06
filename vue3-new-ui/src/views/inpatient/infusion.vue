<template>
  <div class="app-container">
    <vab-page-header title="输液管理" description="执行输液医嘱、记录巡视滴速并完成输液" />
    <el-card>
      <div class="page-toolbar"><el-button @click="fetchList">刷新</el-button></div>
      <el-table :data="orders" v-loading="loading" border empty-text="暂无输液医嘱">
        <el-table-column prop="patient_name" label="患者" width="100" />
        <el-table-column prop="pharmaceutical_name" label="药品" width="130" />
        <el-table-column prop="dose" label="剂量" width="100" />
        <el-table-column prop="batch_no" label="批次" width="110" />
        <el-table-column label="状态" width="100"><template #default="{ row }"><el-tag :type="statusType(row.status)">{{ statusText(row.status) }}</el-tag></template></el-table-column>
        <el-table-column prop="drip_rate" label="滴速(滴/分)" width="110" />
        <el-table-column label="操作" min-width="230">
          <template #default="{ row }">
            <el-button v-if="row.status === 0" size="small" type="primary" @click="execute(row)">开始输液</el-button>
            <el-button v-if="row.status === 1" size="small" type="warning" @click="observe(row)">巡视记录</el-button>
            <el-button v-if="row.status === 1" size="small" type="success" @click="complete(row)">结束输液</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>
  </div>
</template>

<script setup>
import { onMounted, ref } from "vue";
import { ElMessage, ElMessageBox } from "element-plus";
import { completeInfusion, executeInfusion, getInfusionList, observeInfusion } from "@/api/nursing";

const orders = ref([]);
const loading = ref(false);
const statusText = (status) => ["待执行", "输液中", "已结束", "已取消"][status] || "未知";
const statusType = (status) => ["warning", "primary", "success", "info"][status] || "info";
const fetchList = async () => { loading.value = true; try { const res = await getInfusionList(); orders.value = res.data || []; } catch (error) { ElMessage.error(error?.msg || "输液医嘱加载失败"); } finally { loading.value = false; } };
const execute = async (row) => { try { await executeInfusion({ infusion_id: row.infusion_id }); ElMessage.success("已开始输液"); await fetchList(); } catch (error) { ElMessage.error(error?.msg || "执行失败"); } };
const observe = async (row) => { try { const { value } = await ElMessageBox.prompt("请输入巡视情况", "巡视记录", { inputValue: "滴速平稳，无不适", inputPlaceholder: "患者情况", inputValidator: (v) => !!v?.trim() || "请输入巡视情况" }); await observeInfusion({ infusion_id: row.infusion_id, drip_rate: row.drip_rate || 1, condition: value }); ElMessage.success("巡视已记录"); await fetchList(); } catch (error) { if (error !== "cancel" && error !== "close") ElMessage.error(error?.msg || "巡视失败"); } };
const complete = async (row) => { try { await ElMessageBox.confirm("确认结束该患者输液吗？", "提示", { type: "warning" }); await completeInfusion({ infusion_id: row.infusion_id }); ElMessage.success("输液已结束"); await fetchList(); } catch (error) { if (error !== "cancel" && error !== "close") ElMessage.error(error?.msg || "结束失败"); } };
onMounted(fetchList);
</script>
