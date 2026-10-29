<template>
  <div class="app-container">
    <el-card>
      <div class="page-toolbar">
        <el-button type="primary" @click="handleAdd">开处方</el-button>
        <el-input
          v-model="searchQuery"
          placeholder="搜索处方"
          clearable
          class="page-search-input"
        ></el-input>
        <el-button type="primary" @click="fetchList">搜索</el-button>
      </div>
      <el-table :data="paginatedList" v-loading="loading" border empty-text="暂无数据">
        <el-table-column prop="doctor_name" label="医生"  sortable />
        <el-table-column prop="patient_name" label="患者"  sortable />
        <el-table-column prop="status" label="状态">
          <template #default="{row}">
            <el-tag v-if="row.status===0" type="warning">待审核</el-tag>
            <el-tag v-else-if="row.status===1" type="primary">已审核</el-tag>
            <el-tag v-else-if="row.status===2" type="success">已发药</el-tag>
            <el-tag v-else type="danger">已取消</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="create_time" label="创建时间"  sortable />
        <el-table-column label="药品明细">
          <template #default="{row}">
            <div v-for="(p, i) in row.phas" :key="i">{{ p.name }} x{{ p.number }}</div>
          </template>
        </el-table-column>
        <el-table-column prop="amount" label="金额" width="80" />
        <el-table-column label="操作" width="290">
          <template #default="{row}">
            <el-button v-if="row.status===0 && row.charge_id" size="small" type="primary" @click="deskCharge(row)">诊间收费</el-button>
            <el-button size="small" type="danger" @click="cancel(row)">取消</el-button>
            <ai-action label="核查处方" title="处方核查" :patient-id="row.patient_id" :initial-input="{ prescription_id: row.uuid }" :feature-keys="['interaction_review', 'allergy_review', 'drug_comparison', 'dose_review', 'antimicrobial_review']" initial-feature="interaction_review" />
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

    <el-dialog v-model="dialogVisible" title="开处方" width="700px">
      <el-form :model="form" label-width="100px" class="dialog-form">
        <el-form-item label="患者">
          <el-select v-model="form.patient" placeholder="请选择患者" class="form-full-width" filterable @change="onPatientChange">
            <el-option v-for="p in patientOptions" :key="p.id" :label="p.name" :value="p.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="常用模板">
          <el-select v-model="selectedTemplateId" clearable placeholder="选择模板自动带入药品" class="form-full-width" @change="applyTemplate">
            <el-option v-for="template in templates" :key="template.template_id" :label="template.name" :value="template.template_id" />
          </el-select>
        </el-form-item>
        <el-alert
          v-if="selectedPatientAllergy"
          :title="'过敏史：' + selectedPatientAllergy"
          type="warning"
          :closable="false"
          style="margin-bottom: 15px; margin-left: 100px;"
        />
        <el-form-item label="药品">
          <div v-for="(item, i) in form.phas" :key="i" style="margin-bottom:10px">
            <el-select v-model="item.id" placeholder="选择药品" style="width:200px;margin-right:10px" filterable>
              <el-option v-for="p in pharmaceuticals" :key="p.id" :label="p.name" :value="p.id" />
            </el-select>
            <el-input-number v-model="item.number" :min="1" style="width:120px;margin-right:10px" />
            <el-button type="danger" size="small" @click="removePharmaceutical(i)">删除</el-button>
            <el-tag v-if="getAntibioticLevel(item.id) === 2" type="warning" size="small" style="margin-left:5px">限制级抗菌药</el-tag>
            <el-tag v-if="getAntibioticLevel(item.id) === 3" type="danger" size="small" style="margin-left:5px">特殊使用级抗菌药</el-tag>
            <div style="display:flex;flex-wrap:wrap;gap:8px;margin-top:8px">
              <el-input-number v-model="item.dosage" :min="0.000001" :precision="6" aria-label="每次剂量" placeholder="每次剂量" style="width:150px" />
              <el-select v-model="item.dose_unit" filterable allow-create default-first-option clearable placeholder="剂量单位" style="width:110px"><el-option v-for="unit in ['mg','g','μg','mL','片','粒','支','单位']" :key="unit" :label="unit" :value="unit" /></el-select>
              <el-input v-model="item.frequency" placeholder="频次，如 bid" maxlength="40" style="width:130px" />
              <el-select v-model="item.route" filterable allow-create default-first-option clearable placeholder="给药途径" style="width:120px"><el-option v-for="route in ['口服','静滴','静注','肌注','皮下','外用']" :key="route" :label="route" :value="route" /></el-select>
              <el-input-number v-model="item.duration_days" :min="1" :max="3650" aria-label="疗程天数" placeholder="疗程天数" style="width:130px" />
            </div>
          </div>
          <el-button type="primary" size="small" @click="addPharmaceutical">添加药品</el-button>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible=false">取消</el-button>
        <el-button type="primary" @click="submit">确定</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, onMounted, computed } from "vue";
