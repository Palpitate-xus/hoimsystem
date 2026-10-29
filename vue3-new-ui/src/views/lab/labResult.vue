<template>
  <div class="app-container">
    <el-tabs v-model="activeTab">
      <el-tab-pane label="待处理申请" name="pending">
        <div class="page-toolbar">
          <el-input
            v-model="searchQuery1"
            placeholder="搜索待处理申请"
            clearable
            class="page-search-input"
          ></el-input>
          <el-button type="primary" @click="fetchPending">搜索</el-button>
        </div>
        <el-table :data="paginatedPendingList" v-loading="loading" empty-text="暂无记录">
          <el-table-column prop="patient_name" label="患者"  sortable />
          <el-table-column prop="check_type" label="检查类型"  sortable />
            <el-table-column prop="create_time" label="申请时间"  sortable />
            <el-table-column label="操作" width="280">
              <template #default="{row}">
              <el-button v-if="row.sample_status === 1" size="small" type="primary" @click="handleResult(row)">录入结果</el-button>
              <el-button v-if="row.sample_status === 0" size="small" type="success" @click="receiveSample(row)">接收</el-button>
              <el-button v-if="row.sample_status === 0 || row.sample_status === 1" size="small" type="danger" @click="rejectSample(row)">拒收</el-button>
              <el-tag v-if="row.sample_status === 2" type="info" size="small">已拒收</el-tag>
              <el-button size="small" @click="viewTracking(row)">流转</el-button>
            </template>
          </el-table-column>
        </el-table>
      <el-pagination
        v-model:current-page="currentPage"
        v-model:page-size="pageSize"
        :page-sizes="[10, 20, 50, 100]"
        layout="total, sizes, prev, pager, next, jumper"
        :total="pendingList.length"
        class="pagination-wrapper"
      />

      </el-tab-pane>
      <el-tab-pane label="危急值报告" name="critical">
        <div class="page-toolbar"><el-button @click="fetchCritical">刷新</el-button></div>
        <el-table :data="criticalList" v-loading="loadingCritical" border empty-text="暂无危急值报告">
          <el-table-column prop="patient_name" label="患者" width="120" /><el-table-column prop="check_name" label="检查项目" width="140" /><el-table-column prop="result" label="危急结果" min-width="220" /><el-table-column prop="check_time" label="报告时间" width="180" /><el-table-column prop="technician_name" label="技师" width="120" /><el-table-column label="审核状态" width="100"><template #default="{ row }"><el-tag :type="row.audit_status ? 'success' : 'danger'">{{ row.audit_status_text }}</el-tag></template></el-table-column>
        </el-table>
      </el-tab-pane>
      <el-tab-pane label="检查结果" name="results">
        <div class="page-toolbar">
          <el-input
            v-model="searchQuery2"
            placeholder="搜索检查结果"
            clearable
            class="page-search-input"
          ></el-input>
          <el-button type="primary" @click="fetchResults">搜索</el-button>
        </div>
        <el-table :data="paginatedResultList" v-loading="loading2" empty-text="暂无记录">
          <el-table-column prop="check_name" label="检查名称"  sortable />
          <el-table-column prop="check_time" label="检查时间"  sortable />
          <el-table-column prop="result" label="结果"  sortable />
          <el-table-column prop="abnormal_flag" label="是否异常">
            <template #default="{row}">
              <el-tag v-if="row.abnormal_flag" type="danger">异常</el-tag>
              <el-tag v-else type="info">未标异常</el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="technician_name" label="技师" />
          <el-table-column label="审核" width="100"><template #default="{ row }"><el-tag :type="row.audit_status ? 'success' : 'warning'">{{ row.audit_status ? '已审核' : '待审核' }}</el-tag></template></el-table-column>
          <el-table-column label="操作" width="250"><template #default="{ row }">
            <el-button size="small" @click="viewResult(row)">查看结果</el-button>
            <ai-action v-if="row.audit_status === 1" label="AI 解读" title="AI 检验解读与趋势" :patient-id="row.patient_id" :initial-input="{ lab_result_id: row.id }" :feature-keys="['lab_interpretation', 'lab_trends', 'critical_value_assistance']" initial-feature="lab_interpretation" />
          </template></el-table-column>
        </el-table>
      <el-pagination
        v-model:current-page="currentPage"
        v-model:page-size="pageSize"
        :page-sizes="[10, 20, 50, 100]"
        layout="total, sizes, prev, pager, next, jumper"
        :total="resultList.length"
        class="pagination-wrapper"
      />

      </el-tab-pane>
    </el-tabs>

    <el-dialog v-model="dialogVisible" title="录入检查结果" width="min(900px, 96vw)">
      <el-form :model="form" label-width="100px" class="dialog-form">
        <el-form-item label="申请单ID">
          <el-input v-model="form.lab_order_id" disabled />
        </el-form-item>
        <el-form-item label="样本编号">
          <el-input v-model="form.sample_id" />
        </el-form-item>
        <el-form-item label="检查结果">
          <el-input v-model="form.result" type="textarea" :rows="3" />
        </el-form-item>
        <el-form-item label="是否异常">
          <el-switch v-model="form.abnormal_flag" :active-value="1" :inactive-value="0" />
        </el-form-item>
        <el-form-item label="结构化指标"><lab-observation-editor v-model="form.observations" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible=false">取消</el-button>
        <el-button type="primary" @click="submit">确定</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="resultVisible" title="检验报告与原始指标" width="min(1100px, 96vw)">
      <p class="report-text">{{ selectedResult.result }}</p>
      <lab-observation-table :items="selectedResult.observations || []" />
      <template #footer><el-button @click="resultVisible = false">关闭</el-button><el-button v-if="selectedResult.audit_status === 0" type="primary" @click="auditResult">复核并审核</el-button></template>
    </el-dialog>

    <el-dialog v-model="trackingVisible" title="样本流转跟踪" width="500px">
      <el-timeline>
        <el-timeline-item v-for="(item, i) in trackingList" :key="i" :timestamp="item.time">
          {{ item.stage }} - {{ item.operator }}
        </el-timeline-item>
      </el-timeline>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, onMounted, computed } from "vue";
