<template>
  <div class="app-container">
    <vab-page-header title="分诊台管理" description="分诊患者到相应科室，管理分诊记录" />
    <el-row :gutter="20">
      <el-col :span="10">
        <el-card>
          <template #header>
            <span>新建分诊记录</span>
          </template>
          <el-form :model="form" label-width="100px">
            <el-form-item label="身份证号">
              <el-input v-model="form.identity" placeholder="请输入病人身份证号" />
            </el-form-item>
            <el-form-item label="症状描述">
              <el-input v-model="form.symptom" type="textarea" :rows="3" placeholder="请描述病人主要症状" />
            </el-form-item>
            <el-form-item label="生命体征">
              <el-row :gutter="10">
                <el-col :span="12">
                  <el-input-number v-model="form.temperature" :precision="1" :min="30" :max="45" placeholder="体温" style="width: 100%;" />
                </el-col>
                <el-col :span="12">
                  <el-input-number v-model="form.pulse" :min="0" :max="300" placeholder="脉搏" style="width: 100%;" />
                </el-col>
              </el-row>
              <el-row :gutter="10" style="margin-top: 10px;">
                <el-col :span="12">
                  <el-input-number v-model="form.blood_pressure_systolic" :min="0" :max="300" placeholder="收缩压" style="width: 100%;" />
                </el-col>
                <el-col :span="12">
                  <el-input-number v-model="form.blood_pressure_diastolic" :min="0" :max="200" placeholder="舒张压" style="width: 100%;" />
                </el-col>
              </el-row>
            </el-form-item>
            <el-form-item label="分诊级别">
              <el-radio-group v-model="form.level">
                <el-radio-button :label="1">
                  <el-tag type="danger">危急</el-tag>
                </el-radio-button>
                <el-radio-button :label="2">
                  <el-tag type="warning">急症</el-tag>
                </el-radio-button>
                <el-radio-button :label="3">
                  <el-tag type="">普通</el-tag>
                </el-radio-button>
                <el-radio-button :label="4">
                  <el-tag type="success">非急</el-tag>
                </el-radio-button>
              </el-radio-group>
            </el-form-item>
            <el-form-item label="推荐科室">
              <el-select v-model="form.department_id" placeholder="选择科室" clearable style="width: 100%;">
                <el-option v-for="d in departments" :key="d.department_id" :label="d.name" :value="d.department_id" />
              </el-select>
            </el-form-item>
            <el-form-item label="备注">
              <el-input v-model="form.note" type="textarea" :rows="2" />
            </el-form-item>
            <el-form-item>
              <el-button type="primary" @click="submitCreate">提交分诊</el-button>
              <el-button @click="resetForm">重置</el-button>
            </el-form-item>
          </el-form>
        </el-card>
      </el-col>
      <el-col :span="14">
        <el-card>
          <template #header>
            <div style="display: flex; justify-content: space-between; align-items: center;">
              <span>分诊记录</span>
              <div>
                <el-select v-model="filterLevel" placeholder="筛选级别" clearable style="width: 120px; margin-right: 10px;" size="small">
                  <el-option label="危急" :value="1" />
                  <el-option label="急症" :value="2" />
                  <el-option label="普通" :value="3" />
                  <el-option label="非急" :value="4" />
                </el-select>
                <el-select v-model="filterStatus" placeholder="筛选状态" clearable style="width: 120px; margin-right: 10px;" size="small">
                  <el-option label="待就诊" :value="0" />
                  <el-option label="已就诊" :value="1" />
                  <el-option label="已转诊" :value="2" />
                  <el-option label="已取消" :value="3" />
                </el-select>
                <el-button type="primary" size="small" @click="fetchList">查询</el-button>
              </div>
            </div>
          </template>
          <el-table :data="list" v-loading="loading" size="small">
            <el-table-column label="级别" width="70">
              <template #default="{row}">
                <el-tag v-if="row.level===1" type="danger" effect="dark">危急</el-tag>
                <el-tag v-else-if="row.level===2" type="warning" effect="dark">急症</el-tag>
                <el-tag v-else-if="row.level===3" type="">普通</el-tag>
                <el-tag v-else type="success">非急</el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="patient_name" label="病人" width="100" />
            <el-table-column prop="symptom" label="症状" show-overflow-tooltip />
            <el-table-column prop="department_name" label="科室" width="100" />
            <el-table-column label="生命体征" width="120">
              <template #default="{row}">
                <div v-if="row.temperature">{{ row.temperature }}℃</div>
                <div v-if="row.blood_pressure">{{ row.blood_pressure }}mmHg</div>
              </template>
            </el-table-column>
            <el-table-column prop="status_text" label="状态" width="80">
              <template #default="{row}">
                <el-tag v-if="row.status===0" type="warning">{{ row.status_text }}</el-tag>
                <el-tag v-else-if="row.status===1" type="success">{{ row.status_text }}</el-tag>
                <el-tag v-else type="info">{{ row.status_text }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="create_time" label="时间" width="140" />
            <el-table-column label="操作" width="180">
              <template #default="{row}">
                <el-button v-if="row.status===0" size="small" type="success" @click="updateStatus(row, 1)">接诊</el-button>
                <el-button v-if="row.status===0" size="small" @click="updateStatus(row, 2)">转诊</el-button>
                <el-button size="small" type="danger" @click="updateStatus(row, 3)">取消</el-button>
              </template>
            </el-table-column>
          </el-table>
        </el-card>
      </el-col>
    </el-row>
  </div>
</template>

<script setup>
import { ref, onMounted, watch } from "vue";
import { ElMessage } from "element-plus";
import { createTriageRecord, getTriageList, updateTriageStatus } from "@/api/triageDesk";
import { getDepartmentList } from "@/api/admin";

const form = ref({ level: 3 });
const list = ref([]);
const loading = ref(false);
const departments = ref([]);
const filterLevel = ref("");
const filterStatus = ref(0);

const loadDepartments = async () => {
  const res = await getDepartmentList();
  departments.value = res.data || [];
};

const fetchList = async () => {
  loading.value = true;
  const params = {};
  if (filterLevel.value !== "") params.level = filterLevel.value;
  if (filterStatus.value !== "") params.status = filterStatus.value;
  try {
    const res = await getTriageList(params);
    list.value = res.data || [];
  } catch (e) {
    ElMessage.error(e.msg || "查询失败");
  }
  loading.value = false;
};

const submitCreate = async () => {
  if (!form.value.identity) {
    ElMessage.warning("请输入身份证号");
    return;
  }
  try {
    const res = await createTriageRecord(form.value);
    if (res.code === 200) {
      ElMessage.success("分诊记录创建成功");
      resetForm();
      fetchList();
    } else {
      ElMessage.error(res.msg || "创建失败");
    }
  } catch (e) {
    ElMessage.error(e.msg || "创建失败");
  }
};

const resetForm = () => {
  form.value = { level: 3 };
};

const updateStatus = async (row, status) => {
  try {
    await updateTriageStatus({ triage_record_id: row.triage_record_id, status });
    ElMessage.success("状态更新成功");
    fetchList();
  } catch (e) {
    ElMessage.error(e.msg || "操作失败");
  }
};

watch([filterLevel, filterStatus], fetchList, { immediate: false });

onMounted(() => {
  loadDepartments();
  fetchList();
});
</script>
