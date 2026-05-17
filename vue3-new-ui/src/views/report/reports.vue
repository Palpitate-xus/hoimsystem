<template>
  <div class="app-container">
    <vab-page-header title="报表统计" description="统计分析门诊量、财务、药品和医生工作量" />
    <el-tabs v-model="activeTab">
      <el-tab-pane label="门诊量统计" name="outpatient">
        <el-form :inline="true" :model="outpatientForm" class="page-toolbar">
          <el-form-item label="开始日期">
            <el-date-picker v-model="outpatientForm.start_date" type="date" value-format="YYYY-MM-DD" />
          </el-form-item>
          <el-form-item label="结束日期">
            <el-date-picker v-model="outpatientForm.end_date" type="date" value-format="YYYY-MM-DD" />
          </el-form-item>
          <el-form-item label="分组">
            <el-select v-model="outpatientForm.group_by" style="width:120px" filterable>
              <el-option label="按日" value="day" />
              <el-option label="按周" value="week" />
              <el-option label="按月" value="month" />
              <el-option label="按科室" value="department" />
              <el-option label="按医生" value="doctor" />
            </el-select>
          </el-form-item>
          <el-form-item>
            <el-button type="primary" @click="queryOutpatient">查询</el-button>
          </el-form-item>
        </el-form>
        <el-descriptions title="统计结果" :column="1" border v-if="outpatientResult.total_visits !== undefined">
          <el-descriptions-item label="总就诊人次">{{ outpatientResult.total_visits }}</el-descriptions-item>
        </el-descriptions>
        <el-table :data="paginatedOutpatientDetails" empty-text="暂无数据">
          <el-table-column prop="label" label="分组"  sortable />
          <el-table-column prop="value" label="人次" />
        </el-table>
      <el-pagination
        v-model:current-page="currentPage"
        v-model:page-size="pageSize"
        :page-sizes="[10, 20, 50, 100]"
        layout="total, sizes, prev, pager, next, jumper"
        :total="(outpatientResult.details || []).length"
        class="pagination-wrapper"
      />

      </el-tab-pane>

      <el-tab-pane label="财务统计" name="finance">
        <el-form :inline="true" :model="financeForm" class="page-toolbar">
          <el-form-item label="开始日期">
            <el-date-picker v-model="financeForm.start_date" type="date" value-format="YYYY-MM-DD" />
          </el-form-item>
          <el-form-item label="结束日期">
            <el-date-picker v-model="financeForm.end_date" type="date" value-format="YYYY-MM-DD" />
          </el-form-item>
          <el-form-item>
            <el-button type="primary" @click="queryFinance">查询</el-button>
          </el-form-item>
        </el-form>
        <el-descriptions :column="2" border v-if="financeResult.total_income !== undefined">
          <el-descriptions-item label="总收入">{{ financeResult.total_income }}</el-descriptions-item>
          <el-descriptions-item label="总退费">{{ financeResult.total_refund }}</el-descriptions-item>
          <el-descriptions-item label="处方收入">{{ financeResult.prescription_income }}</el-descriptions-item>
          <el-descriptions-item label="检查收入">{{ financeResult.lab_income }}</el-descriptions-item>
        </el-descriptions>
      </el-tab-pane>

      <el-tab-pane label="药品消耗统计" name="pharma">
        <el-form :inline="true" :model="pharmaForm" class="page-toolbar">
          <el-form-item label="开始日期">
            <el-date-picker v-model="pharmaForm.start_date" type="date" value-format="YYYY-MM-DD" />
          </el-form-item>
          <el-form-item label="结束日期">
            <el-date-picker v-model="pharmaForm.end_date" type="date" value-format="YYYY-MM-DD" />
          </el-form-item>
          <el-form-item>
            <el-button type="primary" @click="queryPharma">查询</el-button>
          </el-form-item>
        </el-form>
        <el-table :data="paginatedPharmaResult" empty-text="暂无数据">
          <el-table-column prop="name" label="药品名称"  sortable />
          <el-table-column prop="total_number" label="消耗数量"  sortable />
        </el-table>
      <el-pagination
        v-model:current-page="currentPage"
        v-model:page-size="pageSize"
        :page-sizes="[10, 20, 50, 100]"
        layout="total, sizes, prev, pager, next, jumper"
        :total="(pharmaResult || []).length"
        class="pagination-wrapper"
      />

      </el-tab-pane>

      <el-tab-pane label="医生工作量" name="workload">
        <el-form :inline="true" :model="workloadForm" class="page-toolbar">
          <el-form-item label="开始日期">
            <el-date-picker v-model="workloadForm.start_date" type="date" value-format="YYYY-MM-DD" />
          </el-form-item>
          <el-form-item label="结束日期">
            <el-date-picker v-model="workloadForm.end_date" type="date" value-format="YYYY-MM-DD" />
          </el-form-item>
          <el-form-item label="医生">
            <el-select v-model="workloadForm.doctor_id" placeholder="请选择医生" clearable style="width:180px" filterable>
              <el-option v-for="d in doctorOptions" :key="d.id" :label="d.name" :value="d.id" />
            </el-select>
          </el-form-item>
          <el-form-item>
            <el-button type="primary" @click="queryWorkload">查询</el-button>
          </el-form-item>
        </el-form>
        <el-table :data="paginatedWorkloadResult" empty-text="暂无数据">
          <el-table-column prop="doctor_name" label="医生"  sortable />
          <el-table-column prop="visit_count" label="接诊人数" />
          <el-table-column prop="prescription_count" label="处方数" />
          <el-table-column prop="lab_order_count" label="检查申请数" />
        </el-table>
      <el-pagination
        v-model:current-page="currentPage"
        v-model:page-size="pageSize"
        :page-sizes="[10, 20, 50, 100]"
        layout="total, sizes, prev, pager, next, jumper"
        :total="(workloadResult || []).length"
        class="pagination-wrapper"
      />

      </el-tab-pane>
    </el-tabs>
  </div>
