<template>
  <div class="app-container">
    <vab-page-header title="数据字典" description="维护系统数据字典和编码规范" />
    <el-card>
      <el-form :inline="true" :model="queryForm" class="page-toolbar">
        <el-form-item label="字典类型">
          <el-input v-model="queryForm.dict_type" placeholder="例如 gender" />
        </el-form-item>
        <el-form-item>
          <el-button type="primary" @click="fetchList">查询</el-button>
        </el-form-item>
      </el-form>
      <div class="page-toolbar">
        <el-button type="primary" @click="handleAdd">新增字典项</el-button>
        <el-input
          v-model="searchQuery"
          placeholder="搜索关键词"
          clearable
          class="page-search-input"
        ></el-input>
        <el-button type="primary" @click="fetchList">搜索</el-button>
      </div>
      <el-table :data="paginatedList" v-loading="loading" empty-text="暂无记录">
        <el-table-column prop="dict_id" label="ID" />
        <el-table-column prop="dict_type" label="类型" />
        <el-table-column prop="dict_code" label="编码" />
        <el-table-column prop="dict_value" label="值" />
        <el-table-column prop="sort_order" label="排序" />
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

    <el-dialog v-model="dialogVisible" :title="isEdit?'编辑字典项':'新增字典项'" width="500px">
      <el-form :model="form" label-width="100px" class="dialog-form">
        <el-form-item label="字典类型">
          <el-input v-model="form.dict_type" />
        </el-form-item>
        <el-form-item label="编码">
          <el-input v-model="form.dict_code" />
        </el-form-item>
        <el-form-item label="值">
          <el-input v-model="form.dict_value" />
        </el-form-item>
        <el-form-item label="排序">
          <el-input-number v-model="form.sort_order" :min="0" />
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
import { getDictList, createDict, updateDict, deleteDict } from "@/api/system";

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
const queryForm = ref({ dict_type: "" });

const fetchList = async () => {
  loading.value = true;
  const res = await getDictList(queryForm.value);
  list.value = res.data || [];
  total.value = list.value.length;
  loading.value = false;
};

const handleAdd = () => {
  isEdit.value = false;
  form.value = { sort_order: 0 };
  dialogVisible.value = true;
};

const handleEdit = (row) => {
  isEdit.value = true;
  form.value = { ...row, dict_id: row.dict_id };
  dialogVisible.value = true;
};

const submit = async () => {
  try {
    if (isEdit.value) {
      await updateDict(form.value);
    } else {
      await createDict(form.value);
    }
    ElMessage.success("操作成功");
    dialogVisible.value = false;
    fetchList();
  } catch (e) {
    ElMessage.error(e.msg || "操作失败");
  }
};

const handleDelete = (row) => {
  ElMessageBox.confirm("确认删除？", "提示", { type: "warning" }).then(async () => {
    await deleteDict({ dict_id: row.dict_id });
    ElMessage.success("删除成功");
    fetchList();
  });
};

onMounted(fetchList);
</script>
