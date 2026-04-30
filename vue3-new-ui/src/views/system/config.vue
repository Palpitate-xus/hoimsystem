<template>
  <div class="app-container">
    <vab-page-header title="系统参数" />
    <el-card>
      
      <el-input
        v-model="searchQuery"
        placeholder="搜索..."
        clearable
        style="width: 200px; margin-left: 10px;"
      ></el-input>
      <el-table :data="paginatedList" v-loading="loading">
        <el-table-column prop="config_key" label="参数键" />
        <el-table-column prop="config_value" label="参数值" />
        <el-table-column prop="description" label="说明" />
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
import { ref, onMounted, computed } from "vue";
import { ElMessage } from "element-plus";
import { getConfigList, updateConfig } from "@/api/system";

const list = ref([]);
const searchQuery = ref("");
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
const form = ref({});

const fetchList = async () => {
  loading.value = true;
  const res = await getConfigList();
  list.value = res.data || [];
  total.value = filteredList.value.length;
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
