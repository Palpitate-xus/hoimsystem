<template>
  <div class="app-container">
    <vab-page-header title="生命体征录入" description="为患者录入和查询生命体征数据" />
    <el-card>
      <div class="page-toolbar">
        <el-button type="primary" @click="handleAdd">录入体征</el-button>
        <el-input
          v-model="searchQuery"
          placeholder="搜索..."
          clearable
          class="page-search-input"
        ></el-input>
        <el-button type="primary" @click="fetchList">搜索</el-button>
      </div>
      <el-table :data="paginatedList" v-loading="loading" empty-text="暂无记录">
        <el-table-column prop="patient_name" label="患者"  sortable />
        <el-table-column prop="temperature" label="体温" />
        <el-table-column prop="blood_pressure" label="血压" />
        <el-table-column prop="pulse" label="脉搏" />
        <el-table-column prop="weight" label="体重" />
        <el-table-column prop="check_time" label="测量时间"  sortable />
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

    <el-dialog v-model="dialogVisible" title="录入生命体征" width="600px">
      <el-form :model="form" label-width="120px" class="dialog-form">
        <el-form-item label="患者">
          <el-select v-model="form.patient_id" placeholder="请选择患者" class="form-full-width" filterable>
            <el-option v-for="p in patientOptions" :key="p.id" :label="p.name" :value="p.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="体温">
          <el-input v-model="form.temperature" placeholder="例如 36.5" />
        </el-form-item>
        <el-form-item label="收缩压">
          <el-input v-model="form.blood_pressure_systolic" placeholder="例如 120" />
        </el-form-item>
        <el-form-item label="舒张压">
          <el-input v-model="form.blood_pressure_diastolic" placeholder="例如 80" />
        </el-form-item>
        <el-form-item label="脉搏">
          <el-input v-model="form.pulse" placeholder="例如 72" />
        </el-form-item>
        <el-form-item label="体重">
          <el-input v-model="form.weight" placeholder="例如 65.5" />
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
import { getVitalSignList, createVitalSign } from "@/api/vitalsign";
import { getPatientList } from "@/api/admin";

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
const form = ref({ patient_id: null });
const patientOptions = ref([]);

const fetchList = async () => {
  loading.value = true;
  const res = await getVitalSignList(searchQuery.value);
  list.value = res.data || [];
  total.value = list.value.length;
  loading.value = false;
};

const handleAdd = () => {
  form.value = { patient_id: null };
  dialogVisible.value = true;
};

const submit = async () => {
  try {
    await createVitalSign(form.value);
    ElMessage.success("录入成功");
    dialogVisible.value = false;
    fetchList();
  } catch (e) {
    ElMessage.error(e.msg || "录入失败");
  }
};

const loadPatients = async () => {
  const res = await getPatientList(searchQuery.value);
  patientOptions.value = res.data || [];
};

onMounted(() => {
  fetchList();
  loadPatients();
});
</script>
