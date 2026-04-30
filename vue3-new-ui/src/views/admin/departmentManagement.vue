<template>
  <div class="app-container">
    <vab-page-header title="科室管理" />
    <el-card>
      <el-button type="primary" @click="handleAdd">新增科室</el-button>
      
      <el-input
        v-model="searchQuery"
        placeholder="搜索..."
        clearable
        style="width: 200px; margin-left: 10px;"
      ></el-input>
      <el-button type="primary" @click="fetchList" style="margin-left: 10px;">搜索</el-button>
      <el-table :data="paginatedList" v-loading="loading" style="margin-top: 15px">
        <el-table-column prop="id" label="ID" width="60"  sortable />
        <el-table-column prop="name" label="科室名称"  sortable />
        <el-table-column prop="phone" label="电话"  sortable />
        <el-table-column prop="location" label="位置" />
        <el-table-column prop="director" label="主任" />
        <el-table-column label="操作" width="180">
          <template #default="{row}">
            <el-button size="small" @click="handleEdit(row)">编辑</el-button>
            <el-button size="small" type="danger" @click="handleDelete(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
      <el-pagination
        v-model:current-page="currentPage"
        v-model:page-size="pageSize"
        :page-sizes="[10, 20, 50, 100]"
        layout="total, sizes, prev, pager, next, jumper"
        :total="total"
        style="margin-top: 15px; justify-content: flex-end;"
      />

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
        <el-form-item label="主任医生">
          <el-select v-model="form.director" placeholder="请选择主任医生" clearable style="width:100%" filterable>
            <el-option v-for="d in doctorOptions" :key="d.id" :label="d.name" :value="d.id" />
          </el-select>
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
import { ref, onMounted, computed } from "vue";
import { ElMessage, ElMessageBox } from "element-plus";
import { getDepartmentList, createDepartment, updateDepartment, deleteDepartment, getDoctorList } from "@/api/admin";

const list = ref([]);
const searchQuery = ref("");
const currentPage = ref(1);
const pageSize = ref(10);
const total = ref(0);
const paginatedList = computed(() => {
  const start = (currentPage.value - 1) * pageSize.value;
  return list.value.slice(start, start + pageSize.value);
});

const loading = ref(false);
const dialogVisible = ref(false);
const isEdit = ref(false);
const form = ref({});
const doctorOptions = ref([]);

const loadDoctors = async () => {
  const res = await getDoctorList(searchQuery.value);
  doctorOptions.value = res.data || [];
};

const fetchList = async () => {
  loading.value = true;
  const res = await getDepartmentList(searchQuery.value);
  list.value = res.data || [];
  total.value = list.value.length;
  loading.value = false;
};

const handleAdd = () => {
  isEdit.value = false;
  form.value = {};
  loadDoctors();
  dialogVisible.value = true;
};

const handleEdit = (row) => {
  isEdit.value = true;
  form.value = { ...row, department_id: row.id };
  loadDoctors();
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
