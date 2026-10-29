<template>
  <div class="app-container">
    <p>ADR处理与药物过敏分别登记；确认ADR不会自动新增过敏记录。历史结果缺少明确说明时，须核实是已处理还是已排除。</p>
    <el-card>
      <div class="page-toolbar">
        <el-button v-if="canManageAdr" type="primary" @click="handleAdd">上报ADR</el-button>
        <span v-else>药师按处方业务范围查看患者记录；处理结果由管理角色核实。</span>
      </div>
      <el-table :data="list" v-loading="loading" empty-text="暂无记录">
        <el-table-column prop="patient_name" label="患者" />
        <el-table-column prop="pharmaceutical_name" label="药品" />
        <el-table-column prop="symptom" label="症状" show-overflow-tooltip />
        <el-table-column prop="severity_text" label="严重程度" width="100" />
        <el-table-column label="状态" width="150"><template #default="{ row }">{{ row.status === 2 && !row.status_resolution ? '历史含义待核实' : row.status_text }}</template></el-table-column>
        <el-table-column prop="report_time" label="上报时间" width="160" />
        <el-table-column label="操作" width="380">
          <template #default="{row}">
            <el-button v-if="canManageAdr && row.status===0" size="small" type="primary" @click="updateStatus(row,1)">确认</el-button>
            <el-button v-if="canManageAdr && row.status===1" size="small" type="success" @click="updateStatus(row,2)">处理</el-button>
            <el-button v-if="canManageAdr && (row.status === 0 || row.status === 2 && !row.status_resolution)" size="small" @click="openResolution(row)">{{ row.status === 0 ? '排除ADR' : '核实历史结果' }}</el-button>
            <ai-action v-if="canUseClinicalAi && row.patient_id" label="AI ADR资料分析" title="AI 所选ADR记录与信号辅助" :patient-id="row.patient_id" :initial-input="{ reaction_id: String(row.reaction_id) }" :feature-keys="['adr_signal', 'allergy_review', 'patient_summary']" initial-feature="adr_signal" />
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
    <el-dialog v-model="resolutionDialog" title="ADR处理结果核实" width="540px">
      <p>原上报 #{{ resolutionRow?.reaction_id }}。本次结果为人工处理记录，不自动认定药物因果关系或药物过敏。</p>
      <el-form label-position="top" :disabled="resolutionSaving">
        <el-form-item label="明确处理结果"><el-select v-model="resolutionForm.resolution"><el-option v-if="resolutionRow?.status === 2" label="已处理" value="processed" /><el-option label="已排除ADR" value="excluded" /></el-select></el-form-item>
        <el-form-item label="核实依据或说明"><el-input v-model="resolutionForm.note" type="textarea" :rows="4" maxlength="1000" placeholder="填写查阅了哪些原记录、为何采用该处理结果" /></el-form-item>
      </el-form>
      <template #footer><el-button @click="resolutionDialog = false">关闭</el-button><el-button type="primary" :loading="resolutionSaving" :disabled="resolutionForm.note.trim().length < 3" @click="saveResolution">保存处理结果</el-button></template>
    </el-dialog>
  </div>
</template>
<script setup>
import { computed, ref, onMounted } from "vue";
import { useStore } from "vuex";
import { ElMessage } from "element-plus";
import { createAdverseReaction, getAdverseReactionList, updateAdrStatus } from "@/api/adverseReaction";
import { getPatientList } from "@/api/admin";
import { getPharmaceuticalList } from "@/api/pharmacy";
import AiAction from "@/components/AIAction/index.vue";

const list = ref([]), loading = ref(false), dialogVisible = ref(false), form = ref({severity: 1});
const patients = ref([]);
const pharmaceuticals = ref([]);
const store = useStore();
const canManageAdr = computed(() => store.getters["user/permissions"].some(role => ["super_admin", "admin"].includes(role)));
const canUseClinicalAi = computed(() => store.getters["user/permissions"].some(role => ["super_admin", "doctor", "director", "pharmacist"].includes(role)));
const resolutionDialog = ref(false), resolutionRow = ref(null), resolutionSaving = ref(false), resolutionForm = ref({ resolution: "excluded", note: "" });

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
  } catch (e) { ElMessage.error("获取患者失败"); }
};

const loadPharmaceuticals = async () => {
  try {
    const res = await getPharmaceuticalList();
    pharmaceuticals.value = res.data || [];
  } catch (e) { ElMessage.error("获取药品失败"); }
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
const openResolution = row => { resolutionRow.value = row; resolutionForm.value = { resolution: row.status === 0 ? "excluded" : "processed", note: "" }; resolutionDialog.value = true; };
const saveResolution = async () => {
  if (!resolutionRow.value) return;
  resolutionSaving.value = true;
  try { await updateAdrStatus({ reaction_id: resolutionRow.value.reaction_id, status: 2, ...resolutionForm.value }); resolutionDialog.value = false; await fetchList(); ElMessage.success("已记录明确处理结果"); }
  finally { resolutionSaving.value = false; }
};

onMounted(() => {
  fetchList();
  loadPatients();
  loadPharmaceuticals();
});
</script>