</template>

<script setup>
import { ref, onMounted, computed } from "vue";
import { ElMessage } from "element-plus";
import { reportOutpatientVolume, reportFinance, reportPharmaceutical, reportDoctorWorkload } from "@/api/report";
import { getDoctorList } from "@/api/admin";

const activeTab = ref("outpatient");
const doctorOptions = ref([]);
const outpatientForm = ref({ start_date: "", end_date: "", group_by: "day" });
const financeForm = ref({ start_date: "", end_date: "" });
const pharmaForm = ref({ start_date: "", end_date: "" });
const workloadForm = ref({ start_date: "", end_date: "", doctor_id: null });

const outpatientResult = ref({ total_visits: undefined, details: [] });
const financeResult = ref({});
const pharmaResult = ref([]);
const workloadResult = ref([]);

const searchQuery1 = ref("");
const searchQuery2 = ref("");
const searchQuery3 = ref("");

const currentPage = ref(1);
const pageSize = ref(10);

const paginatedOutpatientDetails = computed(() => {
  const start = (currentPage.value - 1) * pageSize.value;
  return (outpatientResult.value.details || []).slice(start, start + pageSize.value);
});

const paginatedPharmaResult = computed(() => {
  const start = (currentPage.value - 1) * pageSize.value;
  return (pharmaResult.value || []).slice(start, start + pageSize.value);
});

const paginatedWorkloadResult = computed(() => {
  const start = (currentPage.value - 1) * pageSize.value;
  return (workloadResult.value || []).slice(start, start + pageSize.value);
});

const queryOutpatient = async () => {
  try {
    currentPage.value = 1;
    const res = await reportOutpatientVolume(outpatientForm.value, searchQuery1.value);
    outpatientResult.value = res.data || { total_visits: 0, details: [] };
  } catch (e) {
    ElMessage.error(e.msg || "查询失败");
  }
};

const queryFinance = async () => {
  try {
    const res = await reportFinance(financeForm.value);
    financeResult.value = res.data || {};
  } catch (e) {
    ElMessage.error(e.msg || "查询失败");
  }
};

const queryPharma = async () => {
  try {
    currentPage.value = 1;
    const res = await reportPharmaceutical(pharmaForm.value, searchQuery2.value);
    pharmaResult.value = res.data || [];
  } catch (e) {
    ElMessage.error(e.msg || "查询失败");
  }
};

const queryWorkload = async () => {
  try {
    currentPage.value = 1;
    const res = await reportDoctorWorkload(workloadForm.value, searchQuery3.value);
    workloadResult.value = res.data || [];
  } catch (e) {
    ElMessage.error(e.msg || "查询失败");
  }
};

const loadDoctors = async () => {
  const res = await getDoctorList();
  doctorOptions.value = res.data || [];
};

onMounted(loadDoctors);
</script>