import { ElMessage, ElMessageBox } from "element-plus";
import AiAction from "@/components/AIAction/index.vue";
import LabObservationEditor from "@/components/LabObservationEditor/index.vue";
import LabObservationTable from "@/components/LabObservationTable/index.vue";
import { getPendingLabOrders, getLabResultList, getCriticalLabResults, createLabResult, auditLabResult, sampleReceive, sampleReject, sampleTracking } from "@/api/lab";

const activeTab = ref("pending");
const pendingList = ref([]);
const resultList = ref([]);
const searchQuery1 = ref("");
const searchQuery2 = ref("");
const loading = ref(false);
const loading2 = ref(false);
const loadingCritical = ref(false);
const criticalList = ref([]);
const dialogVisible = ref(false);
const trackingVisible = ref(false);
const trackingList = ref([]);
const resultVisible = ref(false);
const selectedResult = ref({});
const form = ref({});
const currentPage = ref(1);
const pageSize = ref(10);

const paginatedPendingList = computed(() => {
  const start = (currentPage.value - 1) * pageSize.value;
  return pendingList.value.slice(start, start + pageSize.value);
});

const paginatedResultList = computed(() => {
  const start = (currentPage.value - 1) * pageSize.value;
  return resultList.value.slice(start, start + pageSize.value);
});

const fetchPending = async () => {
  loading.value = true;
  const res = await getPendingLabOrders(searchQuery1.value);
  pendingList.value = res.data || [];
  loading.value = false;
};

const fetchResults = async () => {
  loading2.value = true;
  const res = await getLabResultList(searchQuery2.value);
  resultList.value = res.data || [];
  loading2.value = false;
};

const fetchCritical = async () => { loadingCritical.value = true; try { const res = await getCriticalLabResults(); criticalList.value = res.data || []; } finally { loadingCritical.value = false; } };

const handleResult = (row) => {
  form.value = { lab_order_id: row.id, sample_id: "", result: "", abnormal_flag: 0, observations: [] };
  dialogVisible.value = true;
};

const submit = async () => {
  try {
    const observations = form.value.observations.map(({ _key, value_kind, ...item }) => {
      if (!item.collected_at || !Number.isFinite(new Date(item.collected_at).getTime())) throw new Error("请填写每项指标的采样时间");
      return { ...item, collected_at: new Date(item.collected_at).toISOString(), value_num: value_kind === "numeric" ? item.value_num : null, value_text: value_kind === "text" ? item.value_text : null, unit: item.unit || null, reference_low: item.reference_low || null, reference_high: item.reference_high || null, reference_text: item.reference_text || null };
    });
    await createLabResult({ ...form.value, observations });
    ElMessage.success("录入成功");
    dialogVisible.value = false;
    fetchPending();
    fetchResults();
  } catch (e) {
    ElMessage.error(e.msg || e.message || "录入失败");
  }
};

const viewResult = (row) => { selectedResult.value = row; resultVisible.value = true; };
const auditResult = async () => {
  try {
    await ElMessageBox.confirm("请确认已核对原始报告、逐项数值、单位和采样时间。录入者不能审核自己的报告。", "检验结果复核", { type: "warning" });
    await auditLabResult({ lab_result_id: selectedResult.value.id });
    ElMessage.success("报告已审核"); resultVisible.value = false; await fetchResults();
  } catch (error) { if (error !== "cancel" && error !== "close") ElMessage.error(error.msg || error.message || "审核失败"); }
};

const receiveSample = async (row) => {
  try {
    await sampleReceive({ lab_order_id: row.id });
    ElMessage.success("样本已接收");
    fetchPending();
  } catch (e) {
    ElMessage.error(e.msg || "操作失败");
  }
};

const rejectSample = async (row) => {
  try {
    await sampleReject({ lab_order_id: row.id });
    ElMessage.success("样本已拒收");
    fetchPending();
  } catch (e) {
    ElMessage.error(e.msg || "操作失败");
  }
};

const viewTracking = async (row) => {
  try {
    const res = await sampleTracking(row.id);
    trackingList.value = res.data || [];
    trackingVisible.value = true;
  } catch (e) {
    ElMessage.error(e.msg || "查询失败");
  }
};

onMounted(() => {
  fetchPending();
  fetchResults();
  fetchCritical();
});
</script>

<style scoped>
.report-text { white-space: pre-wrap; line-height: 1.7; overflow-wrap: anywhere; }
</style>
