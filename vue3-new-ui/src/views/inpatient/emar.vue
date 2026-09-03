<template>
  <div class="app-container">
    <vab-page-header title="eMAR 扫码给药" description="核对患者腕带与医嘱药品条码，形成可追溯给药闭环" />
    <el-tabs v-model="activeTab" @tab-change="loadCurrentTab">
      <el-tab-pane label="待扫码给药" name="pending">
        <el-card>
          <el-button type="primary" @click="loadPending">刷新</el-button>
          <el-table :data="pending" v-loading="loading" style="margin-top: 16px" empty-text="暂无待执行药品医嘱">
            <el-table-column prop="patient_name" label="患者" width="120" />
            <el-table-column prop="item_names" label="药品" min-width="220" />
            <el-table-column prop="planned_time" label="计划时间" width="180" />
            <el-table-column prop="order_type_text" label="类型" width="90" />
            <el-table-column label="操作" width="120">
              <template #default="{ row }">
                <el-button type="primary" size="small" @click="openVerify(row)">开始扫码</el-button>
              </template>
            </el-table-column>
          </el-table>
        </el-card>
      </el-tab-pane>
      <el-tab-pane label="给药记录" name="history">
        <el-card>
          <el-table :data="history" v-loading="loading" empty-text="暂无给药记录">
            <el-table-column prop="patient_name" label="患者" width="120" />
            <el-table-column prop="medications" label="药品" min-width="220">
              <template #default="{ row }">{{ row.medications.join("、") }}</template>
            </el-table-column>
            <el-table-column prop="nurse_name" label="执行护士" width="120" />
            <el-table-column prop="status_text" label="状态" width="100" />
            <el-table-column prop="administration_time" label="给药时间" width="180" />
            <el-table-column prop="note" label="备注" />
          </el-table>
          <el-pagination v-model:current-page="page" :page-size="20" :total="total" @current-change="loadHistory" />
        </el-card>
      </el-tab-pane>
    </el-tabs>

    <el-dialog v-model="verifyVisible" title="双条码核对" width="560px" :close-on-click-modal="false">
      <el-alert title="请先扫描患者腕带/就诊卡，再逐一扫描本次医嘱中的药品条码。" type="warning" :closable="false" />
      <el-form label-width="120px" style="margin-top: 18px">
        <el-form-item label="患者">
          <strong>{{ selected?.patient_name }}</strong>
        </el-form-item>
        <el-form-item label="医嘱药品">{{ selected?.item_names }}</el-form-item>
        <el-form-item label="患者条码">
          <el-input ref="patientBarcodeInput" v-model="verifyForm.patient_barcode" autocomplete="off" @keyup.enter="focusMedication" />
        </el-form-item>
        <el-form-item label="药品条码">
          <el-input ref="medicationBarcodeInput" v-model="barcodeText" type="textarea" :rows="4" placeholder="每行一个条码（扫码枪回车分隔）" />
        </el-form-item>
        <el-form-item v-if="verified" label="核对结果">
          <el-tag type="success">患者与 {{ verified.medications.join("、") }} 核对通过</el-tag>
        </el-form-item>
        <el-form-item label="给药备注">
          <el-input v-model="note" maxlength="300" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="verifyVisible = false">取消</el-button>
        <el-button v-if="!verified" type="primary" :loading="submitting" @click="verify">核对条码</el-button>
        <el-button v-else type="success" :loading="submitting" @click="administer">确认已给药</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { nextTick, onMounted, ref } from "vue";
import { ElMessage, ElMessageBox } from "element-plus";
import { administerMedication, getMedicationAdministrations, getMedicationExecutions, verifyMedication } from "@/api/emar";

const activeTab = ref("pending");
const loading = ref(false);
const submitting = ref(false);
const pending = ref([]);
const history = ref([]);
const total = ref(0);
const page = ref(1);
const verifyVisible = ref(false);
const selected = ref(null);
const verified = ref(null);
const verifyForm = ref({ patient_barcode: "" });
const barcodeText = ref("");
const note = ref("");
const patientBarcodeInput = ref(null);
const medicationBarcodeInput = ref(null);

const loadPending = async () => {
  loading.value = true;
  try {
    const response = await getMedicationExecutions({ status: 0, page: 1, page_size: 100 });
    pending.value = response.data || [];
  } finally {
    loading.value = false;
  }
};
const loadHistory = async () => {
  loading.value = true;
  try {
    const response = await getMedicationAdministrations({ page: page.value, page_size: 20 });
    history.value = response.data || [];
    total.value = response.total || 0;
  } finally {
    loading.value = false;
  }
};
const loadCurrentTab = () => (activeTab.value === "pending" ? loadPending() : loadHistory());
const openVerify = (row) => {
  selected.value = row;
  verified.value = null;
  verifyForm.value.patient_barcode = "";
  barcodeText.value = "";
  note.value = "";
  verifyVisible.value = true;
  nextTick(() => patientBarcodeInput.value?.focus());
};
const focusMedication = () => medicationBarcodeInput.value?.focus();
const verify = async () => {
  const medication_barcodes = barcodeText.value.split(/[\n,，]/).map((value) => value.trim()).filter(Boolean);
  if (!verifyForm.value.patient_barcode.trim() || !medication_barcodes.length) return ElMessage.warning("请扫描患者与药品条码");
  submitting.value = true;
  try {
    const response = await verifyMedication({
      execution_id: selected.value.execution_id,
      patient_barcode: verifyForm.value.patient_barcode.trim(),
      medication_barcodes,
    });
    verified.value = response.data;
    ElMessage.success("双条码核对通过");
  } finally {
    submitting.value = false;
  }
};
const administer = async () => {
  await ElMessageBox.confirm("确认药品已按医嘱给予患者？此操作会写入给药记录。", "给药确认", { type: "warning" });
  submitting.value = true;
  try {
    await administerMedication({ administration_id: verified.value.administration_id, note: note.value });
    ElMessage.success("给药记录已保存");
    verifyVisible.value = false;
    await loadPending();
  } finally {
    submitting.value = false;
  }
};

onMounted(loadPending);
</script>
