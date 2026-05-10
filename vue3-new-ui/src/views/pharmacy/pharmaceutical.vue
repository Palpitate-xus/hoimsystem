<template>
  <div class="app-container">
    <vab-page-header title="药品管理" />
    <el-card>
      <el-button type="primary" @click="handleAdd">新增药品</el-button>
      
      <el-input
        v-model="searchQuery"
        placeholder="搜索..."
        clearable
        style="width: 200px; margin-left: 10px;"
      ></el-input>
      <el-button type="primary" @click="fetchList" style="margin-left: 10px;">搜索</el-button>
      <el-table :data="paginatedList" v-loading="loading" style="margin-top: 15px">
        <el-table-column prop="id" label="ID"  sortable />
        <el-table-column prop="name" label="药品名称"  sortable />
        <el-table-column prop="stock" label="库存"  sortable />
        <el-table-column prop="price" label="单价"  sortable />
        <el-table-column prop="expireddate" label="过期日期" />
        <el-table-column prop="supplier" label="供应商" />
        <el-table-column prop="antibiotic_level" label="抗菌级别" width="100">
          <template #default="{row}">
            <el-tag v-if="row.antibiotic_level===0" type="info">非抗菌</el-tag>
            <el-tag v-else-if="row.antibiotic_level===1" type="success">非限制</el-tag>
            <el-tag v-else-if="row.antibiotic_level===2" type="warning">限制级</el-tag>
            <el-tag v-else type="danger">特殊级</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="remark" label="备注" />
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

    <el-dialog v-model="dialogVisible" :title="isEdit?'编辑药品':'新增药品'" width="600px">
      <el-form :model="form" label-width="100px">
        <el-form-item label="药品名称">
          <el-input v-model="form.name" />
        </el-form-item>
        <el-form-item label="库存">
          <el-input-number v-model="form.stock" :min="0" />
        </el-form-item>
        <el-form-item label="单价">
          <el-input v-model="form.price" />
        </el-form-item>
        <el-form-item label="过期日期">
          <el-date-picker v-model="form.expireddate" type="date" value-format="YYYY-MM-DD" />
        </el-form-item>
        <el-form-item label="供应商">
          <el-input v-model="form.supplier" />
        </el-form-item>
        <el-form-item label="抗菌级别">
          <el-radio-group v-model="form.antibiotic_level">
            <el-radio :label="0">非抗菌药</el-radio>
            <el-radio :label="1">非限制级</el-radio>
            <el-radio :label="2">限制级</el-radio>
            <el-radio :label="3">特殊使用级</el-radio>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="备注">
          <el-input v-model="form.remark" />
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
import { getPharmaceuticalList, createPharmaceutical, updatePharmaceutical, deletePharmaceutical } from "@/api/pharmacy";

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

const fetchList = async () => {
  loading.value = true;
  const res = await getPharmaceuticalList(searchQuery.value);
  list.value = res.data || [];
  total.value = list.value.length;
  loading.value = false;
};

const handleAdd = () => {
  isEdit.value = false;
  form.value = { stock: 0, price: "0", antibiotic_level: 0 };
  dialogVisible.value = true;
};

const handleEdit = (row) => {
  isEdit.value = true;
  form.value = { ...row, pharmaceutical_id: row.id };
  dialogVisible.value = true;
};

const submit = async () => {
  try {
    if (isEdit.value) {
      await updatePharmaceutical(form.value);
    } else {
      await createPharmaceutical(form.value);
    }
    ElMessage.success("操作成功");
    dialogVisible.value = false;
    fetchList();
  } catch (e) {
    ElMessage.error(e.msg || "操作失败");
  }
};

const handleDelete = (row) => {
  ElMessageBox.confirm("确认删除该药品？", "提示", { type: "warning" }).then(async () => {
    await deletePharmaceutical({ pharmaceutical_id: row.id });
    ElMessage.success("删除成功");
    fetchList();
  });
};

onMounted(fetchList);
</script>
