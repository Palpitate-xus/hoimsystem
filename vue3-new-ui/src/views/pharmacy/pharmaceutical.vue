<template>
  <div class="app-container">
    <vab-page-header title="药品管理" description="维护药品信息、库存查询和出入库管理" />
    <el-card>
      <div class="page-toolbar">
        <el-button type="primary" @click="handleAdd">新增药品</el-button>
        <el-input
          v-model="searchQuery"
          placeholder="搜索药品"
          clearable
          class="page-search-input"
        ></el-input>
        <el-button type="primary" @click="fetchList">搜索</el-button>
      </div>
      <el-table :data="paginatedList" v-loading="loading" empty-text="暂无记录">
        <el-table-column prop="name" label="药品名称"  sortable />
        <el-table-column prop="stock" label="库存"  sortable />
        <el-table-column prop="price" label="单价"  sortable />
        <el-table-column prop="expireddate" label="过期日期" />
        <el-table-column prop="supplier" label="供应商" />
        <el-table-column prop="barcode" label="药品条码" min-width="150">
          <template #default="{ row }">{{ row.barcode || "未配置" }}</template>
        </el-table-column>
        <el-table-column prop="antibiotic_level" label="抗菌级别" width="100">
          <template #default="{row}">
            <el-tag v-if="row.antibiotic_level===0" type="info">非抗菌</el-tag>
            <el-tag v-else-if="row.antibiotic_level===1" type="success">非限制</el-tag>
            <el-tag v-else-if="row.antibiotic_level===2" type="warning">限制级</el-tag>
            <el-tag v-else type="danger">特殊级</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="remark" label="备注" />
        <el-table-column v-if="canUseSupplyAI" label="AI 原量预测" width="160"><template #default="{ row }"><ai-action :key="supplyAuth" v-if="Number.isSafeInteger(row.id)&&row.id>0" label="核对原量与预测" title="受审物资原量预测" :feature-keys="['supply_forecast']" initial-feature="supply_forecast" :initial-input="{ item_kind: 'pharmaceutical', item_id: row.id }" /></template></el-table-column>
        <el-table-column v-if="canUseSupplyAI" label="AI 库存候选比较" width="175"><template #default="{ row }"><ai-action :key="supplyAuth+'-inventory'" v-if="Number.isSafeInteger(row.id)&&row.id>0&&row.id<=2147483647" label="核对库存候选" title="受审完整库存候选比较" :feature-keys="['inventory_optimization']" initial-feature="inventory_optimization" :initial-input="{ item_kind: 'pharmaceutical', item_id: row.id }" /></template></el-table-column>
        <el-table-column v-if="canUseDrugLabelAI" label="AI 说明书复核" width="280"><template #default="{ row }"><template v-if="Number.isSafeInteger(row.id)&&row.id>0&&row.id<=2147483647"><ai-action :key="supplyAuth+'-leaflet-'+row.id" label="核对说明书字段" title="本药品说明书逐字字段复核" :feature-keys="['drug_label_extraction']" initial-feature="drug_label_extraction" :pharmaceutical-id="row.id" /><el-button size="small" @click="openDrugLabelSources(row.id)">说明书原文与签署</el-button></template></template></el-table-column>
        <el-table-column label="操作" width="250">
          <template #default="{row}">
            <el-button size="small" @click="handleEdit(row)">编辑</el-button>
            <el-button size="small" type="primary" link @click="bindBarcode(row)">绑定条码</el-button>
            <el-button size="small" type="danger" @click="handleDelete(row)">删除</el-button>
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

    <el-drawer v-model="drugLabelSourcesOpen" title="本药品说明书原文与本人签署" size="min(1000px,96vw)" append-to-body destroy-on-close><drug-label-sources v-if="drugLabelSourcesOpen&&canUseDrugLabelAI" :key="supplyAuth+'-'+drugLabelSku" :pharmaceutical-id="drugLabelSku" :active="drugLabelSourcesOpen&&supplyViewActive" /></el-drawer>

    <el-dialog v-model="dialogVisible" :title="isEdit?'编辑药品':'新增药品'" width="600px">
      <el-form :model="form" label-width="100px" class="dialog-form">
        <el-form-item label="药品名称">
          <el-input v-model="form.name" />
        </el-form-item>
        <el-form-item label="库存">
          <el-input-number v-model="form.stock" :min="0" />
        </el-form-item>
        <el-form-item label="单价">
          <el-input v-model="form.price" />
        </el-form-item>
        <el-form-item label="过期日期">
          <el-date-picker v-model="form.expireddate" type="date" value-format="YYYY-MM-DD" />
        </el-form-item>
        <el-form-item label="供应商">
          <el-input v-model="form.supplier" />
        </el-form-item>
        <el-form-item label="抗菌级别">
          <el-radio-group v-model="form.antibiotic_level">
            <el-radio :label="0">非抗菌药</el-radio>
            <el-radio :label="1">非限制级</el-radio>
            <el-radio :label="2">限制级</el-radio>
            <el-radio :label="3">特殊使用级</el-radio>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="备注">
          <el-input v-model="form.remark" />
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
import { ref, onMounted, onActivated, onDeactivated, computed, watch, defineAsyncComponent } from "vue";
import { useStore } from "vuex";
import AiAction from "@/components/AIAction/index.vue";
import { ElMessage, ElMessageBox } from "element-plus";
import { getPharmaceuticalList, createPharmaceutical, updatePharmaceutical, deletePharmaceutical, setMedicationBarcode } from "@/api/pharmacy";

