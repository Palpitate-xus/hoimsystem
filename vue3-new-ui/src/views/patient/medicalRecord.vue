<template>
  <div class="app-container">
    <vab-page-header title="病历查询" description="查看个人就诊病历和诊断记录" />
    <el-card>
      
      <div class="page-toolbar">
        <el-input
          v-model="searchQuery"
          placeholder="搜索病历"
          clearable
          class="page-search-input"
        ></el-input>
        <el-button type="primary" @click="fetchList">搜索</el-button>
      </div>
      <el-table :data="paginatedList" v-loading="loading" border empty-text="暂无数据">
        <el-table-column prop="consultation_time" label="就诊时间"  sortable />
        <el-table-column prop="doctor_name" label="医生"  sortable />
        <el-table-column prop="symptom" label="症状" show-overflow-tooltip  sortable />
        <el-table-column prop="result" label="诊断结果" show-overflow-tooltip  sortable />
        <el-table-column label="操作" width="120">
          <template #default="{row}">
            <el-button size="small" @click="viewDetail(row)">查看</el-button>
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

    <el-dialog v-model="dialogVisible" title="病历详情" width="600px">
      <el-descriptions :column="1" border>
        <el-descriptions-item label="就诊时间">{{ detail.consultation_time }}</el-descriptions-item>
        <el-descriptions-item label="医生">{{ detail.doctor_name }}</el-descriptions-item>
        <el-descriptions-item label="患者">{{ detail.patient_name }}</el-descriptions-item>
        <el-descriptions-item label="症状">{{ detail.symptom }}</el-descriptions-item>
        <el-descriptions-item label="诊断结果">{{ detail.result }}</el-descriptions-item>
      </el-descriptions>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, onMounted, computed } from "vue";
import { getMedicalRecordList, getMedicalRecordDetail } from "@/api/patient";

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
const detail = ref({});

const fetchList = async () => {
  loading.value = true;
  const res = await getMedicalRecordList(searchQuery.value);
  list.value = res.data || [];
  total.value = list.value.length;
  loading.value = false;
};

const viewDetail = async (row) => {
  const res = await getMedicalRecordDetail({ medical_record_id: row.uuid });
  detail.value = res.data || {};
  dialogVisible.value = true;
};

onMounted(fetchList);
</script>