import AiAction from "@/components/AIAction/index.vue";
import { ElMessage } from "element-plus";
import { getPrescriptionList, createPrescription, cancelPrescription, getPrescriptionTemplates, applyPrescriptionTemplate } from "@/api/doctor";
import { commitCharge } from "@/api/charge";
import { getPharmaceuticalList } from "@/api/pharmacy";
import { getPatientList } from "@/api/admin";

const list = ref([]);
const searchQuery = ref("");
const currentPage = ref(1);
const pageSize = ref(10);
const total = ref(0);
const paginatedList = computed(() => {
  const start = (currentPage.value - 1) * pageSize.value;
  return list.value.slice(start, start + pageSize.value);
});

const pharmaceuticals = ref([]);
const patientOptions = ref([]);
const loading = ref(false);
const dialogVisible = ref(false);
const form = ref({ patient: null, phas: [] });
const selectedPatientAllergy = ref("");
const templates = ref([]);
const selectedTemplateId = ref(null);

const fetchList = async () => {
  loading.value = true;
  const res = await getPrescriptionList(searchQuery.value);
  list.value = res.data || [];
  total.value = list.value.length;
  loading.value = false;
};

const handleAdd = async () => {
  const phRes = await getPharmaceuticalList(searchQuery.value);
  pharmaceuticals.value = phRes.data || [];
  const pRes = await getPatientList(searchQuery.value);
  patientOptions.value = pRes.data || [];
  const templateRes = await getPrescriptionTemplates();
  templates.value = templateRes.data || [];
  form.value = { patient: null, phas: [{ id: null, number: 1 }] };
  selectedPatientAllergy.value = "";
  selectedTemplateId.value = null;
  dialogVisible.value = true;
};

const applyTemplate = async (templateId) => {
  if (!templateId) return;
  try {
    const res = await applyPrescriptionTemplate({ template_id: templateId });
    form.value.phas = (res.data || []).map((item) => ({ id: item.id, number: item.number }));
    ElMessage.success("模板已带入处方");
  } catch (e) {
    ElMessage.error(e.msg || "模板应用失败");
  }
};

const onPatientChange = (pid) => {
  const p = patientOptions.value.find((x) => x.id === pid);
  selectedPatientAllergy.value = p && p.allergy_history ? p.allergy_history : "";
};

const addPharmaceutical = () => {
  form.value.phas.push({ id: null, number: 1, dosage: null, dose_unit: "", frequency: "", route: "", duration_days: null });
};

const removePharmaceutical = (i) => {
  form.value.phas.splice(i, 1);
};

const getAntibioticLevel = (id) => {
  const pha = pharmaceuticals.value.find((p) => p.id === id);
  return pha ? pha.antibiotic_level : 0;
};

const submit = async () => {
  const special = form.value.phas.filter((item) => getAntibioticLevel(item.id) === 3);
  if (special.length > 0) {
    ElMessage.warning("特殊使用级抗菌药需抗菌药物管理组审批后方可开具");
    return;
  }
  try {
    await createPrescription(form.value);
    ElMessage.success("开方成功");
    dialogVisible.value = false;
    fetchList();
  } catch (e) {
    ElMessage.error(e.msg || "开方失败");
  }
};

const deskCharge = async (row) => {
  try {
    await commitCharge({ id: row.charge_id });
    ElMessage.success("诊间收费成功");
    fetchList();
  } catch (e) {
    ElMessage.error(e.msg || "收费失败");
  }
};

const cancel = async (row) => {
  try {
    await cancelPrescription({ prescription_id: row.uuid });
    ElMessage.success("取消成功");
    fetchList();
  } catch (e) {
    ElMessage.error(e.msg || "取消失败");
  }
};

onMounted(fetchList);
</script>
