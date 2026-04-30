<template>
  <div class="app-container">
    <vab-page-header title="处方审核与发药" />
    <el-card>
      
      <el-input
        v-model="searchQuery"
        placeholder="搜索..."
        clearable
        style="width: 200px; margin-left: 10px;"
      ></el-input>
      <el-table :data="paginatedList" v-loading="loading">
        <el-table-column prop="uuid" label="处方ID" />
        <el-table-column prop="patient_name" label="患者" />
        <el-table-column prop="doctor_name" label="医生" />
        <el-table-column prop="status" label="状态">
          <template #default="{row}">
            <el-tag v-if="row.status===0" type="warning">待审核</el-tag>
            <el-tag v-else-if="row.status===1" type="primary">已审核</el-tag>
            <el-tag v-else-if="row.status===2" type="success">已发药</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="create_time" label="创建时间" />
        <el-table-column label="药品明细">
          <template #default="{row}">
            <div v-for="(p, i) in row.phas" :key="i">{{ p.name }} x{{ p.number }}</div>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="200">
          <template #default="{row}">
            <el-button v-if="row.status===0" size="small" type="primary" @click="audit(row)">审核</el-button>
            <el-button v-if="row.status===1" size="small" type="success" @click="dispense(row)">发药</el-button>
            <el-button size="small" @click="handleReturn(row)">退药</el-button>
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

    <el-dialog v-model="returnVisible" title="退药" width="500px">
      <el-form :model="returnForm" label-width="100px">
        <el-form-item label="药品">
          <el-select v-model="returnForm.pha_id" filterable>
            <el-option v-for="p in returnPhas" :key="p.pharmaceutical_id" :label="p.name" :value="p.pharmaceutical_id" />
          </el-select>
        </el-form-item>
        <el-form-item label="数量">
          <el-input-number v-model="returnForm.number" :min="1" />
        </el-form-item>
        <el-form-item label="原因">
          <el-input v-model="returnForm.reason" type="textarea" :rows="2" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="returnVisible=false">取消</el-button>
        <el-button type="primary" @click="submitReturn">确定</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, onMounted, computed } from "vue";
import { ElMessage } from "element-plus";
import { getDispenseList, auditPrescription, dispensePrescription, returnMedicine } from "@/api/pharmacy";

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
const returnVisible = ref(false);
const returnForm = ref({});
const returnPhas = ref([]);

const fetchList = async () => {
  loading.value = true;
  const res = await getDispenseList(searchQuery.value);
  list.value = res.data || [];
  total.value = filteredList.value.length;
  loading.value = false;
};

const audit = async (row) => {
  try {
    await auditPrescription({ prescription_id: row.uuid });
    ElMessage.success("审核成功");
    fetchList();
  } catch (e) {
    ElMessage.error(e.msg || "审核失败");
  }
};

const dispense = async (row) => {
  try {
    await dispensePrescription({ prescription_id: row.uuid });
    ElMessage.success("发药成功");
    fetchList();
  } catch (e) {
    ElMessage.error(e.msg || "发药失败");
  }
};

const handleReturn = (row) => {
  returnPhas.value = row.phas || [];
  returnForm.value = { prescription_id: row.uuid, pha_id: null, number: 1, reason: "" };
  returnVisible.value = true;
};

const submitReturn = async () => {
  try {
    await returnMedicine(returnForm.value);
    ElMessage.success("退药成功");
    returnVisible.value = false;
    fetchList();
  } catch (e) {
    ElMessage.error(e.msg || "退药失败");
  }
};

onMounted(fetchList);
</script>
