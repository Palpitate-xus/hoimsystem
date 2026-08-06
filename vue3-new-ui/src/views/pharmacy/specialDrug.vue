<template>
  <div class="app-container">
    <vab-page-header title="特殊药品" description="毒麻精放药品专册登记，申请人与复核人必须为不同账号" />
    <el-card>
      <el-form :model="form" inline @submit.prevent>
        <el-form-item label="药品"><el-select v-model="form.pharmaceutical_id" filterable placeholder="选择药品" style="width: 180px"><el-option v-for="item in drugs" :key="item.id" :label="item.name" :value="item.id" /></el-select></el-form-item>
        <el-form-item label="操作"><el-select v-model="form.action" style="width: 110px"><el-option label="入库" value="in" /><el-option label="发出" value="out" /><el-option label="退回" value="return" /><el-option label="销毁" value="destroy" /></el-select></el-form-item>
        <el-form-item label="数量"><el-input-number v-model="form.quantity" :min="1" /></el-form-item>
        <el-form-item label="原因"><el-input v-model="form.reason" maxlength="200" placeholder="登记原因" style="width: 220px" /></el-form-item>
        <el-form-item><el-button type="primary" @click="submit">提交登记</el-button><el-button @click="fetchList">刷新</el-button></el-form-item>
      </el-form>
    </el-card>
    <el-card>
      <el-table :data="records" v-loading="loading" border empty-text="暂无特殊药品登记">
        <el-table-column prop="pharmaceutical_name" label="药品" width="150" /><el-table-column prop="action_text" label="操作" width="90" /><el-table-column prop="quantity" label="数量" width="80" /><el-table-column prop="reason" label="原因" min-width="180" /><el-table-column prop="applicant_name" label="申请人" width="110" /><el-table-column label="状态" width="110"><template #default="{ row }"><el-tag :type="row.status === 0 ? 'warning' : row.status === 1 ? 'success' : 'info'">{{ row.status_text }}</el-tag></template></el-table-column><el-table-column label="复核" width="170"><template #default="{ row }"><el-button v-if="row.status === 0 && isAdmin" size="small" type="success" @click="approve(row)">确认</el-button><el-button v-if="row.status === 0 && isAdmin" size="small" @click="reject(row)">驳回</el-button><span v-if="row.checker_name">{{ row.checker_name }}</span></template></el-table-column>
      </el-table>
    </el-card>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from "vue";
import { useStore } from "vuex";
import { ElMessage, ElMessageBox } from "element-plus";
import { getPharmaceuticalList, getSpecialDrugList, createSpecialDrug, approveSpecialDrug, rejectSpecialDrug } from "@/api/pharmacy";

const store = useStore(); const isAdmin = computed(() => store.state.user.permissions.some((role) => role === "admin" || role === "super_admin"));
const drugs = ref([]); const records = ref([]); const loading = ref(false); const form = ref({ pharmaceutical_id: null, action: "out", quantity: 1, reason: "" });
const fetchList = async () => { loading.value = true; try { const res = await getSpecialDrugList(); records.value = res.data || []; } catch (error) { ElMessage.error(error?.msg || "登记记录加载失败"); } finally { loading.value = false; } };
const submit = async () => { if (!form.value.pharmaceutical_id || !form.value.reason.trim()) { ElMessage.warning("请选择药品并填写原因"); return; } try { await createSpecialDrug(form.value); ElMessage.success("特殊药品登记已提交"); form.value.reason = ""; await fetchList(); } catch (error) { ElMessage.error(error?.msg || "提交失败"); } };
const approve = async (row) => { try { await approveSpecialDrug({ register_id: row.register_id }); ElMessage.success("已完成双人复核"); await fetchList(); } catch (error) { ElMessage.error(error?.msg || "确认失败"); } };
const reject = async (row) => { try { await ElMessageBox.confirm("确认驳回该特殊药品登记？", "提示", { type: "warning" }); await rejectSpecialDrug({ register_id: row.register_id }); ElMessage.success("登记已驳回"); await fetchList(); } catch (error) { if (error !== "cancel" && error !== "close") ElMessage.error(error?.msg || "驳回失败"); } };
onMounted(async () => { const res = await getPharmaceuticalList(); drugs.value = res.data || []; await fetchList(); });
</script>
