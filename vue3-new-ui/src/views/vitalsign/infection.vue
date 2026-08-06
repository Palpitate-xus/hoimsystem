<template>
  <div class="app-container">
    <vab-page-header title="院感监测" description="感染病例、暴发预警、消毒监测和职业暴露上报" />
    <el-tabs v-model="activeTab">
      <el-tab-pane label="感染病例" name="cases">
        <div class="page-toolbar"><el-button type="primary" @click="caseDialog = true">上报感染病例</el-button></div>
        <el-table :data="cases" border empty-text="暂无感染病例"><el-table-column prop="patient_name" label="患者" /><el-table-column prop="department_name" label="科室" /><el-table-column prop="infection_type" label="感染类型" /><el-table-column prop="pathogen" label="病原体" /><el-table-column prop="status_text" label="状态" /><el-table-column prop="onset_date" label="发病日期" /></el-table>
      </el-tab-pane>
      <el-tab-pane label="暴发预警" name="alerts">
        <el-alert title="同一感染类型/病原体30天内达到3例将标记为预警" type="warning" :closable="false" style="margin-bottom: 16px" />
        <el-table :data="alerts" border empty-text="暂无聚集性病例"><el-table-column prop="infection_type" label="感染类型" /><el-table-column prop="pathogen" label="病原体" /><el-table-column prop="case_count" label="病例数" /><el-table-column prop="alert" label="预警"><template #default="{ row }"><el-tag :type="row.alert ? 'danger' : 'success'">{{ row.alert ? "需关注" : "正常" }}</el-tag></template></el-table-column></el-table>
      </el-tab-pane>
      <el-tab-pane label="消毒监测" name="disinfection">
        <div class="page-toolbar"><el-button type="primary" @click="disinfectionDialog = true">新增监测记录</el-button></div>
        <el-table :data="disinfection" border empty-text="暂无监测记录"><el-table-column prop="area" label="区域" /><el-table-column prop="item" label="监测项目" /><el-table-column prop="result" label="结果" /><el-table-column prop="pass_flag" label="是否合格"><template #default="{ row }">{{ row.pass_flag ? "合格" : "不合格" }}</template></el-table-column><el-table-column prop="monitor_time" label="监测时间" /></el-table>
      </el-tab-pane>
      <el-tab-pane label="职业暴露" name="exposure">
        <div class="page-toolbar"><el-button type="primary" @click="exposureDialog = true">上报职业暴露</el-button></div>
        <el-table :data="exposures" border empty-text="暂无职业暴露记录"><el-table-column prop="exposure_type" label="暴露类型" /><el-table-column prop="body_site" label="暴露部位" /><el-table-column prop="description" label="经过" show-overflow-tooltip /><el-table-column prop="status_text" label="状态" /><el-table-column prop="exposure_time" label="发生时间" /></el-table>
      </el-tab-pane>
    </el-tabs>

    <el-dialog v-model="caseDialog" title="上报感染病例" width="520px"><el-form :model="caseForm" label-width="100px"><el-form-item label="患者ID"><el-input v-model="caseForm.patient_id" /></el-form-item><el-form-item label="感染类型"><el-input v-model="caseForm.infection_type" /></el-form-item><el-form-item label="病原体"><el-input v-model="caseForm.pathogen" /></el-form-item><el-form-item label="发病日期"><el-date-picker v-model="caseForm.onset_date" value-format="YYYY-MM-DD" /></el-form-item><el-form-item label="描述"><el-input v-model="caseForm.description" type="textarea" /></el-form-item></el-form><template #footer><el-button @click="caseDialog = false">取消</el-button><el-button type="primary" @click="saveCase">提交</el-button></template></el-dialog>
    <el-dialog v-model="disinfectionDialog" title="新增消毒监测" width="520px"><el-form :model="disinfectionForm" label-width="100px"><el-form-item label="区域"><el-input v-model="disinfectionForm.area" /></el-form-item><el-form-item label="监测项目"><el-input v-model="disinfectionForm.item" /></el-form-item><el-form-item label="结果"><el-input v-model="disinfectionForm.result" /></el-form-item><el-form-item label="标准"><el-input v-model="disinfectionForm.standard" /></el-form-item></el-form><template #footer><el-button @click="disinfectionDialog = false">取消</el-button><el-button type="primary" @click="saveDisinfection">提交</el-button></template></el-dialog>
    <el-dialog v-model="exposureDialog" title="上报职业暴露" width="520px"><el-form :model="exposureForm" label-width="100px"><el-form-item label="暴露类型"><el-input v-model="exposureForm.exposure_type" /></el-form-item><el-form-item label="暴露部位"><el-input v-model="exposureForm.body_site" /></el-form-item><el-form-item label="经过"><el-input v-model="exposureForm.description" type="textarea" /></el-form-item><el-form-item label="处置措施"><el-input v-model="exposureForm.action_taken" type="textarea" /></el-form-item></el-form><template #footer><el-button @click="exposureDialog = false">取消</el-button><el-button type="primary" @click="saveExposure">提交</el-button></template></el-dialog>
  </div>
</template>

<script setup>
import { onMounted, ref } from "vue";
import { ElMessage } from "element-plus";
import { createDisinfectionRecord, createExposureRecord, createInfectionCase, getDisinfectionRecords, getExposureRecords, getInfectionCases, getOutbreakAlerts } from "@/api/infection";

const activeTab = ref("cases");
const cases = ref([]); const alerts = ref([]); const disinfection = ref([]); const exposures = ref([]);
const caseDialog = ref(false); const disinfectionDialog = ref(false); const exposureDialog = ref(false);
const caseForm = ref({ patient_id: "", infection_type: "", pathogen: "", onset_date: "", description: "" });
const disinfectionForm = ref({ area: "", item: "", result: "", standard: "" });
const exposureForm = ref({ exposure_type: "", body_site: "", description: "", action_taken: "" });
const load = async () => { try { const [c, a, d, e] = await Promise.all([getInfectionCases(), getOutbreakAlerts(), getDisinfectionRecords(), getExposureRecords()]); cases.value = c.data || []; alerts.value = a.data || []; disinfection.value = d.data || []; exposures.value = e.data || []; } catch (error) { ElMessage.error(error.msg || "获取院感数据失败"); } };
const saveCase = async () => { try { await createInfectionCase(caseForm.value); ElMessage.success("病例已上报"); caseDialog.value = false; await load(); } catch (e) { ElMessage.error(e.msg || "上报失败"); } };
const saveDisinfection = async () => { try { await createDisinfectionRecord(disinfectionForm.value); ElMessage.success("监测记录已保存"); disinfectionDialog.value = false; await load(); } catch (e) { ElMessage.error(e.msg || "保存失败"); } };
const saveExposure = async () => { try { await createExposureRecord(exposureForm.value); ElMessage.success("职业暴露已上报"); exposureDialog.value = false; await load(); } catch (e) { ElMessage.error(e.msg || "上报失败"); } };
onMounted(load);
</script>
