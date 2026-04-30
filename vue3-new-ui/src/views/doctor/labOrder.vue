<template>
  <div class="app-container">
    <vab-page-header title="检查检验申请" />
    <el-card>
      <el-button type="primary" @click="handleAdd">新增申请</el-button>
      
      <el-input
        v-model="searchQuery"
        placeholder="搜索..."
        clearable
        style="width: 200px; margin-left: 10px;"
      ></el-input>
      <el-table :data="paginatedList" v-loading="loading" style="margin-top: 15px">
        <el-table-column prop="id" label="申请单ID" />
        <el-table-column prop="patient_name" label="患者" />
        <el-table-column prop="check_type" label="检查类型" />
        <el-table-column prop="status" label="状态">
          <template #default="{row}">
            <el-tag v-if="row.status===0" type="warning">待缴费</el-tag>
            <el-tag v-else-if="row.status===1" type="primary">待检查</el-tag>
            <el-tag v-else type="success">已完成</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="create_time" label="申请时间" />
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

    <el-dialog v-model="dialogVisible" title="新增检查申请" width="600px">
      <el-form :model="form" label-width="100px">
        <el-form-item label="患者">
          <el-select v-model="form.patient_id" placeholder="请选择患者" style="width:100%" filterable>
            <el-option v-for="p in patientOptions" :key="p.id" :label="p.name" :value="p.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="检查类型">
          <el-input v-model="form.check_type" />
        </el-form-item>
        <el-form-item label="检查项目">
          <el-input v-model="checkItemsStr" placeholder="用逗号分隔" />
        </el-form-item>
        <el-form-item label="是否紧急">
          <el-switch v-model="form.urgent" :active-value="1" :inactive-value="0" />
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
import { ref, computed, onMounted } from "vue";
import { ElMessage } from "element-plus";
import { getLabOrderList, createLabOrder } from "@/api/doctor";
import { getPatientList } from "@/api/admin";

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
const form = ref({ patient_id: null, check_type: "", check_items: [], urgent: 0 });
const patientOptions = ref([]);

const checkItemsStr = computed({
  get: () => form.value.check_items.join(","),
  set: (val) => { form.value.check_items = val.split(",").filter(Boolean); }
});

const fetchList = async () => {
  loading.value = true;
  const res = await getLabOrderList();
  list.value = res.data || [];
  total.value = filteredList.value.length;
  loading.value = false;
};

const handleAdd = () => {
  form.value = { patient_id: null, check_type: "", check_items: [], urgent: 0 };
  dialogVisible.value = true;
};

const submit = async () => {
  try {
    await createLabOrder(form.value);
    ElMessage.success("申请成功");
    dialogVisible.value = false;
    fetchList();
  } catch (e) {
    ElMessage.error(e.msg || "申请失败");
  }
};

const loadPatients = async () => {
  const res = await getPatientList();
  patientOptions.value = res.data || [];
};

onMounted(() => {
  fetchList();
  loadPatients();
});
</script>
