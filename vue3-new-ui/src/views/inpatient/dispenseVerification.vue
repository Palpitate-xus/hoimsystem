<template>
  <div class="app-container">
    <vab-page-header title="配药核对" description="护士核对药品、剂量与患者信息后确认接收，避免发错药" />
    <el-card>
      <div class="page-toolbar"><el-button @click="fetchList">刷新</el-button></div>
      <el-table :data="records" v-loading="loading" border empty-text="暂无待核对配药记录">
        <el-table-column prop="patient_name" label="患者" width="110" />
        <el-table-column prop="doctor_name" label="开方医生" width="110" />
        <el-table-column label="药品明细" min-width="240"><template #default="{ row }">{{ medicineText(row) }}</template></el-table-column>
        <el-table-column prop="pharmacist_name" label="药师" width="110" />
        <el-table-column label="状态" width="110"><template #default="{ row }"><el-tag :type="row.status ? 'success' : 'warning'">{{ row.status_text }}</el-tag></template></el-table-column>
        <el-table-column prop="note" label="核对备注" min-width="160" />
        <el-table-column label="操作" width="110"><template #default="{ row }"><el-button v-if="row.status === 0" type="primary" size="small" @click="verify(row)">确认核对</el-button></template></el-table-column>
      </el-table>
    </el-card>
  </div>
</template>

<script setup>
import { onMounted, ref } from "vue";
import { ElMessage, ElMessageBox } from "element-plus";
import { getDispenseVerificationList, verifyDispense } from "@/api/pharmacy";

const records = ref([]); const loading = ref(false);
const medicineText = (row) => (row.pharmaceuticals || []).map((item) => `${item.name} × ${item.number}`).join("、") || "-";
const fetchList = async () => { loading.value = true; try { const res = await getDispenseVerificationList(); records.value = res.data || []; } catch (error) { ElMessage.error(error?.msg || "配药核对记录加载失败"); } finally { loading.value = false; } };
const verify = async (row) => { try { const { value } = await ElMessageBox.prompt("可填写核对备注", "确认配药核对", { inputPlaceholder: "药品、剂量、患者均已核对" }); await verifyDispense({ verification_id: row.verification_id, note: value || "药品、剂量、患者均已核对" }); ElMessage.success("配药核对已完成"); await fetchList(); } catch (error) { if (error !== "cancel" && error !== "close") ElMessage.error(error?.msg || "核对失败"); } };
onMounted(fetchList);
</script>
