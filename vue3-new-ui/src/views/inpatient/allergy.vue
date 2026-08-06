<template>
  <div class="app-container">
    <vab-page-header title="过敏标识" description="维护患者结构化过敏信息，临床开立医嘱时可快速识别风险" />
    <el-card>
      <div class="page-toolbar">
        <el-input v-model="search" placeholder="按患者或过敏原搜索" clearable class="page-search-input" />
        <el-button type="primary" @click="openCreate">新增过敏标识</el-button>
        <el-button @click="fetchList">刷新</el-button>
      </div>
      <el-table :data="filteredRows" v-loading="loading" border empty-text="暂无过敏标识">
        <el-table-column prop="patient_name" label="患者" width="110" />
        <el-table-column prop="allergen" label="过敏原" width="140" />
        <el-table-column prop="reaction" label="反应表现" min-width="150" />
        <el-table-column prop="severity_text" label="严重程度" width="100"><template #default="{ row }"><el-tag :type="severityType(row.severity)">{{ row.severity_text }}</el-tag></template></el-table-column>
        <el-table-column label="状态" width="90"><template #default="{ row }"><el-tag :type="row.status ? 'danger' : 'info'">{{ row.status_text }}</el-tag></template></el-table-column>
        <el-table-column prop="note" label="备注" min-width="150" />
        <el-table-column label="操作" width="150"><template #default="{ row }"><el-button size="small" @click="openEdit(row)">编辑</el-button><el-button v-if="row.status" size="small" type="danger" @click="disable(row)">停用</el-button></template></el-table-column>
      </el-table>
    </el-card>

    <el-dialog v-model="dialogVisible" :title="form.allergy_id ? '编辑过敏标识' : '新增过敏标识'" width="520px">
      <el-form :model="form" label-width="90px">
        <el-form-item label="患者" required><el-select v-model="form.patient_id" placeholder="请选择患者" filterable style="width: 100%" :disabled="!!form.allergy_id"><el-option v-for="item in patients" :key="item.id" :label="`${item.name}（${item.phone || '无手机号'}）`" :value="item.id" /></el-select></el-form-item>
        <el-form-item label="过敏原" required><el-input v-model="form.allergen" maxlength="100" /></el-form-item>
        <el-form-item label="反应表现" required><el-input v-model="form.reaction" maxlength="200" /></el-form-item>
        <el-form-item label="严重程度"><el-radio-group v-model="form.severity"><el-radio :value="1">轻度</el-radio><el-radio :value="2">中度</el-radio><el-radio :value="3">重度</el-radio></el-radio-group></el-form-item>
        <el-form-item label="备注"><el-input v-model="form.note" type="textarea" maxlength="200" show-word-limit /></el-form-item>
      </el-form>
      <template #footer><el-button @click="dialogVisible = false">取消</el-button><el-button type="primary" @click="submit">保存</el-button></template>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from "vue";
import { ElMessage, ElMessageBox } from "element-plus";
import { getPatientList } from "@/api/admin";
import { createAllergy, disableAllergy, getAllergyList, updateAllergy } from "@/api/clinical";

const rows = ref([]); const patients = ref([]); const search = ref(""); const loading = ref(false); const dialogVisible = ref(false);
const form = ref({ patient_id: null, allergen: "", reaction: "", severity: 1, note: "" });
const filteredRows = computed(() => { const keyword = search.value.trim().toLowerCase(); return keyword ? rows.value.filter((row) => `${row.patient_name}${row.allergen}${row.reaction}`.toLowerCase().includes(keyword)) : rows.value; });
const severityType = (severity) => ["", "warning", "danger", "danger"][severity] || "info";
const fetchList = async () => { loading.value = true; try { const res = await getAllergyList(); rows.value = res.data || []; } catch (error) { ElMessage.error(error?.msg || "过敏标识加载失败"); } finally { loading.value = false; } };
const loadPatients = async () => { const res = await getPatientList(); patients.value = res.data || []; };
const openCreate = () => { form.value = { patient_id: null, allergen: "", reaction: "", severity: 1, note: "" }; dialogVisible.value = true; };
const openEdit = (row) => { form.value = { allergy_id: row.allergy_id, patient_id: row.patient_id, allergen: row.allergen, reaction: row.reaction, severity: row.severity, note: row.note }; dialogVisible.value = true; };
const submit = async () => { if (!form.value.patient_id || !form.value.allergen.trim() || !form.value.reaction.trim()) { ElMessage.warning("请完整填写患者、过敏原和反应表现"); return; } try { if (form.value.allergy_id) await updateAllergy(form.value); else await createAllergy(form.value); ElMessage.success("过敏标识已保存"); dialogVisible.value = false; await fetchList(); } catch (error) { ElMessage.error(error?.msg || "保存失败"); } };
const disable = async (row) => { try { await ElMessageBox.confirm(`确认停用 ${row.patient_name} 的“${row.allergen}”过敏标识？`, "请确认", { type: "warning" }); await disableAllergy({ allergy_id: row.allergy_id }); ElMessage.success("过敏标识已停用"); await fetchList(); } catch (error) { if (error !== "cancel" && error !== "close") ElMessage.error(error?.msg || "停用失败"); } };
onMounted(async () => { await Promise.all([fetchList(), loadPatients()]); });
</script>
