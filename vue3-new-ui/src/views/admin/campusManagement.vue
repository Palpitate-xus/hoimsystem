<template>
  <div class="app-container">
    <vab-page-header title="院区管理" description="维护多院区基础信息，删除前需先清理所属科室" />
    <el-card>
      <div class="page-toolbar">
        <el-button type="primary" @click="handleAdd">新增院区</el-button>
        <el-input v-model="keyword" placeholder="搜索编码或名称" clearable class="page-search-input" @keyup.enter="fetchList" />
        <el-button type="primary" @click="fetchList">搜索</el-button>
      </div>
      <el-table :data="list" v-loading="loading" empty-text="暂无院区">
        <el-table-column prop="code" label="院区编码" />
        <el-table-column prop="name" label="院区名称" />
        <el-table-column prop="address" label="地址" />
        <el-table-column prop="phone" label="电话" />
        <el-table-column prop="department_count" label="科室数" width="90" />
        <el-table-column label="状态" width="90">
          <template #default="{ row }">
            <el-tag :type="row.status === 1 ? 'success' : 'info'">{{ row.status === 1 ? '启用' : '停用' }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="180">
          <template #default="{ row }">
            <el-button size="small" @click="handleEdit(row)">编辑</el-button>
            <el-button size="small" type="danger" @click="handleDelete(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <el-dialog v-model="dialogVisible" :title="isEdit ? '编辑院区' : '新增院区'" width="520px">
      <el-form :model="form" label-width="90px" class="dialog-form">
        <el-form-item label="院区编码" required><el-input v-model="form.code" /></el-form-item>
        <el-form-item label="院区名称" required><el-input v-model="form.name" /></el-form-item>
        <el-form-item label="地址"><el-input v-model="form.address" /></el-form-item>
        <el-form-item label="电话"><el-input v-model="form.phone" /></el-form-item>
        <el-form-item label="状态"><el-switch v-model="form.status" :active-value="1" :inactive-value="0" /></el-form-item>
        <el-form-item label="排序"><el-input-number v-model="form.sort_order" :min="0" :max="9999" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" @click="submit">确定</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { onMounted, ref } from "vue";
import { ElMessage, ElMessageBox } from "element-plus";
import { createCampus, deleteCampus, getCampusList, updateCampus } from "@/api/admin";

const keyword = ref("");
const list = ref([]);
const loading = ref(false);
const dialogVisible = ref(false);
const isEdit = ref(false);
const form = ref({ status: 1, sort_order: 0 });

const fetchList = async () => {
  loading.value = true;
  try {
    const res = await getCampusList(keyword.value);
    list.value = res.data || [];
  } finally {
    loading.value = false;
  }
};

const handleAdd = () => {
  isEdit.value = false;
  form.value = { status: 1, sort_order: 0 };
  dialogVisible.value = true;
};

const handleEdit = (row) => {
  isEdit.value = true;
  form.value = { ...row, campus_id: row.id };
  dialogVisible.value = true;
};

const submit = async () => {
  try {
    if (!form.value.code || !form.value.name) {
      ElMessage.warning("院区编码和名称不能为空");
      return;
    }
    if (isEdit.value) await updateCampus(form.value);
    else await createCampus(form.value);
    ElMessage.success("操作成功");
    dialogVisible.value = false;
    await fetchList();
  } catch (error) {
    ElMessage.error(error.msg || "操作失败");
  }
};

const handleDelete = (row) => {
  ElMessageBox.confirm("确认删除该院区？若仍有科室将无法删除。", "提示", { type: "warning" })
    .then(async () => {
      await deleteCampus({ campus_id: row.id });
      ElMessage.success("删除成功");
      await fetchList();
    })
    .catch(() => {});
};

onMounted(fetchList);
</script>
