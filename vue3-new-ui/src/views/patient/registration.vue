<template>
  <div class="app-container">
    <vab-page-header title="现场挂号" description="现场挂号就诊，查看挂号记录" />
    <el-card>
      <div class="page-toolbar">
        <el-button type="primary" @click="openDialog">现场挂号</el-button>
        <el-input
          v-model="searchQuery"
          placeholder="搜索..."
          clearable
          class="page-search-input"
        ></el-input>
        <el-button type="primary" @click="fetchList">搜索</el-button>
      </div>
      <el-table :data="paginatedList" v-loading="loading" border empty-text="暂无数据">
        <el-table-column prop="order" label="序号"  sortable />
        <el-table-column prop="doctor" label="医生" />
        <el-table-column prop="department" label="科室"  sortable />
        <el-table-column prop="time" label="挂号时间"  sortable />
        <el-table-column prop="status" label="状态"  sortable />
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
      <el-table :data="schedules" v-loading="schedLoading">
        <el-table-column prop="doctor" label="医生" />
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
            <el-button size="small" type="primary" @click="register(row)">挂号</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, onMounted, computed } from "vue";
import { ElMessage } from "element-plus";
import { getRegistrationList, getRegistrationSchedules, createRegistration, cancelRegistration } from "@/api/patient";

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

const fetchList = async () => {
  loading.value = true;
  const res = await getRegistrationList(searchQuery.value);
  list.value = res.data || [];
  total.value = list.value.length;
  loading.value = false;
};

const openDialog = async () => {
  dialogVisible.value = true;
  schedLoading.value = true;
  const res = await getRegistrationSchedules();
  if (typeof res.data === "string") {
    ElMessage.warning(res.data);
    schedules.value = [];
  } else {
    schedules.value = res.data || [];
  }
  schedLoading.value = false;
};

const register = async (row) => {
  try {
    await createRegistration({
      id: row.id,
      doctor_id: row.doctor_id,
      department_id: row.department_id,
      specialist: row.specialist,
    });
    ElMessage.success("挂号成功");
    dialogVisible.value = false;
    fetchList();
  } catch (e) {
    ElMessage.error(e.msg || "挂号失败");
  }
};

const cancel = async (row) => {
  try {
    await cancelRegistration({ uuid: row.uuid });
    ElMessage.success("取消成功");
    fetchList();
  } catch (e) {
    ElMessage.error(e.msg || "取消失败");
  }
};

onMounted(fetchList);
</script>
