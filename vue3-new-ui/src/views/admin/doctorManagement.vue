<template>
  <div class="app-container">
    <vab-page-header title="医生管理" description="维护医生档案信息，支持新增、编辑和删除操作" />
    <el-card>
      <div class="page-toolbar">
        <el-button type="primary" @click="handleAdd">新增医生</el-button>
        <el-input
          v-model="searchQuery"
          placeholder="搜索医生"
          clearable
          class="page-search-input"
        ></el-input>
        <el-button type="primary" @click="fetchList">搜索</el-button>
      </div>
      <el-table :data="paginatedList" v-loading="loading" empty-text="暂无记录">
        <el-table-column prop="name" label="姓名"  sortable />
        <el-table-column prop="sex" label="性别" :formatter="(row)=>row.sex===0?'女':'男'" sortable />
        <el-table-column prop="title" label="职称"  sortable />
        <el-table-column prop="education" label="学历"  sortable />
        <el-table-column prop="phone" label="手机号"  sortable />
        <el-table-column prop="permission" label="权限" />
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
        class="pagination-wrapper"
      />

    </el-card>

    <el-dialog v-model="dialogVisible" :title="isEdit?'编辑医生':'新增医生'" width="600px">
      <el-form :model="form" label-width="100px" class="dialog-form">
        <el-form-item label="登录用户名" v-if="!isEdit">
          <el-input v-model="form.username" />
        </el-form-item>
        <el-form-item label="密码" v-if="!isEdit">
          <el-input v-model="form.password" type="password" />
        </el-form-item>
        <el-form-item label="姓名">
          <el-input v-model="form.name" />
        </el-form-item>
        <el-form-item label="性别">
          <el-select v-model="form.sex" filterable>
            <el-option label="男" value="男" />
            <el-option label="女" value="女" />
          </el-select>
        </el-form-item>
        <el-form-item label="职称">
          <el-input v-model="form.title" />
        </el-form-item>
        <el-form-item label="学历">
          <el-input v-model="form.education" />
        </el-form-item>
        <el-form-item label="手机号">
          <el-input v-model="form.phone" />
        </el-form-item>
        <el-form-item label="科室">
          <el-select v-model="form.department" placeholder="请选择科室" class="form-full-width" filterable>
            <el-option v-for="d in departmentOptions" :key="d.id" :label="d.name" :value="d.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="权限">
          <el-select v-model="form.permission" filterable>
            <el-option label="普通医生" value="doctor" />
            <el-option label="科室主任" value="director" />
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
import { getDoctorList, registerDoctor, updateDoctor, deleteDoctor, getDepartmentList } from "@/api/admin";

const list = ref([]);
const searchQuery = ref("");
const departmentOptions = ref([]);
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

const fetchList = async () => {
  loading.value = true;
  const res = await getDoctorList(searchQuery.value);
  list.value = res.data || [];
  total.value = list.value.length;
  loading.value = false;
};

const loadDepartments = async () => {
  const res = await getDepartmentList(searchQuery.value);
  departmentOptions.value = res.data || [];
};

const handleAdd = () => {
  isEdit.value = false;
  form.value = { sex: "男", permission: "doctor", department: null };
  loadDepartments();
  dialogVisible.value = true;
};

const handleEdit = (row) => {
  isEdit.value = true;
  form.value = { ...row, sex: row.sex === 0 ? "女" : "男", doctor_id: row.id };
  loadDepartments();
  dialogVisible.value = true;
};

const submit = async () => {
  try {
    if (isEdit.value) {
      await updateDoctor(form.value);
    } else {
      await registerDoctor(form.value);
    }
    ElMessage.success("操作成功");
    dialogVisible.value = false;
    fetchList();
  } catch (e) {
    ElMessage.error(e.msg || "操作失败");
  }
};

const handleDelete = (row) => {
  ElMessageBox.confirm("确认删除该医生？", "提示", { type: "warning" }).then(async () => {
    await deleteDoctor({ doctor_id: row.id });
    ElMessage.success("删除成功");
    fetchList();
  }).catch(() => {});
};

onMounted(fetchList);
</script>
