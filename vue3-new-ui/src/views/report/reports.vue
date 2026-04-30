<template>
  <div class="app-container">
    <vab-page-header title="报表统计" />
    <el-tabs v-model="activeTab">
      <el-tab-pane label="门诊量统计" name="outpatient">
        <el-form :inline="true" :model="outpatientForm">
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
        <el-input
          v-model="searchQuery1"
          placeholder="搜索..."
          clearable
          style="width: 200px; margin-top: 10px;"
        ></el-input>
        <el-table :data="paginatedOutpatientDetails" style="margin-top:15px">
          <el-table-column prop="label" label="分组" />
          <el-table-column prop="value" label="人次" />
        </el-table>
      <el-pagination
        v-model:current-page="currentPage"
        v-model:page-size="pageSize"
        :page-sizes="[10, 20, 50, 100]"
        layout="total, sizes, prev, pager, next, jumper"
        :total="filteredOutpatientDetails.length"
        style="margin-top: 15px; justify-content: flex-end;"
      />

      </el-tab-pane>

      <el-tab-pane label="财务统计" name="finance">
        <el-form :inline="true" :model="financeForm">
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
        <el-form :inline="true" :model="pharmaForm">
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
        <el-input
          v-model="searchQuery2"
          placeholder="搜索..."
          clearable
          style="width: 200px; margin-bottom: 10px;"
        ></el-input>
        <el-table :data="paginatedPharmaResult">
          <el-table-column prop="name" label="药品名称" />
          <el-table-column prop="total_number" label="消耗数量" />
        </el-table>
      <el-pagination
        v-model:current-page="currentPage"
        v-model:page-size="pageSize"
        :page-sizes="[10, 20, 50, 100]"
        layout="total, sizes, prev, pager, next, jumper"
        :total="filteredPharmaResult.length"
        style="margin-top: 15px; justify-content: flex-end;"
      />

      </el-tab-pane>

      <el-tab-pane label="医生工作量" name="workload">
        <el-form :inline="true" :model="workloadForm">
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
        <el-input
          v-model="searchQuery3"
          placeholder="搜索..."
          clearable
          style="width: 200px; margin-bottom: 10px;"
        ></el-input>
        <el-table :data="paginatedWorkloadResult">
          <el-table-column prop="doctor_name" label="医生" />
          <el-table-column prop="visit_count" label="接诊人数" />
          <el-table-column prop="prescription_count" label="处方数" />
          <el-table-column prop="lab_order_count" label="检查申请数" />
        </el-table>
      <el-pagination
        v-model:current-page="currentPage"
        v-model:page-size="pageSize"
        :page-sizes="[10, 20, 50, 100]"
        layout="total, sizes, prev, pager, next, jumper"
        :total="filteredWorkloadResult.length"
        style="margin-top: 15px; justify-content: flex-end;"
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

const filteredOutpatientDetails = computed(() => {
  const data = outpatientResult.value.details || [];
  if (!searchQuery1.value) return data;
  const kw = searchQuery1.value.toLowerCase();
  return data.filter((item) =>
    Object.values(item).some((val) =>
      String(val ?? "").toLowerCase().includes(kw)
    )
  );
});

const filteredPharmaResult = computed(() => {
  if (!searchQuery2.value) return pharmaResult.value;
  const kw = searchQuery2.value.toLowerCase();
  return pharmaResult.value.filter((item) =>
    Object.values(item).some((val) =>
      String(val ?? "").toLowerCase().includes(kw)
    )
  );
});

const filteredWorkloadResult = computed(() => {
  if (!searchQuery3.value) return workloadResult.value;
  const kw = searchQuery3.value.toLowerCase();
  return workloadResult.value.filter((item) =>
    Object.values(item).some((val) =>
      String(val ?? "").toLowerCase().includes(kw)
    )
  );
});

const paginatedOutpatientDetails = computed(() => {
  const start = (currentPage.value - 1) * pageSize.value;
  return filteredOutpatientDetails.value.slice(start, start + pageSize.value);
});

const paginatedPharmaResult = computed(() => {
  const start = (currentPage.value - 1) * pageSize.value;
  return filteredPharmaResult.value.slice(start, start + pageSize.value);
});

const paginatedWorkloadResult = computed(() => {
  const start = (currentPage.value - 1) * pageSize.value;
  return filteredWorkloadResult.value.slice(start, start + pageSize.value);
});

const queryOutpatient = async () => {
  try {
    const res = await reportOutpatientVolume(outpatientForm.value);
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
    const res = await reportPharmaceutical(pharmaForm.value);
    pharmaResult.value = res.data || [];
  } catch (e) {
    ElMessage.error(e.msg || "查询失败");
  }
};

const queryWorkload = async () => {
  try {
    const res = await reportDoctorWorkload(workloadForm.value);
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
