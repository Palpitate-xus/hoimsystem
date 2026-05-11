<template>
  <div class="app-container">
    <vab-page-header title="住院医嘱管理" description="开立、审核、执行住院医嘱" />
    <el-row :gutter="20">
      <el-col :span="6">
        <el-card>
          <template #header>
            <span>在院患者</span>
          </template>
          <el-input v-model="patientKeyword" placeholder="搜索患者" clearable size="small" style="margin-bottom: 10px;" />
          <el-table :data="filteredInpatients" size="small" highlight-current-row @current-change="onPatientSelect" empty-text="暂无在院患者">
            <el-table-column prop="bed_no" label="床号" width="60" />
            <el-table-column prop="patient_name" label="姓名" width="80" />
            <el-table-column prop="admission_diagnosis" label="诊断" show-overflow-tooltip />
          </el-table>
        </el-card>
      </el-col>
      <el-col :span="18">
        <el-card v-if="currentPatient">
          <template #header>
            <div style="display: flex; justify-content: space-between; align-items: center;">
              <span>{{ currentPatient.patient_name }} - {{ currentPatient.bed_no }}床 - 医嘱列表</span>
              <div>
                <el-radio-group v-model="orderFilterType" size="small" style="margin-right: 10px;">
                  <el-radio-button label="">全部</el-radio-button>
                  <el-radio-button :label="0">长期</el-radio-button>
                  <el-radio-button :label="1">临时</el-radio-button>
                </el-radio-group>
                <el-button type="primary" size="small" @click="openOrderDialog()">开立医嘱</el-button>
              </div>
            </div>
          </template>
          <el-table :data="filteredOrders" size="small" v-loading="orderLoading">
            <el-table-column type="expand">
              <template #default="{row}">
                <el-table :data="row.items" size="small" style="margin: 10px 20px;">
                  <el-table-column prop="item_name" label="名称" />
                  <el-table-column prop="dose" label="剂量" width="80" />
                  <el-table-column prop="frequency" label="频次" width="80" />
                  <el-table-column prop="route" label="途径" width="80" />
                  <el-table-column prop="days" label="天数" width="60" />
                  <el-table-column prop="total_price" label="金额" width="80">
                    <template #default="{row: item}">¥{{ item.total_price }}</template>
                  </el-table-column>
                </el-table>
              </template>
            </el-table-column>
            <el-table-column label="类型" width="70">
              <template #default="{row}">
                <el-tag v-if="row.order_type===0" type="success" size="small">长期</el-tag>
                <el-tag v-else type="warning" size="small">临时</el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="category_text" label="分类" width="70" />
            <el-table-column prop="priority_text" label="优先级" width="70" />
            <el-table-column prop="start_time" label="开始时间" width="140" />
            <el-table-column prop="stop_time" label="停止时间" width="140" />
            <el-table-column label="状态" width="70">
              <template #default="{row}">
                <el-tag v-if="row.status===0" size="small">{{ row.status_text }}</el-tag>
                <el-tag v-else-if="row.status===1" type="warning" size="small">{{ row.status_text }}</el-tag>
                <el-tag v-else-if="row.status===2" type="success" size="small">{{ row.status_text }}</el-tag>
                <el-tag v-else type="info" size="small">{{ row.status_text }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="note" label="备注" show-overflow-tooltip />
            <el-table-column label="操作" width="180">
              <template #default="{row}">
                <el-button v-if="row.status===0" size="small" type="primary" @click="auditOrder(row)">审核</el-button>
                <el-button v-if="row.status===1 || row.status===2" size="small" @click="stopOrder(row)">停止</el-button>
                <el-button v-if="row.status===0 || row.status===1" size="small" type="danger" @click="cancelOrder(row)">撤销</el-button>
              </template>
            </el-table-column>
          </el-table>
        </el-card>
        <el-card v-else style="text-align: center; padding: 60px; color: #999;">
          <div>请从左侧选择一个在院患者</div>
        </el-card>
      </el-col>
    </el-row>

    <!-- 开立医嘱对话框 -->
    <el-dialog v-model="orderDialogVisible" title="开立医嘱" width="700px">
      <el-form :model="orderForm" label-width="100px">
        <el-form-item label="医嘱类型">
          <el-radio-group v-model="orderForm.order_type">
            <el-radio-button :label="0">长期医嘱</el-radio-button>
            <el-radio-button :label="1">临时医嘱</el-radio-button>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="医嘱分类">
          <el-radio-group v-model="orderForm.category">
            <el-radio-button label="drug">药品</el-radio-button>
            <el-radio-button label="treatment">治疗</el-radio-button>
            <el-radio-button label="exam">检查</el-radio-button>
            <el-radio-button label="diet">饮食</el-radio-button>
            <el-radio-button label="nursing">护理</el-radio-button>
            <el-radio-button label="other">其他</el-radio-button>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="优先级">
          <el-radio-group v-model="orderForm.priority">
            <el-radio-button :label="0">常规</el-radio-button>
            <el-radio-button :label="1">紧急</el-radio-button>
            <el-radio-button :label="2">抢救</el-radio-button>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="医嘱项目">
          <div v-for="(item, idx) in orderItems" :key="idx" style="display: flex; gap: 5px; margin-bottom: 8px; align-items: center;">
            <el-input v-model="item.item_name" placeholder="名称" style="width: 120px;" />
            <el-input v-model="item.dose" placeholder="剂量" style="width: 80px;" />
            <el-input v-model="item.unit" placeholder="单位" style="width: 60px;" />
            <el-input v-model="item.frequency" placeholder="频次" style="width: 80px;" />
            <el-input v-model="item.route" placeholder="途径" style="width: 80px;" />
            <el-input-number v-model="item.days" :min="1" style="width: 70px;" />
            <el-input-number v-model="item.quantity" :min="1" style="width: 70px;" />
            <el-input-number v-model="item.unit_price" :min="0" :precision="2" style="width: 80px;" />
            <el-button type="danger" size="small" @click="removeItem(idx)">删除</el-button>
          </div>
          <el-button type="primary" size="small" @click="addItem">+ 添加项目</el-button>
        </el-form-item>
        <el-form-item label="备注">
          <el-input v-model="orderForm.note" type="textarea" :rows="2" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="orderDialogVisible = false">取消</el-button>
        <el-button type="primary" @click="submitOrder">确定</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from "vue";
import { ElMessage, ElMessageBox } from "element-plus";
import { getInpatientList } from "@/api/admission";
import { getInpatientOrderList, createInpatientOrder, auditInpatientOrder, stopInpatientOrder, cancelInpatientOrder } from "@/api/inpatientOrder";

const inpatients = ref([]);
const patientKeyword = ref("");
const currentPatient = ref(null);
const orders = ref([]);
const orderLoading = ref(false);
const orderFilterType = ref("");

const orderDialogVisible = ref(false);
const orderForm = ref({ order_type: 0, category: "drug", priority: 0 });
const orderItems = ref([{ item_name: "", dose: "", unit: "", frequency: "", route: "", days: 1, quantity: 1, unit_price: 0 }]);

const filteredInpatients = computed(() => {
  if (!patientKeyword.value) return inpatients.value;
  const kw = patientKeyword.value.toLowerCase();
  return inpatients.value.filter(p => p.patient_name.toLowerCase().includes(kw) || p.admission_no?.toLowerCase().includes(kw));
});

const filteredOrders = computed(() => {
  if (orderFilterType.value === "" || orderFilterType.value === undefined || orderFilterType.value === null) return orders.value;
  return orders.value.filter(o => o.order_type === orderFilterType.value);
});

const loadInpatients = async () => {
  const res = await getInpatientList({});
  inpatients.value = res.data || [];
};

const onPatientSelect = async (row) => {
  if (!row) return;
  currentPatient.value = row;
  await loadOrders(row.admission_id);
};

const loadOrders = async (admissionId) => {
  orderLoading.value = true;
  const res = await getInpatientOrderList({ admission_id: admissionId });
  orders.value = res.data || [];
  orderLoading.value = false;
};

const openOrderDialog = () => {
  orderForm.value = { order_type: 0, category: "drug", priority: 0 };
  orderItems.value = [{ item_name: "", dose: "", unit: "", frequency: "qd", route: "口服", days: 1, quantity: 1, unit_price: 0 }];
  orderDialogVisible.value = true;
};

const addItem = () => {
  orderItems.value.push({ item_name: "", dose: "", unit: "", frequency: "qd", route: "口服", days: 1, quantity: 1, unit_price: 0 });
};

const removeItem = (idx) => {
  orderItems.value.splice(idx, 1);
};

const submitOrder = async () => {
  if (!currentPatient.value) { ElMessage.warning("请先选择患者"); return; }
  const validItems = orderItems.value.filter(it => it.item_name.trim());
  if (validItems.length === 0) { ElMessage.warning("请至少填写一个医嘱项目"); return; }
  try {
    await createInpatientOrder({
      admission_id: currentPatient.value.admission_id,
      patient_id: currentPatient.value.patient_id,
      doctor_id: currentPatient.value.doctor_id,
      order_type: orderForm.value.order_type,
      category: orderForm.value.category,
      priority: orderForm.value.priority,
      note: orderForm.value.note,
      items: validItems,
    });
    ElMessage.success("医嘱开立成功");
    orderDialogVisible.value = false;
    loadOrders(currentPatient.value.admission_id);
  } catch (e) {
    ElMessage.error(e.msg || "操作失败");
  }
};

const auditOrder = async (row) => {
  try {
    await auditInpatientOrder({ order_id: row.order_id });
    ElMessage.success("审核成功");
    loadOrders(currentPatient.value.admission_id);
  } catch (e) {
    ElMessage.error(e.msg || "操作失败");
  }
};

const stopOrder = async (row) => {
  try {
    await ElMessageBox.confirm("确定停止该医嘱？", "提示", { type: "warning" });
    await stopInpatientOrder({ order_id: row.order_id });
    ElMessage.success("停止成功");
    loadOrders(currentPatient.value.admission_id);
  } catch (e) {
    if (e !== "cancel") ElMessage.error(e.msg || "操作失败");
  }
};

const cancelOrder = async (row) => {
  try {
    await ElMessageBox.confirm("确定撤销该医嘱？", "提示", { type: "warning" });
    await cancelInpatientOrder({ order_id: row.order_id });
    ElMessage.success("撤销成功");
    loadOrders(currentPatient.value.admission_id);
  } catch (e) {
    if (e !== "cancel") ElMessage.error(e.msg || "操作失败");
  }
};

onMounted(() => {
  loadInpatients();
});
</script>
