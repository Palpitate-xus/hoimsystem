<template>
  <div class="app-container">
    <vab-page-header title="医生管理" />
    <el-card>
      <el-button type="primary" @click="handleAdd">新增医生</el-button>
      
      <el-input
        v-model="searchQuery"
        placeholder="搜索..."
        clearable
        style="width: 200px; margin-left: 10px;"
      ></el-input>
      <el-table :data="paginatedList" v-loading="loading" style="margin-top: 15px">
        <el-table-column prop="id" label="ID" width="60" />
        <el-table-column prop="name" label="姓名" />
        <el-table-column prop="sex" label="性别" :formatter="(row)=>row.sex===0?'女':'男'" />
        <el-table-column prop="title" label="职称" />
        <el-table-column prop="education" label="学历" />
        <el-table-column prop="phone" label="手机号" />
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
        style="margin-top: 15px; justify-content: flex-end;"
      />

    </el-card>

    <el-dialog v-model="dialogVisible" :title="isEdit?'编辑医生':'新增医生'" width="600px">
      <el-form :model="form" label-width="100px">
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
          <el-select v-model="form.department" placeholder="请选择科室" style="width:100%" filterable>
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
const filteredList = computed(() => {
  if (!searchQuery.value) return list.value;
  const kw = searchQuery.value.toLowerCase();
  return list.value.filter((item) =>
    Object.values(item).some((val) =>
      String(val ?? "").toLowerCase().includes(kw)
    )
  );
});

const paginatedList = computed(() => {
  const start = (currentPage.value - 1) * pageSize.value;
  return filteredList.value.slice(start, start + pageSize.value);
});

const loading = ref(false);
const dialogVisible = ref(false);
const isEdit = ref(false);
const form = ref({});

const fetchList = async () => {
  loading.value = true;
  const res = await getDoctorList();
  list.value = res.data || [];
  total.value = filteredList.value.length;
  loading.value = false;
};

const loadDepartments = async () => {
  const res = await getDepartmentList();
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
  });
};

onMounted(fetchList);
</script>
