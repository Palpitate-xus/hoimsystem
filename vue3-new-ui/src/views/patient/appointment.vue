<template>
  <div class="app-container">
    <vab-page-header title="预约挂号" description="在线预约医生号源，管理预约记录" />
    <el-card>
      <div class="page-toolbar">
        <el-button type="primary" @click="openDialog">预约挂号</el-button>
        <el-input
          v-model="searchQuery"
          placeholder="搜索预约"
          clearable
          class="page-search-input"
        ></el-input>
        <el-button type="primary" @click="fetchList">搜索</el-button>
      </div>
      <el-table :data="paginatedList" v-loading="loading" border empty-text="暂无数据">
        <el-table-column prop="doctor" label="医生" />
        <el-table-column prop="department" label="科室"  sortable />
        <el-table-column prop="time" label="预约日期"  sortable />
        <el-table-column prop="prefer_time" label="时段" />
        <el-table-column prop="specialist" label="专家号">
          <template #default="{row}">
            <el-tag v-if="row.specialist">是</el-tag>
            <el-tag v-else type="info">否</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="状态" sortable>
          <template #default="{row}">
            <el-tag v-if="row.status==='未就诊'" type="warning" size="small">{{ row.status }}</el-tag>
            <el-tag v-else-if="row.status==='已就诊'" type="success" size="small">{{ row.status }}</el-tag>
            <el-tag v-else type="info" size="small">{{ row.status }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="120">
          <template #default="{row}">
            <el-button size="small" type="danger" @click="cancel(row)">取消</el-button>
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

    <el-dialog v-model="dialogVisible" title="选择号源" width="900px">
      <el-table :data="schedules" v-loading="schedLoading" empty-text="暂无可预约号源">
        <el-table-column prop="doctor" label="医生" />
        <el-table-column prop="date" label="日期"  sortable />
        <el-table-column prop="time" label="时段"  sortable />
        <el-table-column prop="stock" label="剩余号源"  sortable />
        <el-table-column prop="specialist" label="专家号">
          <template #default="{row}">
            <el-tag v-if="row.specialist">是</el-tag>
            <el-tag v-else type="info">否</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="120">
          <template #default="{row}">
            <el-button
              size="small"
              type="primary"
              :loading="submitting && submittingScheduleId === row.id"
              :disabled="submitting || isOutOfStock(row)"
              @click="book(row)"
            >
              {{ isOutOfStock(row) ? "无号源" : "预约" }}
            </el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, onMounted, computed } from "vue";
import { ElMessage } from "element-plus";
import { getAppointmentList, getAppointmentSchedules, createAppointment, cancelAppointment } from "@/api/patient";

const list = ref([]);
const searchQuery = ref("");
const currentPage = ref(1);
const pageSize = ref(10);
const total = ref(0);
const paginatedList = computed(() => {
  const start = (currentPage.value - 1) * pageSize.value;
  return list.value.slice(start, start + pageSize.value);
});

const schedules = ref([]);
const loading = ref(false);
const schedLoading = ref(false);
const dialogVisible = ref(false);
const submitting = ref(false);
const submittingScheduleId = ref(null);

const getErrorMessage = (error, fallback) => {
  const message = error?.response?.data?.msg || error?.msg;
  if (message) return message;

  if (typeof error === "string") {
    const backendMessage = error.match(/"msg":"([^"]+)"/)?.[1];
    if (backendMessage) return backendMessage;
  }

  if (error?.message === "Network Error") return "网络连接异常，请检查网络后重试";
  if (error?.message?.includes("timeout")) return "请求超时，请稍后重试";
  return fallback;
};

const isOutOfStock = (row) => Number(row?.stock) <= 0;

const fetchList = async () => {
  loading.value = true;
  try {
    const res = await getAppointmentList(searchQuery.value);
    list.value = res.data || [];
    total.value = list.value.length;
  } catch (e) {
    ElMessage.error(getErrorMessage(e, "预约记录加载失败，请稍后重试"));
  } finally {
    loading.value = false;
  }
};

const openDialog = async () => {
  if (schedLoading.value || submitting.value) return;
  dialogVisible.value = true;
  schedLoading.value = true;
  try {
    const res = await getAppointmentSchedules();
    schedules.value = res.data || [];
  } catch (e) {
    schedules.value = [];
    ElMessage.error(getErrorMessage(e, "号源加载失败，请稍后重试"));
  } finally {
    schedLoading.value = false;
  }
};

const book = async (row) => {
  if (submitting.value) return;
  if (isOutOfStock(row)) {
    ElMessage.warning("该时段号源已满，请选择其他时段");
    return;
  }

  submitting.value = true;
  submittingScheduleId.value = row.id;
  try {
    await createAppointment({
      id: row.id,
      date: row.date,
      department_id: row.department_id,
      doctor_id: row.doctor_id,
      time: row.time,
      specialist: row.specialist,
    });
    ElMessage.success("预约成功");
    dialogVisible.value = false;
    fetchList();
  } catch (e) {
    ElMessage.error(getErrorMessage(e, "预约失败，请稍后重试"));
  } finally {
    submitting.value = false;
    submittingScheduleId.value = null;
  }
};

const cancel = async (row) => {
  try {
    await cancelAppointment({ uuid: row.uuid });
    ElMessage.success("取消成功");
    fetchList();
  } catch (e) {
    ElMessage.error(e.msg || "取消失败");
  }
};

onMounted(fetchList);
</script>
