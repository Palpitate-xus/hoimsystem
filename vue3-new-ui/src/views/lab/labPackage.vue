<template>
  <div class="app-container">
    <vab-page-header title="检验套餐维护" description="维护检验套餐、项目组合及价格，供医生开立检验申请时选择" />
    <el-card>
      <template #header><div class="page-toolbar"><el-input v-model="keyword" placeholder="搜索套餐编码或名称" clearable size="small" style="width: 240px" @keyup.enter="loadList" /><el-button type="primary" size="small" @click="loadList">查询</el-button><el-button v-if="canMaintain" size="small" @click="openCreate">新增套餐</el-button></div></template>
      <el-table :data="packages" v-loading="loading" size="small" empty-text="暂无启用检验套餐">
        <el-table-column prop="code" label="套餐编码" width="130" /><el-table-column prop="name" label="套餐名称" width="150" /><el-table-column prop="category" label="分类" width="120" /><el-table-column prop="items" label="包含项目" show-overflow-tooltip /><el-table-column prop="price" label="价格(元)" width="90" />
        <el-table-column v-if="canMaintain" label="操作" width="80"><template #default="{ row }"><el-button size="small" @click="openEdit(row)">编辑</el-button></template></el-table-column>
      </el-table>
    </el-card>
    <el-dialog v-model="dialogVisible" :title="form.package_id ? '编辑检验套餐' : '新增检验套餐'" width="520px">
      <el-form :model="form" label-width="90px"><el-form-item label="套餐编码" required><el-input v-model="form.code" maxlength="30" /></el-form-item><el-form-item label="套餐名称" required><el-input v-model="form.name" maxlength="100" /></el-form-item><el-form-item label="分类"><el-input v-model="form.category" maxlength="50" /></el-form-item><el-form-item label="包含项目"><el-input v-model="form.items" type="textarea" :rows="2" placeholder="多个项目用逗号分隔" maxlength="1000" /></el-form-item><el-form-item label="价格"><el-input-number v-model="form.price" :min="0" :precision="2" /></el-form-item></el-form>
      <template #footer><el-button @click="dialogVisible = false">取消</el-button><el-button type="primary" @click="save">保存</el-button></template>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from "vue";
import { useStore } from "vuex";
import { ElMessage } from "element-plus";
import { getLabPackageList, createLabPackage, updateLabPackage } from "@/api/labPackage";

const store = useStore(); const permissions = computed(() => store.getters["user/permissions"] || []); const canMaintain = computed(() => permissions.value.some(role => ["admin", "super_admin", "lab_technician"].includes(role)));
const loading = ref(false); const packages = ref([]); const keyword = ref(""); const dialogVisible = ref(false); const form = ref({ package_id: "", code: "", name: "", category: "", items: "", price: 0 });
const loadList = async () => { loading.value = true; try { packages.value = (await getLabPackageList({ keyword: keyword.value })).data || []; } finally { loading.value = false; } };
const openCreate = () => { form.value = { package_id: "", code: "", name: "", category: "", items: "", price: 0 }; dialogVisible.value = true; };
const openEdit = row => { form.value = { ...row }; dialogVisible.value = true; };
const save = async () => { if (!form.value.code.trim() || !form.value.name.trim()) return ElMessage.warning("请填写套餐编码和名称"); if (form.value.package_id) await updateLabPackage(form.value); else await createLabPackage(form.value); ElMessage.success("保存成功"); dialogVisible.value = false; await loadList(); };
onMounted(loadList);
</script>
