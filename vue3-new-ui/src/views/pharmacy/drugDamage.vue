<template>
  <div class="app-container">
    <vab-page-header title="药品报损" description="记录过期、破损等药品损耗，审批通过后扣减库存" />
    <el-card>
      <div class="page-toolbar"><el-button type="primary" @click="openCreate">提交报损</el-button><el-button @click="loadData">刷新</el-button></div>
      <el-table :data="records" v-loading="loading" border empty-text="暂无报损记录">
        <el-table-column prop="pharmaceutical_name" label="药品" width="150" /><el-table-column prop="damage_type" label="类型" width="100" /><el-table-column prop="quantity" label="数量" width="80" /><el-table-column prop="batch_no" label="批次" width="120" /><el-table-column prop="reason" label="原因" /><el-table-column prop="status_text" label="状态" width="100" /><el-table-column prop="applicant" label="申请人" width="120" />
        <el-table-column v-if="isAdmin" label="审批" width="150"><template #default="{ row }"><el-button v-if="row.status === 0" link type="success" @click="approve(row)">通过</el-button><el-button v-if="row.status === 0" link type="danger" @click="reject(row)">驳回</el-button></template></el-table-column>
      </el-table>
    </el-card>
    <el-dialog v-model="dialogVisible" title="提交药品报损" width="520px">
      <el-form :model="form" label-width="90px"><el-form-item label="药品" required><el-select v-model="form.pharmaceutical_id" filterable class="form-full-width"><el-option v-for="drug in drugs" :key="drug.id" :label="`${drug.name}（库存${drug.stock}）`" :value="drug.id" /></el-select></el-form-item><el-form-item label="损耗类型"><el-select v-model="form.damage_type" class="form-full-width"><el-option label="过期" value="expired" /><el-option label="破损" value="broken" /><el-option label="污染" value="contaminated" /><el-option label="其他" value="other" /></el-select></el-form-item><el-form-item label="数量" required><el-input-number v-model="form.quantity" :min="1" /></el-form-item><el-form-item label="批次"><el-input v-model="form.batch_no" maxlength="60" /></el-form-item><el-form-item label="原因" required><el-input v-model="form.reason" type="textarea" maxlength="300" /></el-form-item></el-form>
      <template #footer><el-button @click="dialogVisible = false">取消</el-button><el-button type="primary" :loading="saving" @click="submit">提交</el-button></template>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from "vue";
import { ElMessage, ElMessageBox } from "element-plus";
import store from "@/store";
import { approveDrugDamage, createDrugDamage, getDrugDamageList, getPharmaceuticalList, rejectDrugDamage } from "@/api/pharmacy";

const records = ref([]); const drugs = ref([]); const loading = ref(false); const saving = ref(false); const dialogVisible = ref(false); const form = ref({ pharmaceutical_id: null, damage_type: "expired", quantity: 1, batch_no: "", reason: "" });
const isAdmin = computed(() => store.state.user.permissions.some(role => ["admin", "super_admin"].includes(role)));
const loadData = async () => { loading.value = true; try { const res = await getDrugDamageList(); records.value = res.data || []; } catch (e) { ElMessage.error(e.msg || "报损记录加载失败"); } finally { loading.value = false; } };
const openCreate = async () => { const res = await getPharmaceuticalList(); drugs.value = res.data || []; form.value = { pharmaceutical_id: null, damage_type: "expired", quantity: 1, batch_no: "", reason: "" }; dialogVisible.value = true; };
const submit = async () => { if (!form.value.pharmaceutical_id || !form.value.reason.trim()) return ElMessage.warning("请选择药品并填写原因"); saving.value = true; try { await createDrugDamage(form.value); ElMessage.success("报损申请已提交"); dialogVisible.value = false; await loadData(); } catch (e) { ElMessage.error(e.msg || "提交失败"); } finally { saving.value = false; } };
const approve = async row => { try { await ElMessageBox.confirm("审批后将扣减库存，确认通过？", "审批确认", { type: "warning" }); await approveDrugDamage({ damage_id: row.damage_id }); ElMessage.success("审批通过"); await loadData(); } catch (e) { if (e !== "cancel" && e !== "close") ElMessage.error(e.msg || "审批失败"); } };
const reject = async row => { try { await rejectDrugDamage({ damage_id: row.damage_id }); ElMessage.success("已驳回"); await loadData(); } catch (e) { ElMessage.error(e.msg || "驳回失败"); } };
onMounted(loadData);
</script>
