<template>
  <div class="app-container">
    <vab-page-header title="处方模板" description="维护个人常用处方，开方时可一键带入药品" />
    <el-card>
      <div class="page-toolbar"><el-button type="primary" @click="openCreate">新建模板</el-button></div>
      <el-table :data="templates" v-loading="loading" border empty-text="暂无模板">
        <el-table-column prop="name" label="模板名称" width="180" />
        <el-table-column label="药品明细">
          <template #default="{ row }">
            <el-tag v-for="item in row.items" :key="item.id" style="margin-right: 6px;">{{ item.name }} x{{ item.number }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="update_time" label="更新时间" width="180" />
        <el-table-column label="操作" width="160" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" @click="openEdit(row)">编辑</el-button>
            <el-button link type="danger" @click="remove(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <el-dialog v-model="dialogVisible" :title="editing ? '编辑处方模板' : '新建处方模板'" width="680px">
      <el-form ref="formRef" :model="form" :rules="rules" label-width="90px">
        <el-form-item label="模板名称" prop="name"><el-input v-model="form.name" maxlength="50" /></el-form-item>
        <el-form-item label="药品明细" prop="items">
          <div class="item-list">
            <div v-for="(item, index) in form.items" :key="index" class="item-row">
              <el-select v-model="item.id" placeholder="选择药品" filterable style="width: 300px;">
                <el-option v-for="drug in drugs" :key="drug.id" :label="drug.name" :value="drug.id" />
              </el-select>
              <el-input-number v-model="item.number" :min="1" style="width: 130px;" />
              <el-button type="danger" link @click="form.items.splice(index, 1)">删除</el-button>
            </div>
            <el-button type="primary" link @click="form.items.push({ id: null, number: 1 })">添加药品</el-button>
          </div>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="submit">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { onMounted, ref } from "vue";
import { ElMessage, ElMessageBox } from "element-plus";
import { createPrescriptionTemplate, deletePrescriptionTemplate, getPrescriptionTemplates, updatePrescriptionTemplate } from "@/api/doctor";
import { getPharmaceuticalList } from "@/api/pharmacy";

const templates = ref([]);
const drugs = ref([]);
const loading = ref(false);
const saving = ref(false);
const dialogVisible = ref(false);
const editing = ref(false);
const formRef = ref();
const emptyForm = () => ({ template_id: null, name: "", items: [{ id: null, number: 1 }] });
const form = ref(emptyForm());
const rules = {
  name: [{ required: true, message: "请输入模板名称", trigger: "blur" }],
  items: [{ required: true, message: "请至少添加一项药品", trigger: "change" }],
};

const fetchData = async () => {
  loading.value = true;
  try {
    const [templateRes, drugRes] = await Promise.all([getPrescriptionTemplates(), getPharmaceuticalList()]);
    templates.value = templateRes.data || [];
    drugs.value = drugRes.data || [];
  } catch (error) {
    ElMessage.error(error?.msg || "处方模板加载失败");
  } finally {
    loading.value = false;
  }
};

const openCreate = () => { editing.value = false; form.value = emptyForm(); dialogVisible.value = true; };
const openEdit = (row) => { editing.value = true; form.value = { template_id: row.template_id, name: row.name, items: row.items.map((item) => ({ id: item.id, number: item.number })) }; dialogVisible.value = true; };

const submit = async () => {
  const valid = await formRef.value?.validate().catch(() => false);
  if (!valid || !form.value.items.length || form.value.items.some((item) => !item.id || !item.number)) {
    ElMessage.warning("请完整填写药品明细");
    return;
  }
  saving.value = true;
  try {
    if (editing.value) await updatePrescriptionTemplate(form.value);
    else await createPrescriptionTemplate(form.value);
    ElMessage.success("保存成功");
    dialogVisible.value = false;
    await fetchData();
  } catch (error) {
    ElMessage.error(error?.msg || "保存失败");
  } finally {
    saving.value = false;
  }
};

const remove = async (row) => {
  try {
    await ElMessageBox.confirm(`确定删除模板“${row.name}”吗？`, "提示", { type: "warning" });
    await deletePrescriptionTemplate({ template_id: row.template_id });
    ElMessage.success("删除成功");
    await fetchData();
  } catch (error) {
    if (error !== "cancel" && error !== "close") ElMessage.error(error?.msg || "删除失败");
  }
};

onMounted(fetchData);
</script>

<style scoped>
.item-list { width: 100%; }
.item-row { display: flex; gap: 10px; align-items: center; margin-bottom: 10px; }
</style>