const DrugLabelSources=defineAsyncComponent(()=>import('@/components/ai/DrugLabelSources.vue'));
const supplyStore=useStore(),supplyViewActive=ref(true);
const drugLabelSourcesOpen=ref(false),drugLabelSku=ref(null);
const canUseDrugLabelAI=computed(()=>supplyViewActive.value&&typeof supplyStore.state.user.accessToken==='string'&&!!supplyStore.state.user.accessToken&&Array.isArray(supplyStore.getters['user/permissions'])&&supplyStore.getters['user/permissions'].some(role=>['super_admin','pharmacist'].includes(role)));
function openDrugLabelSources(id){if(!canUseDrugLabelAI.value||!Number.isSafeInteger(id)||id<1||id>2147483647)return;drugLabelSku.value=id;drugLabelSourcesOpen.value=true;}

const canUseSupplyAI=computed(()=>supplyViewActive.value&&!!supplyStore.state.user.accessToken&&Array.isArray(supplyStore.getters['user/permissions'])&&supplyStore.getters['user/permissions'].some(role=>['super_admin','admin','director','pharmacist'].includes(role)));
const supplyAuth=computed(()=>JSON.stringify([supplyStore.state.user.username,supplyStore.state.user.accessToken,supplyStore.getters['user/permissions']]));
watch([supplyAuth,supplyViewActive],()=>{drugLabelSourcesOpen.value=false;drugLabelSku.value=null;},{flush:'sync'});
watch(drugLabelSourcesOpen,value=>{if(!value)drugLabelSku.value=null;},{flush:'sync'});
onDeactivated(()=>{supplyViewActive.value=false;});onActivated(()=>{supplyViewActive.value=true;});
const list = ref([]);
const searchQuery = ref("");
const currentPage = ref(1);
const pageSize = ref(10);
const total = ref(0);
const paginatedList = computed(() => {
  const start = (currentPage.value - 1) * pageSize.value;
  return list.value.slice(start, start + pageSize.value);
});

const loading = ref(false);
const dialogVisible = ref(false);
const isEdit = ref(false);
const form = ref({});

const fetchList = async () => {
  loading.value = true;
  const res = await getPharmaceuticalList(searchQuery.value);
  list.value = res.data || [];
  total.value = list.value.length;
  loading.value = false;
};

const handleAdd = () => {
  isEdit.value = false;
  form.value = { stock: 0, price: "0", antibiotic_level: 0 };
  dialogVisible.value = true;
};

const handleEdit = (row) => {
  isEdit.value = true;
  form.value = { ...row, pharmaceutical_id: row.id };
  dialogVisible.value = true;
};

const submit = async () => {
  try {
    if (isEdit.value) {
      await updatePharmaceutical(form.value);
    } else {
      await createPharmaceutical(form.value);
    }
    ElMessage.success("操作成功");
    dialogVisible.value = false;
    fetchList();
  } catch (e) {
    ElMessage.error(e.msg || "操作失败");
  }
};

const handleDelete = (row) => {
  ElMessageBox.confirm("确认删除该药品？", "提示", { type: "warning" }).then(async () => {
    await deletePharmaceutical({ pharmaceutical_id: row.id });
    ElMessage.success("删除成功");
    fetchList();
  }).catch(() => {});
};

const bindBarcode = async (row) => {
  const { value } = await ElMessageBox.prompt(`请输入或扫描 ${row.name} 的药品条码`, "绑定药品条码", {
    inputValue: row.barcode || "",
    inputValidator: (barcode) => Boolean(barcode?.trim()) || "条码不能为空",
  });
  await setMedicationBarcode({ pharmaceutical_id: row.id, barcode: value.trim() });
  ElMessage.success("药品条码已绑定");
  await fetchList();
};

onMounted(fetchList);
</script>
