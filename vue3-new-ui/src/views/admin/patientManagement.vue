<template>
  <div class="app-container">
    <vab-page-header title="病人管理" />
    <el-card>
      <el-table :data="paginatedList" v-loading="loading">
        <el-table-column prop="id" label="ID" width="60" />
        <el-table-column prop="name" label="姓名" />
        <el-table-column prop="sex" label="性别" />
        <el-table-column prop="birthday" label="生日" />
        <el-table-column prop="phone" label="手机号" />
        <el-table-column prop="address" label="地址" />
        <el-table-column prop="identity" label="身份证号" />
        <el-table-column label="操作" width="120">
          <template #default="{row}">
            <el-button size="small" @click="handleEdit(row)">编辑</el-button>
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

    <el-dialog v-model="dialogVisible" title="编辑病人" width="500px">
      <el-form :model="form" label-width="100px">
        <el-form-item label="姓名">
          <el-input v-model="form.name" />
        </el-form-item>
        <el-form-item label="性别">
          <el-select v-model="form.sex">
            <el-option label="男" value="男" />
            <el-option label="女" value="女" />
          </el-select>
        </el-form-item>
        <el-form-item label="手机号">
          <el-input v-model="form.phone" />
        </el-form-item>
        <el-form-item label="地址">
          <el-input v-model="form.address" />
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
import { ElMessage } from "element-plus";
import { getPatientList, updatePatient } from "@/api/admin";

const list = ref([]);
const currentPage = ref(1);
const pageSize = ref(10);
const total = ref(0);
const paginatedList = computed(() => {
  const start = (currentPage.value - 1) * pageSize.value;
  return list.value.slice(start, start + pageSize.value);
});

const loading = ref(false);
const dialogVisible = ref(false);
const form = ref({});

const fetchList = async () => {
  loading.value = true;
  const res = await getPatientList();
  list.value = res.data || [];
  total.value = list.value.length;
  loading.value = false;
};

const handleEdit = (row) => {
  form.value = { ...row, patient_id: row.id };
  dialogVisible.value = true;
};

const submit = async () => {
  try {
    await updatePatient(form.value);
    ElMessage.success("更新成功");
    dialogVisible.value = false;
    fetchList();
  } catch (e) {
    ElMessage.error(e.msg || "操作失败");
  }
};

onMounted(fetchList);
</script>
