<template>
  <div class="app-container">
    <vab-page-header title="号源池管理" description="查看各科室号源分布和使用情况" />
    <el-card>
      <el-table :data="list" v-loading="loading">
        <el-table-column prop="department_name" label="科室" />
        <el-table-column prop="doctor_count" label="出诊医生数" width="120" />
        <el-table-column prop="schedules_count" label="排班时段数" width="120" />
        <el-table-column prop="total_slots" label="总号源" width="120" />
        <el-table-column label="操作" width="120">
          <template #default="{row}">
            <el-button size="small" @click="viewDetail(row)">详情</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>
  </div>
</template>
<script setup>
import { ref, onMounted } from "vue";
import { ElMessage } from "element-plus";
import { getSlotPoolList } from "@/api/slotPool";
const list = ref([]); const loading = ref(false);
const fetchList = async () => { loading.value = true; const res = await getSlotPoolList(); list.value = res.data || []; loading.value = false; };
const viewDetail = (row) => { ElMessage.info(`科室 ${row.department_name} 共 ${row.total_slots} 个号源`); };
onMounted(fetchList);
</script>