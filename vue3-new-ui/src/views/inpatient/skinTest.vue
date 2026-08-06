<template>
  <div class="app-container">
    <vab-page-header title="皮试管理" description="执行皮试医嘱并记录观察结果，结果判定后不可重复修改" />
    <el-card>
      <div class="page-toolbar"><el-button @click="fetchList">刷新</el-button></div>
      <el-table :data="orders" v-loading="loading" border empty-text="暂无皮试医嘱">
        <el-table-column prop="patient_name" label="患者" width="100" />
        <el-table-column prop="pharmaceutical_name" label="药品" width="140" />
        <el-table-column prop="dose" label="剂量" width="100" />
        <el-table-column prop="site" label="部位" width="100" />
        <el-table-column prop="observe_minutes" label="观察(分钟)" width="110" />
        <el-table-column label="状态" width="100"><template #default="{ row }"><el-tag :type="statusType(row.status)">{{ statusText(row.status) }}</el-tag></template></el-table-column>
        <el-table-column prop="result_note" label="判定备注" min-width="140" />
        <el-table-column label="操作" min-width="260">
          <template #default="{ row }">
            <el-button v-if="row.status === 0" size="small" type="primary" @click="administer(row)">执行皮试</el-button>
            <template v-if="row.status === 1">
              <el-button size="small" type="success" @click="assess(row, 'negative')">阴性</el-button>
              <el-button size="small" type="danger" @click="assess(row, 'positive')">阳性</el-button>
              <el-button size="small" @click="assess(row, 'invalid')">无效</el-button>
            </template>
          </template>
        </el-table-column>
      </el-table>
    </el-card>
  </div>
</template>

<script setup>
import { onMounted, ref } from "vue";
import { ElMessage, ElMessageBox } from "element-plus";
import { administerSkinTest, assessSkinTest, getSkinTestList } from "@/api/nursing";

const orders = ref([]);
const loading = ref(false);
const statusText = (status) => ["待执行", "待判定", "阴性", "阳性", "无效", "已取消"][status] || "未知";
const statusType = (status) => ["warning", "primary", "success", "danger", "info", "info"][status] || "info";
const fetchList = async () => { loading.value = true; try { const res = await getSkinTestList(); orders.value = res.data || []; } catch (error) { ElMessage.error(error?.msg || "皮试医嘱加载失败"); } finally { loading.value = false; } };
const administer = async (row) => { try { await administerSkinTest({ skin_test_id: row.skin_test_id }); ElMessage.success("皮试已执行，请按规定时间观察"); await fetchList(); } catch (error) { ElMessage.error(error?.msg || "执行失败"); } };
const assess = async (row, result) => { try { const { value } = await ElMessageBox.prompt("请输入观察备注（可选）", "判定皮试结果", { inputValue: result === "positive" ? "出现阳性反应" : "未见异常", inputValidator: (v) => v.length <= 200 || "备注不能超过200字" }); await assessSkinTest({ skin_test_id: row.skin_test_id, result, note: value || "" }); ElMessage.success("皮试结果已记录"); await fetchList(); } catch (error) { if (error !== "cancel" && error !== "close") ElMessage.error(error?.msg || "结果记录失败"); } };
onMounted(fetchList);
</script>
