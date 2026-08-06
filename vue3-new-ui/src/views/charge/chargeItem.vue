<template>
  <div class="app-container">
    <vab-page-header title="收费项目" description="维护门诊收费项目及价格，停用项目不应继续用于收费" />
    <el-card>
      <div class="page-toolbar"><el-button v-if="isAdmin" type="primary" @click="openCreate">新增收费项目</el-button><el-button @click="fetchList">刷新</el-button></div>
      <el-table :data="items" v-loading="loading" border empty-text="暂无收费项目"><el-table-column prop="code" label="编码" width="120" /><el-table-column prop="name" label="项目名称" width="180" /><el-table-column prop="category" label="类别" width="120" /><el-table-column prop="price" label="价格(元)" width="110" /><el-table-column label="状态" width="90"><template #default="{ row }"><el-tag :type="row.status ? 'success' : 'info'">{{ row.status_text }}</el-tag></template></el-table-column><el-table-column prop="note" label="备注" min-width="180" /><el-table-column v-if="isAdmin" label="操作" width="160"><template #default="{ row }"><el-button size="small" @click="openEdit(row)">编辑</el-button><el-button size="small" type="warning" @click="toggle(row)">{{ row.status ? "停用" : "启用" }}</el-button></template></el-table-column></el-table>
    </el-card>
    <el-dialog v-model="dialogVisible" :title="form.item_id ? '编辑收费项目' : '新增收费项目'" width="500px"><el-form :model="form" label-width="90px"><el-form-item label="编码" required><el-input v-model="form.code" maxlength="30" /></el-form-item><el-form-item label="名称" required><el-input v-model="form.name" maxlength="100" /></el-form-item><el-form-item label="类别" required><el-input v-model="form.category" maxlength="30" /></el-form-item><el-form-item label="价格" required><el-input-number v-model="form.price" :min="0" :precision="2" /></el-form-item><el-form-item label="备注"><el-input v-model="form.note" maxlength="200" /></el-form-item></el-form><template #footer><el-button @click="dialogVisible = false">取消</el-button><el-button type="primary" @click="submit">保存</el-button></template></el-dialog>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from "vue";
import { useStore } from "vuex";
import { ElMessage, ElMessageBox } from "element-plus";
import { createChargeItem, getChargeItemList, toggleChargeItem, updateChargeItem } from "@/api/charge";

const store = useStore(); const isAdmin = computed(() => store.state.user.permissions.some((role) => role === "admin" || role === "super_admin"));
const items = ref([]); const loading = ref(false); const dialogVisible = ref(false); const form = ref({ code: "", name: "", category: "", price: 0, note: "" });
const fetchList = async () => { loading.value = true; try { const res = await getChargeItemList(); items.value = res.data || []; } catch (error) { ElMessage.error(error?.msg || "收费项目加载失败"); } finally { loading.value = false; } };
const openCreate = () => { form.value = { code: "", name: "", category: "", price: 0, note: "" }; dialogVisible.value = true; };
const openEdit = (row) => { form.value = { item_id: row.item_id, code: row.code, name: row.name, category: row.category, price: row.price, note: row.note }; dialogVisible.value = true; };
const submit = async () => { if (!form.value.code?.trim() || !form.value.name?.trim() || !form.value.category?.trim()) { ElMessage.warning("请完整填写收费项目"); return; } try { if (form.value.item_id) await updateChargeItem(form.value); else await createChargeItem(form.value); ElMessage.success("收费项目已保存"); dialogVisible.value = false; await fetchList(); } catch (error) { ElMessage.error(error?.msg || "保存失败"); } };
const toggle = async (row) => { try { await ElMessageBox.confirm(`确认${row.status ? "停用" : "启用"}“${row.name}”？`, "请确认", { type: "warning" }); await toggleChargeItem({ item_id: row.item_id }); ElMessage.success("状态已更新"); await fetchList(); } catch (error) { if (error !== "cancel" && error !== "close") ElMessage.error(error?.msg || "操作失败"); } };
onMounted(fetchList);
</script>
