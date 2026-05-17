<template>
  <div class="app-container">
    <vab-page-header title="药品不良反应监测" description="记录和跟踪药品不良反应事件" />
    <el-card>
      <div class="page-toolbar">
        <el-button type="primary" @click="handleAdd">上报ADR</el-button>
      </div>
      <el-table :data="list" v-loading="loading" empty-text="暂无记录">
        <el-table-column prop="patient_name" label="患者" />
        <el-table-column prop="pharmaceutical_name" label="药品" />
        <el-table-column prop="symptom" label="症状" show-overflow-tooltip />
        <el-table-column prop="severity_text" label="严重程度" width="100" />
        <el-table-column prop="status_text" label="状态" width="100" />
        <el-table-column prop="report_time" label="上报时间" width="160" />
        <el-table-column label="操作" width="150">
          <template #default="{row}">
            <el-button v-if="row.status===0" size="small" type="primary" @click="updateStatus(row,1)">确认</el-button>
            <el-button v-if="row.status===1" size="small" type="success" @click="updateStatus(row,2)">处理</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>
    <el-dialog v-model="dialogVisible" title="上报ADR" width="500px">
      <el-form :model="form" label-width="80px" class="dialog-form">
        <el-form-item label="患者">
          <el-select v-model="form.patient_id" placeholder="选择患者" filterable class="form-full-width">
            <el-option v-for="p in patients" :key="p.patient_id" :label="p.name" :value="p.patient_id" />
          </el-select>
        </el-form-item>
        <el-form-item label="药品">
          <el-select v-model="form.pharmaceutical_id" placeholder="选择药品" filterable class="form-full-width">
            <el-option v-for="d in pharmaceuticals" :key="d.pharmaceutical_id" :label="d.name" :value="d.pharmaceutical_id" />
          </el-select>
        </el-form-item>
        <el-form-item label="症状"><el-input v-model="form.symptom" type="textarea" :rows="3" /></el-form-item>
        <el-form-item label="严重程度">
          <el-radio-group v-model="form.severity">
            <el-radio :label="1">轻度</el-radio><el-radio :label="2">中度</el-radio><el-radio :label="3">重度</el-radio>
          </el-radio-group>
        </el-form-item>
      </el-form>
      <template #footer><el-button @click="dialogVisible=false">取消</el-button><el-button type="primary" @click="submit">确定</el-button></template>
    </el-dialog>
  </div>
</template>
<script setup>
import { ref, onMounted } from "vue";
import { ElMessage } from "element-plus";
import { createAdverseReaction, getAdverseReactionList, updateAdrStatus } from "@/api/adverseReaction";
import { getPatientList } from "@/api/admin";
import { getPharmaceuticalList } from "@/api/pharmacy";

const list = ref([]), loading = ref(false), dialogVisible = ref(false), form = ref({severity: 1});
const patients = ref([]);
const pharmaceuticals = ref([]);

const fetchList = async () => {
  loading.value = true;
  const res = await getAdverseReactionList();
  list.value = res.data || [];
  loading.value = false;
};

const loadPatients = async () => {
  try {
    const res = await getPatientList();
    patients.value = res.data || [];
  } catch (e) { console.error("获取患者失败", e); }
};

const loadPharmaceuticals = async () => {
  try {
    const res = await getPharmaceuticalList();
    pharmaceuticals.value = res.data || [];
  } catch (e) { console.error("获取药品失败", e); }
};

const handleAdd = () => { form.value = { severity: 1 }; dialogVisible.value = true; };
const submit = async () => {
  try {
    await createAdverseReaction(form.value);
    ElMessage.success("上报成功");
    dialogVisible.value = false;
    fetchList();
  } catch (e) { ElMessage.error(e.msg || "上报失败"); }
};
const updateStatus = async (row, status) => {
  try {
    await updateAdrStatus({ reaction_id: row.reaction_id, status });
    ElMessage.success("状态更新成功");
    fetchList();
  } catch (e) { ElMessage.error(e.msg || "更新失败"); }
};

onMounted(() => {
  fetchList();
  loadPatients();
  loadPharmaceuticals();
});
</script>
