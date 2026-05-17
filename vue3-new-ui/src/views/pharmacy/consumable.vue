<template>
  <div class="app-container">
    <vab-page-header title="耗材管理" description="管理医疗耗材信息和库存" />
    <el-card>
      <div class="page-toolbar">
        <el-button type="primary" @click="handleAdd">新增耗材</el-button>
        <el-input v-model="searchQuery" placeholder="搜索..." clearable class="page-search-input" />
        <el-button type="primary" @click="fetchList">搜索</el-button>
      </div>

      <el-table :data="list" v-loading="loading" empty-text="暂无记录">
        <el-table-column prop="consumable_id" label="ID" width="60" />
        <el-table-column prop="name" label="名称" />
        <el-table-column prop="category" label="分类" width="100" />
        <el-table-column prop="stock" label="库存" width="80" />
        <el-table-column prop="unit" label="单位" width="80" />
        <el-table-column prop="price" label="单价" width="80" />
        <el-table-column prop="supplier" label="供应商" />
        <el-table-column prop="status" label="状态" width="80">
          <template #default="{row}">
            <el-tag v-if="row.status===0" type="success">正常</el-tag>
            <el-tag v-else type="danger">停用</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="150">
          <template #default="{row}">
            <el-button size="small" @click="handleEdit(row)">编辑</el-button>
            <el-button size="small" type="danger" @click="handleDelete(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <el-dialog v-model="dialogVisible" :title="isEdit ? '编辑耗材' : '新增耗材'" width="500px">
      <el-form :model="form" label-width="80px" class="dialog-form">
        <el-form-item label="名称">
          <el-input v-model="form.name" />
        </el-form-item>
        <el-form-item label="分类">
          <el-select v-model="form.category" placeholder="选择分类" style="width: 100%;">
            <el-option label="注射类" value="注射类" />
            <el-option label="敷料类" value="敷料类" />
            <el-option label="检验类" value="检验类" />
            <el-option label="手术类" value="手术类" />
            <el-option label="其他" value="其他" />
          </el-select>
        </el-form-item>
        <el-form-item label="库存">
          <el-input-number v-model="form.stock" :min="0" style="width: 100%;" />
        </el-form-item>
        <el-form-item label="单位">
          <el-input v-model="form.unit" placeholder="个/包/支/套" />
        </el-form-item>
        <el-form-item label="单价">
          <el-input-number v-model="form.price" :min="0" :precision="2" style="width: 100%;" />
        </el-form-item>
        <el-form-item label="供应商">
          <el-input v-model="form.supplier" />
        </el-form-item>
        <el-form-item label="备注">
          <el-input v-model="form.remark" type="textarea" :rows="2" />
        </el-form-item>
        <el-form-item label="状态">
          <el-radio-group v-model="form.status">
            <el-radio :label="0">正常</el-radio>
            <el-radio :label="1">停用</el-radio>
          </el-radio-group>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" @click="submit">确定</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, onMounted } from "vue";
import { ElMessage, ElMessageBox } from "element-plus";
import { getConsumableList, createConsumable, updateConsumable, deleteConsumable } from "@/api/consumable";

const list = ref([]);
const loading = ref(false);
const searchQuery = ref("");
const dialogVisible = ref(false);
const isEdit = ref(false);
const form = ref({ status: 0 });

const fetchList = async () => {
  loading.value = true;
  const res = await getConsumableList(searchQuery.value);
  list.value = res.data || [];
  loading.value = false;
};

const handleAdd = () => {
  isEdit.value = false;
  form.value = { status: 0 };
  dialogVisible.value = true;
};

const handleEdit = (row) => {
  isEdit.value = true;
  form.value = { ...row };
  dialogVisible.value = true;
};

const submit = async () => {
  try {
    if (isEdit.value) {
      await updateConsumable(form.value);
    } else {
      await createConsumable(form.value);
    }
    ElMessage.success("保存成功");
    dialogVisible.value = false;
    fetchList();
  } catch (e) {
    ElMessage.error(e.msg || "保存失败");
  }
};

const handleDelete = async (row) => {
  try {
    await ElMessageBox.confirm("确定删除该耗材吗？", "提示", { type: "warning" });
    await deleteConsumable({ consumable_id: row.consumable_id });
    ElMessage.success("删除成功");
    fetchList();
  } catch (e) {
    if (e !== "cancel") ElMessage.error(e.msg || "删除失败");
  }
};

onMounted(fetchList);
</script>
