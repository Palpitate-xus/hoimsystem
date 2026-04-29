<template>
  <div class="app-container">
    <vab-page-header title="系统参数" />
    <el-card>
      <el-table :data="list" v-loading="loading">
        <el-table-column prop="config_key" label="参数键" />
        <el-table-column prop="config_value" label="参数值" />
        <el-table-column prop="description" label="说明" />
        <el-table-column label="操作" width="120">
          <template #default="{row}">
            <el-button size="small" @click="handleEdit(row)">编辑</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <el-dialog v-model="dialogVisible" title="编辑参数" width="500px">
      <el-form :model="form" label-width="100px">
        <el-form-item label="参数键">
          <el-input v-model="form.config_key" disabled />
        </el-form-item>
        <el-form-item label="参数值">
          <el-input v-model="form.config_value" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible=false">取消</el-button>
        <el-button type="primary" @click="submit">确定</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, onMounted } from "vue";
import { ElMessage } from "element-plus";
import { getConfigList, updateConfig } from "@/api/system";

const list = ref([]);
const loading = ref(false);
const dialogVisible = ref(false);
const form = ref({});

const fetchList = async () => {
  loading.value = true;
  const res = await getConfigList();
  list.value = res.data || [];
  loading.value = false;
};

const handleEdit = (row) => {
  form.value = { ...row };
  dialogVisible.value = true;
};

const submit = async () => {
  try {
    await updateConfig(form.value);
    ElMessage.success("更新成功");
    dialogVisible.value = false;
    fetchList();
  } catch (e) {
    ElMessage.error(e.msg || "更新失败");
  }
};

onMounted(fetchList);
</script>
