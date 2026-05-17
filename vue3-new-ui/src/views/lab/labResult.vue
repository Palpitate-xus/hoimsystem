<template>
  <div class="app-container">
    <vab-page-header title="检验科管理" description="录入和查询检验检查结果数据" />
    <el-tabs v-model="activeTab">
      <el-tab-pane label="待处理申请" name="pending">
        <div class="page-toolbar">
          <el-input
            v-model="searchQuery1"
            placeholder="搜索..."
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
              <el-button size="small" type="primary" @click="handleResult(row)">录入结果</el-button>
              <el-button size="small" type="success" @click="receiveSample(row)">接收</el-button>
              <el-button size="small" type="danger" @click="rejectSample(row)">拒收</el-button>
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
      <el-tab-pane label="检查结果" name="results">
        <div class="page-toolbar">
          <el-input
            v-model="searchQuery2"
            placeholder="搜索..."
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
              <el-tag v-else type="success">正常</el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="technician_name" label="技师" />
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

    <el-dialog v-model="dialogVisible" title="录入检查结果" width="600px">
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
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible=false">取消</el-button>
        <el-button type="primary" @click="submit">确定</el-button>
      </template>
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
import { ElMessage } from "element-plus";
import { getPendingLabOrders, getLabResultList, createLabResult, sampleReceive, sampleReject, sampleTracking } from "@/api/lab";

const activeTab = ref("pending");
const pendingList = ref([]);
const resultList = ref([]);
const searchQuery1 = ref("");
const searchQuery2 = ref("");
const loading = ref(false);
const loading2 = ref(false);
const dialogVisible = ref(false);
const trackingVisible = ref(false);
const trackingList = ref([]);
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

const handleResult = (row) => {
  form.value = { lab_order_id: row.id, sample_id: "", result: "", abnormal_flag: 0 };
  dialogVisible.value = true;
};

const submit = async () => {
  try {
    await createLabResult(form.value);
    ElMessage.success("录入成功");
    dialogVisible.value = false;
    fetchPending();
    fetchResults();
  } catch (e) {
    ElMessage.error(e.msg || "录入失败");
  }
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
});
</script>
