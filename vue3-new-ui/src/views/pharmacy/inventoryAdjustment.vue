<template>
  <div class="app-container">
    <vab-page-header title="库存调整" description="药品报损、报溢需提交审批后才会变更库存" />
    <el-card>
      <div class="page-toolbar"><el-button type="primary" @click="openCreate">提交调整单</el-button><el-button @click="fetchData">刷新</el-button></div>
      <el-table :data="records" v-loading="loading" border empty-text="暂无库存调整单">
        <el-table-column prop="pharmaceutical_name" label="药品" width="150" />
        <el-table-column label="类型" width="90"><template #default="{ row }"><el-tag :type="row.adjustment_type === 'loss' ? 'danger' : 'success'">{{ row.adjustment_type === "loss" ? "报损" : "报溢" }}</el-tag></template></el-table-column>
        <el-table-column prop="quantity" label="数量" width="80" />
        <el-table-column prop="reason" label="原因" />
        <el-table-column label="状态" width="90"><template #default="{ row }"><el-tag :type="statusType(row.status)">{{ statusText(row.status) }}</el-tag></template></el-table-column>
        <el-table-column prop="applicant" label="申请人" width="130" />
        <el-table-column label="操作" width="140" v-if="isAdmin">
          <template #default="{ row }">
            <el-button v-if="row.status === 0" link type="success" @click="approve(row)">审批通过</el-button>
            <el-button v-if="row.status === 0" link type="danger" @click="reject(row)">驳回</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <el-dialog v-model="dialogVisible" title="提交库存调整单" width="500px">
      <el-form ref="formRef" :model="form" :rules="rules" label-width="90px">
        <el-form-item label="药品" prop="pharmaceutical_id"><el-select v-model="form.pharmaceutical_id" filterable class="form-full-width"><el-option v-for="drug in drugs" :key="drug.id" :label="`${drug.name}（库存${drug.stock}）`" :value="drug.id" /></el-select></el-form-item>
        <el-form-item label="类型" prop="adjustment_type"><el-radio-group v-model="form.adjustment_type"><el-radio value="loss">报损</el-radio><el-radio value="gain">报溢</el-radio></el-radio-group></el-form-item>
        <el-form-item label="数量" prop="quantity"><el-input-number v-model="form.quantity" :min="1" /></el-form-item>
        <el-form-item label="原因" prop="reason"><el-input v-model="form.reason" type="textarea" maxlength="200" /></el-form-item>
      </el-form>
      <template #footer><el-button @click="dialogVisible = false">取消</el-button><el-button type="primary" :loading="saving" @click="submit">提交</el-button></template>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from "vue";
import { ElMessage, ElMessageBox } from "element-plus";
import store from "@/store";
import { approveInventoryAdjustment, createInventoryAdjustment, getInventoryAdjustments, getPharmaceuticalList, rejectInventoryAdjustment } from "@/api/pharmacy";

const records = ref([]);
const drugs = ref([]);
const loading = ref(false);
const saving = ref(false);
const dialogVisible = ref(false);
const formRef = ref();
const form = ref({ pharmaceutical_id: null, adjustment_type: "loss", quantity: 1, reason: "" });
const rules = { pharmaceutical_id: [{ required: true, message: "请选择药品", trigger: "change" }], adjustment_type: [{ required: true, message: "请选择类型", trigger: "change" }], quantity: [{ required: true, message: "请输入数量", trigger: "change" }], reason: [{ required: true, message: "请输入原因", trigger: "blur" }] };
const isAdmin = computed(() => store.state.user.permissions.some((role) => role === "admin" || role === "super_admin"));
const statusText = (status) => ["待审批", "已通过", "已驳回"][status] || "未知";
const statusType = (status) => ["warning", "success", "danger"][status] || "info";

const fetchData = async () => {
  loading.value = true;
  try { const res = await getInventoryAdjustments(); records.value = res.data || []; } catch (error) { ElMessage.error(error?.msg || "调整单加载失败"); } finally { loading.value = false; }
};
const openCreate = async () => { const res = await getPharmaceuticalList(); drugs.value = res.data || []; form.value = { pharmaceutical_id: null, adjustment_type: "loss", quantity: 1, reason: "" }; dialogVisible.value = true; };
const submit = async () => { const valid = await formRef.value?.validate().catch(() => false); if (!valid) return; saving.value = true; try { await createInventoryAdjustment(form.value); ElMessage.success("已提交，等待审批"); dialogVisible.value = false; await fetchData(); } catch (error) { ElMessage.error(error?.msg || "提交失败"); } finally { saving.value = false; } };
const approve = async (row) => { await ElMessageBox.confirm("审批通过后将立即变更库存，确定继续？", "确认审批", { type: "warning" }); try { await approveInventoryAdjustment({ adjustment_id: row.adjustment_id }); ElMessage.success("审批通过"); await fetchData(); } catch (error) { ElMessage.error(error?.msg || "审批失败"); } };
const reject = async (row) => { try { await rejectInventoryAdjustment({ adjustment_id: row.adjustment_id }); ElMessage.success("已驳回"); await fetchData(); } catch (error) { ElMessage.error(error?.msg || "驳回失败"); } };
onMounted(fetchData);
</script>
