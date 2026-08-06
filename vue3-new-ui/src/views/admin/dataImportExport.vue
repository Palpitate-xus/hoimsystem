<template>
  <div class="app-container">
    <vab-page-header title="数据导入导出" description="批量维护医生、患者和药品基础数据，导入前请先下载模板" />
    <el-alert title="导入规则" type="info" :closable="false" show-icon>
      每次导入为全量校验：只要有一行错误就不会写入任何数据；医生和患者账号默认密码为 123456，请导入后及时修改。
    </el-alert>
    <el-row :gutter="16" style="margin-top: 16px">
      <el-col v-for="item in entities" :key="item.key" :span="8">
        <el-card shadow="hover" class="import-card">
          <template #header><span>{{ item.label }}</span></template>
          <p class="description">{{ item.description }}</p>
          <div class="actions">
            <el-button @click="download(item.key, true)">下载模板</el-button>
            <el-button type="primary" @click="chooseFile(item.key)">选择 Excel 导入</el-button>
            <el-button type="success" plain @click="download(item.key, false)">导出全部</el-button>
          </div>
          <input :ref="(element) => setInputRef(item.key, element)" type="file" accept=".xlsx,.xlsm" hidden @change="handleImport(item.key, $event)" />
        </el-card>
      </el-col>
    </el-row>
  </div>
</template>

<script setup>
import { reactive } from "vue";
import { ElMessage } from "element-plus";
import { downloadData, importData } from "@/api/dataImportExport";

const entities = [
  { key: "doctors", label: "医生", description: "导入姓名、职称、科室、账号等信息" },
  { key: "patients", label: "患者", description: "导入姓名、身份证号、联系方式和过敏史" },
  { key: "pharmaceuticals", label: "药品", description: "导入库存、价格、有效期和抗菌药物等级" },
];
const inputRefs = reactive({});

const setInputRef = (key, element) => {
  if (element) inputRefs[key] = element;
};

const chooseFile = (key) => inputRefs[key]?.click();

const saveBlob = (blob, filename) => {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  link.click();
  URL.revokeObjectURL(url);
};

const download = async (entity, template) => {
  try {
    const blob = await downloadData(entity, template);
    saveBlob(blob, `${entity}${template ? "_template" : ""}.xlsx`);
  } catch (error) {
    ElMessage.error(error.msg || "下载失败");
  }
};

const handleImport = async (entity, event) => {
  const file = event.target.files?.[0];
  event.target.value = "";
  if (!file) return;
  try {
    const response = await importData(entity, file);
    const result = response.data || {};
    if (response.code === 200) ElMessage.success(`导入成功，共${result.imported}行`);
    else ElMessage.error(`导入失败：${(result.errors || []).join("；")}`);
  } catch (error) {
    ElMessage.error(error.msg || "导入失败");
  }
};
</script>

<style scoped>
.description { color: var(--el-text-color-secondary); min-height: 42px; }
.actions { display: flex; flex-wrap: wrap; gap: 8px; }
.actions .el-button { margin-left: 0; }
</style>
