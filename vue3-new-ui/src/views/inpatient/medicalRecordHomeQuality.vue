<template>
  <div class="app-container">
    <vab-page-header title="病案首页质控" description="检查病案首页完整性，记录问题、评分和整改依据" />
    <el-row :gutter="16" style="margin-bottom: 16px">
      <el-col :span="6"><el-card><div class="metric-label">检查总数</div><div class="metric-value">{{ summary.total }}</div></el-card></el-col>
      <el-col :span="6"><el-card><div class="metric-label">错误项</div><div class="metric-value danger">{{ summary.error_count }}</div></el-card></el-col>
      <el-col :span="6"><el-card><div class="metric-label">警告项</div><div class="metric-value warning">{{ summary.warning_count }}</div></el-card></el-col>
      <el-col :span="6"><el-card><div class="metric-label">平均得分</div><div class="metric-value">{{ summary.average_score }}</div></el-card></el-col>
    </el-row>
    <el-card>
      <template #header><div class="page-toolbar"><el-button type="primary" @click="openCheck">新增质控检查</el-button><el-button size="small" @click="loadAll">刷新</el-button></div></template>
      <el-table :data="checks" v-loading="loading" size="small" empty-text="暂无质控记录">
        <el-table-column prop="admission_no" label="住院号" width="130" /><el-table-column prop="patient_name" label="患者" width="90" /><el-table-column prop="check_item" label="检查项目" width="130" />
        <el-table-column label="结果" width="85"><template #default="{ row }"><el-tag :type="row.check_result === 2 ? 'danger' : row.check_result === 1 ? 'warning' : 'success'" size="small">{{ row.check_result_text }}</el-tag></template></el-table-column>
        <el-table-column prop="issue" label="问题说明" show-overflow-tooltip /><el-table-column prop="score" label="得分" width="70" /><el-table-column prop="checker_name" label="检查人" width="90" />
      </el-table>
    </el-card>
    <el-dialog v-model="dialogVisible" title="新增质控检查" width="520px">
      <el-form :model="form" label-width="100px">
        <el-form-item label="病案首页" required><el-select v-model="form.home_id" filterable placeholder="请选择病案首页" style="width: 100%"><el-option v-for="item in homes" :key="item.home_id" :label="`${item.patient_name}（${item.admission_no}）`" :value="item.home_id" /></el-select></el-form-item>
        <el-form-item label="检查项目" required><el-input v-model="form.check_item" maxlength="100" placeholder="例如：出院诊断" /></el-form-item>
        <el-form-item label="检查结果"><el-radio-group v-model="form.check_result"><el-radio-button :label="0">通过</el-radio-button><el-radio-button :label="1">警告</el-radio-button><el-radio-button :label="2">错误</el-radio-button></el-radio-group></el-form-item>
        <el-form-item label="问题说明"><el-input v-model="form.issue" type="textarea" :rows="3" maxlength="500" /></el-form-item><el-form-item label="得分"><el-input-number v-model="form.score" :min="0" :max="100" /></el-form-item>
      </el-form>
      <template #footer><el-button @click="dialogVisible = false">取消</el-button><el-button type="primary" @click="save">保存检查</el-button></template>
    </el-dialog>
  </div>
</template>

<script setup>
import { onMounted, ref } from "vue";
import { ElMessage } from "element-plus";
import { getMedicalRecordHomeList } from "@/api/medicalRecordHome";
import { getMedicalRecordHomeQualityList, checkMedicalRecordHomeQuality, getMedicalRecordHomeQualitySummary } from "@/api/medicalRecordHomeQuality";

const loading = ref(false); const checks = ref([]); const homes = ref([]); const summary = ref({ total: 0, error_count: 0, warning_count: 0, average_score: 0 }); const dialogVisible = ref(false); const form = ref({ home_id: "", check_item: "", check_result: 0, issue: "", score: 100 });
const loadAll = async () => { loading.value = true; try { const [list, stats] = await Promise.all([getMedicalRecordHomeQualityList({}), getMedicalRecordHomeQualitySummary()]); checks.value = list.data || []; summary.value = stats.data || summary.value; } finally { loading.value = false; } };
const openCheck = async () => { homes.value = (await getMedicalRecordHomeList({})).data || []; form.value = { home_id: "", check_item: "", check_result: 0, issue: "", score: 100 }; dialogVisible.value = true; };
const save = async () => { if (!form.value.home_id || !form.value.check_item.trim()) return ElMessage.warning("请选择病案并填写检查项目"); await checkMedicalRecordHomeQuality(form.value); ElMessage.success("质控检查已保存"); dialogVisible.value = false; await loadAll(); };
onMounted(loadAll);
</script>

<style scoped>
.metric-label { color: #909399; font-size: 13px; }
.metric-value { color: #303133; font-size: 24px; font-weight: 600; margin-top: 8px; }
.metric-value.danger { color: #f56c6c; }
.metric-value.warning { color: #e6a23c; }
</style>
