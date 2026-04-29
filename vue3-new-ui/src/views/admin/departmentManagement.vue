<template>
  <div class="app-container">
    <vab-page-header title="科室管理" />
    <el-card>
      <el-button type="primary" @click="handleAdd">新增科室</el-button>
      <el-table :data="list" v-loading="loading" style="margin-top: 15px">
        <el-table-column prop="id" label="ID" width="60" />
        <el-table-column prop="name" label="科室名称" />
        <el-table-column prop="phone" label="电话" />
        <el-table-column prop="location" label="位置" />
        <el-table-column prop="director" label="主任" />
        <el-table-column label="操作" width="180">
          <template #default="{row}">
            <el-button size="small" @click="handleEdit(row)">编辑</el-button>
            <el-button size="small" type="danger" @click="handleDelete(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <el-dialog v-model="dialogVisible" :title="isEdit?'编辑科室':'新增科室'" width="500px">
      <el-form :model="form" label-width="100px">
        <el-form-item label="科室名称">
          <el-input v-model="form.name" />
        </el-form-item>
        <el-form-item label="电话">
          <el-input v-model="form.phone" />
        </el-form-item>
        <el-form-item label="位置">
          <el-input v-model="form.location" />
        </el-form-item>
        <el-form-item label="主任医生ID">
          <el-input-number v-model="form.director" :min="0" />
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
import { ElMessage, ElMessageBox } from "element-plus";
import { getDepartmentList, createDepartment, updateDepartment, deleteDepartment } from "@/api/admin";

const list = ref([]);
const loading = ref(false);
const dialogVisible = ref(false);
const isEdit = ref(false);
const form = ref({});

const fetchList = async () => {
  loading.value = true;
  const res = await getDepartmentList();
  list.value = res.data || [];
  loading.value = false;
};

const handleAdd = () => {
  isEdit.value = false;
  form.value = {};
  dialogVisible.value = true;
};

const handleEdit = (row) => {
  isEdit.value = true;
  form.value = { ...row, department_id: row.id };
  dialogVisible.value = true;
};

const submit = async () => {
  try {
    if (isEdit.value) {
      await updateDepartment(form.value);
    } else {
      await createDepartment(form.value);
    }
    ElMessage.success("操作成功");
    dialogVisible.value = false;
    fetchList();
  } catch (e) {
    ElMessage.error(e.msg || "操作失败");
  }
};

const handleDelete = (row) => {
  ElMessageBox.confirm("确认删除该科室？", "提示", { type: "warning" }).then(async () => {
    await deleteDepartment({ department_id: row.id });
    ElMessage.success("删除成功");
    fetchList();
  });
};

onMounted(fetchList);
</script>
