<template>
  <div class="app-container">
    <vab-page-header title="诊断模板" description="维护个人常用诊断及 ICD-10 编码" />
    <el-card>
      <div class="page-toolbar"><el-button type="primary" @click="openCreate">新建诊断模板</el-button></div>
      <el-table :data="templates" v-loading="loading" border empty-text="暂无诊断模板">
        <el-table-column prop="code" label="ICD-10 编码" width="160" />
        <el-table-column prop="name" label="诊断名称" />
        <el-table-column prop="update_time" label="更新时间" width="180" />
        <el-table-column label="操作" width="140" fixed="right"><template #default="{ row }"><el-button link type="primary" @click="openEdit(row)">编辑</el-button><el-button link type="danger" @click="remove(row)">删除</el-button></template></el-table-column>
      </el-table>
    </el-card>
    <el-dialog v-model="dialogVisible" :title="editing ? '编辑诊断模板' : '新建诊断模板'" width="500px">
      <el-form ref="formRef" :model="form" :rules="rules" label-width="100px">
        <el-form-item label="ICD-10 编码" prop="code"><el-input v-model="form.code" maxlength="20" placeholder="如 I10" /></el-form-item>
        <el-form-item label="诊断名称" prop="name"><el-input v-model="form.name" maxlength="100" /></el-form-item>
      </el-form>
      <template #footer><el-button @click="dialogVisible = false">取消</el-button><el-button type="primary" :loading="saving" @click="submit">保存</el-button></template>
    </el-dialog>
  </div>
</template>

<script setup>
import { onMounted, ref } from "vue";
import { ElMessage, ElMessageBox } from "element-plus";
import { createDiagnosisTemplate, deleteDiagnosisTemplate, getDiagnosisTemplates, updateDiagnosisTemplate } from "@/api/doctor";

const templates = ref([]);
const loading = ref(false);
const saving = ref(false);
const dialogVisible = ref(false);
const editing = ref(false);
const formRef = ref();
const form = ref({ template_id: null, code: "", name: "" });
const rules = { code: [{ required: true, message: "请输入编码", trigger: "blur" }], name: [{ required: true, message: "请输入诊断名称", trigger: "blur" }] };
const fetchData = async () => { loading.value = true; try { const res = await getDiagnosisTemplates(); templates.value = res.data || []; } catch (error) { ElMessage.error(error?.msg || "诊断模板加载失败"); } finally { loading.value = false; } };
const openCreate = () => { editing.value = false; form.value = { template_id: null, code: "", name: "" }; dialogVisible.value = true; };
const openEdit = (row) => { editing.value = true; form.value = { template_id: row.template_id, code: row.code, name: row.name }; dialogVisible.value = true; };
const submit = async () => { const valid = await formRef.value?.validate().catch(() => false); if (!valid) return; saving.value = true; try { if (editing.value) await updateDiagnosisTemplate(form.value); else await createDiagnosisTemplate(form.value); ElMessage.success("保存成功"); dialogVisible.value = false; await fetchData(); } catch (error) { ElMessage.error(error?.msg || "保存失败"); } finally { saving.value = false; } };
const remove = async (row) => { try { await ElMessageBox.confirm(`确定删除诊断模板“${row.name}”吗？`, "提示", { type: "warning" }); await deleteDiagnosisTemplate({ template_id: row.template_id }); ElMessage.success("删除成功"); await fetchData(); } catch (error) { if (error !== "cancel" && error !== "close") ElMessage.error(error?.msg || "删除失败"); } };
onMounted(fetchData);
</script>
