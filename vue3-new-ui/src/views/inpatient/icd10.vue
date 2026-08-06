<template>
  <div class="app-container">
    <vab-page-header title="ICD-10 编码" description="诊断和手术操作编码查询，支持维护常用编码" />
    <el-card>
      <template #header>
        <div class="page-toolbar">
          <el-input v-model="keyword" placeholder="按编码、名称或分类搜索" clearable size="small" style="width: 260px" @keyup.enter="loadList" />
          <el-button type="primary" size="small" @click="loadList">查询</el-button>
          <el-button v-if="canMaintain" size="small" @click="openCreate">新增编码</el-button>
        </div>
      </template>
      <el-tabs v-model="activeTab" @tab-change="loadList">
        <el-tab-pane label="诊断编码" name="diagnosis">
          <el-table :data="diagnosisList" v-loading="loading" size="small" empty-text="暂无诊断编码">
            <el-table-column prop="code" label="ICD-10 编码" width="150" /><el-table-column prop="name" label="诊断名称" /><el-table-column prop="category" label="分类" width="160" />
            <el-table-column v-if="canMaintain" label="操作" width="80"><template #default="{ row }"><el-button size="small" @click="openEdit(row)">编辑</el-button></template></el-table-column>
          </el-table>
        </el-tab-pane>
        <el-tab-pane label="手术操作编码" name="operation">
          <el-table :data="operationList" v-loading="loading" size="small" empty-text="暂无手术操作编码">
            <el-table-column prop="code" label="操作编码" width="150" /><el-table-column prop="name" label="操作名称" /><el-table-column prop="category" label="分类" width="160" />
            <el-table-column v-if="canMaintain" label="操作" width="80"><template #default="{ row }"><el-button size="small" @click="openEdit(row)">编辑</el-button></template></el-table-column>
          </el-table>
        </el-tab-pane>
      </el-tabs>
    </el-card>
    <el-dialog v-model="dialogVisible" :title="form.id ? '编辑编码' : '新增编码'" width="480px">
      <el-form :model="form" label-width="90px"><el-form-item label="编码" required><el-input v-model="form.code" maxlength="20" /></el-form-item><el-form-item label="名称" required><el-input v-model="form.name" maxlength="200" /></el-form-item><el-form-item label="分类"><el-input v-model="form.category" maxlength="100" /></el-form-item></el-form>
      <template #footer><el-button @click="dialogVisible = false">取消</el-button><el-button type="primary" @click="save">保存</el-button></template>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from "vue";
import { useStore } from "vuex";
import { ElMessage } from "element-plus";
import { getIcd10DiagnosisList, createIcd10Diagnosis, updateIcd10Diagnosis, getIcd10OperationList, createIcd10Operation, updateIcd10Operation } from "@/api/icd10";

const store = useStore(); const permissions = computed(() => store.getters["user/permissions"] || []); const canMaintain = computed(() => permissions.value.some(role => ["admin", "super_admin", "director"].includes(role)));
const activeTab = ref("diagnosis"); const keyword = ref(""); const loading = ref(false); const diagnosisList = ref([]); const operationList = ref([]); const dialogVisible = ref(false); const form = ref({ id: "", code: "", name: "", category: "" });
const loadList = async () => { loading.value = true; try { const res = activeTab.value === "diagnosis" ? await getIcd10DiagnosisList({ keyword: keyword.value }) : await getIcd10OperationList({ keyword: keyword.value }); if (activeTab.value === "diagnosis") diagnosisList.value = res.data || []; else operationList.value = res.data || []; } finally { loading.value = false; } };
const openCreate = () => { form.value = { id: "", code: "", name: "", category: "" }; dialogVisible.value = true; };
const openEdit = row => { form.value = { ...row }; dialogVisible.value = true; };
const save = async () => { if (!form.value.code.trim() || !form.value.name.trim()) return ElMessage.warning("请填写编码和名称"); const edit = activeTab.value === "diagnosis"; if (edit) await (form.value.id ? updateIcd10Diagnosis(form.value) : createIcd10Diagnosis(form.value)); else await (form.value.id ? updateIcd10Operation(form.value) : createIcd10Operation(form.value)); ElMessage.success("保存成功"); dialogVisible.value = false; await loadList(); };
onMounted(loadList);
</script>
