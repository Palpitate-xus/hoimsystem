<template>
  <div class="app-container">
    <vab-page-header title="临床路径" description="管理临床路径方案和患者入径记录" />
    <el-card>
      <div class="page-toolbar">
        <el-button type="primary" @click="handleAdd">新增路径</el-button>
      </div>
      <el-table :data="tableData" v-loading="loading" border>
        <el-table-column prop="name" label="路径名称" />
        <el-table-column prop="disease_code" label="疾病编码" />
        <el-table-column prop="disease_name" label="疾病名称" />
        <el-table-column prop="expected_days" label="预计天数" />
        <el-table-column prop="status_text" label="状态" />
        <el-table-column label="操作" width="200">
          <template #default="scope">
            <el-button size="small" type="primary" @click="handleEdit(scope.row)">编辑</el-button>
            <el-button size="small" type="danger" @click="handleDelete(scope.row.id)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <el-dialog v-model="dialogVisible" :title="isEdit ? '编辑临床路径' : '新增临床路径'" width="500px">
      <el-form :model="form" label-width="100px" class="dialog-form">
        <el-form-item label="路径名称">
          <el-input v-model="form.name" />
        </el-form-item>
        <el-form-item label="疾病编码">
          <el-input v-model="form.disease_code" />
        </el-form-item>
        <el-form-item label="疾病名称">
          <el-input v-model="form.disease_name" />
        </el-form-item>
        <el-form-item label="预计天数">
          <el-input-number v-model="form.expected_days" :min="1" />
        </el-form-item>
        <el-form-item label="状态">
          <el-radio-group v-model="form.status">
            <el-radio :label="1">启用</el-radio>
            <el-radio :label="0">停用</el-radio>
          </el-radio-group>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" @click="submitForm">确定</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, onMounted } from "vue";
import { ElMessage, ElMessageBox } from "element-plus";
import { createPathway, getPathwayList, updatePathway, deletePathway } from "@/api/clinicalPathway";

const tableData = ref([]);
const loading = ref(false);
const dialogVisible = ref(false);
const isEdit = ref(false);
const form = ref({
  id: "",
  name: "",
  disease_code: "",
  disease_name: "",
  expected_days: 7,
  status: 1,
});

const fetchList = async () => {
  loading.value = true;
  try {
    const res = await getPathwayList();
    tableData.value = res.data || res;
  } catch (error) {
    ElMessage.error("获取临床路径列表失败");
  }
  loading.value = false;
};

const handleAdd = () => {
  isEdit.value = false;
  form.value = { id: "", name: "", disease_code: "", disease_name: "", expected_days: 7, status: 1 };
  dialogVisible.value = true;
};

const handleEdit = (row) => {
  isEdit.value = true;
  form.value = { ...row };
  dialogVisible.value = true;
};

const submitForm = async () => {
  try {
    if (isEdit.value) {
      await updatePathway(form.value);
      ElMessage.success("更新成功");
    } else {
      await createPathway(form.value);
      ElMessage.success("新增成功");
    }
    dialogVisible.value = false;
    fetchList();
  } catch (error) {
    ElMessage.error(isEdit.value ? "更新失败" : "新增失败");
  }
};

const handleDelete = async (id) => {
  try {
    await ElMessageBox.confirm("确定删除该临床路径吗？", "提示", { type: "warning" });
    await deletePathway({ id });
    ElMessage.success("删除成功");
    fetchList();
  } catch (error) {
    if (error !== "cancel") {
      ElMessage.error("删除失败");
    }
  }
};

onMounted(() => {
  fetchList();
});
</script>
