<template>
  <div class="app-container">
    <vab-page-header title="药品采购管理" description="创建采购订单，跟踪采购入库流程" />
    <el-card>
      <div class="page-toolbar">
        <el-button type="primary" @click="handleAdd">新建采购单</el-button>
        <el-select v-model="filterStatus" placeholder="筛选状态" clearable class="page-search-input" @change="fetchList">
          <el-option label="待审批" :value="0" />
          <el-option label="已审批" :value="1" />
          <el-option label="已入库" :value="2" />
          <el-option label="已取消" :value="3" />
        </el-select>
        <el-button @click="fetchList">刷新</el-button>
      </div>

      <el-table :data="list" v-loading="loading" empty-text="暂无记录">
        <el-table-column prop="order_no" label="采购单号" />
        <el-table-column prop="supplier" label="供应商" />
        <el-table-column prop="total_amount" label="总金额" />
        <el-table-column prop="status_text" label="状态">
          <template #default="{row}">
            <el-tag v-if="row.status===0" type="warning">{{ row.status_text }}</el-tag>
            <el-tag v-else-if="row.status===1" type="primary">{{ row.status_text }}</el-tag>
            <el-tag v-else-if="row.status===2" type="success">{{ row.status_text }}</el-tag>
            <el-tag v-else type="info">{{ row.status_text }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="明细">
          <template #default="{row}">
            <div v-for="(it, i) in row.items" :key="i">{{ it.item_name }} x{{ it.quantity }}</div>
          </template>
        </el-table-column>
        <el-table-column prop="create_by" label="创建人" width="100" />
        <el-table-column prop="create_time" label="创建时间" width="160" />
        <el-table-column label="操作" width="250">
          <template #default="{row}">
            <el-button v-if="row.status===0" size="small" type="primary" @click="approve(row)">审批</el-button>
            <el-button v-if="row.status===1" size="small" type="success" @click="storage(row)">入库</el-button>
            <el-button v-if="row.status!==2 && row.status!==3" size="small" type="danger" @click="cancel(row)">取消</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <el-dialog v-model="dialogVisible" title="新建采购单" width="600px">
      <el-form :model="form" label-width="80px" class="dialog-form">
        <el-form-item label="供应商">
          <el-input v-model="form.supplier" />
        </el-form-item>
        <el-form-item label="采购明细">
          <div v-for="(item, i) in form.items" :key="i" style="margin-bottom: 10px;">
            <el-select v-model="item.item_type" style="width: 100px; margin-right: 5px;">
              <el-option label="药品" value="drug" />
              <el-option label="耗材" value="consumable" />
            </el-select>
            <el-input v-model="item.item_name" placeholder="名称" style="width: 120px; margin-right: 5px;" />
            <el-input-number v-model="item.quantity" :min="1" style="width: 80px; margin-right: 5px;" />
            <el-input-number v-model="item.unit_price" :min="0" :precision="2" style="width: 100px; margin-right: 5px;" />
            <el-button type="danger" size="small" @click="removeItem(i)">删除</el-button>
          </div>
          <el-button type="primary" size="small" @click="addItem">添加明细</el-button>
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
import { ref, onMounted } from "vue";
import { ElMessage, ElMessageBox } from "element-plus";
import { createPurchase, getPurchaseList, approvePurchase, storagePurchase, cancelPurchase } from "@/api/purchase";

const list = ref([]);
const loading = ref(false);
const dialogVisible = ref(false);
const filterStatus = ref("");
const form = ref({ supplier: "", items: [] });

const fetchList = async () => {
  loading.value = true;
  const params = {};
  if (filterStatus.value !== "") params.status = filterStatus.value;
  const res = await getPurchaseList(params);
  list.value = res.data || [];
  loading.value = false;
};

const handleAdd = () => {
  form.value = { supplier: "", items: [{ item_type: "drug", item_name: "", quantity: 1, unit_price: 0 }] };
  dialogVisible.value = true;
};

const addItem = () => {
  form.value.items.push({ item_type: "drug", item_name: "", quantity: 1, unit_price: 0 });
};

const removeItem = (i) => {
  form.value.items.splice(i, 1);
};

const submit = async () => {
  try {
    await createPurchase(form.value);
    ElMessage.success("创建成功");
    dialogVisible.value = false;
    fetchList();
  } catch (e) {
    ElMessage.error(e.msg || "创建失败");
  }
};

const approve = async (row) => {
  try {
    await ElMessageBox.confirm("确认审批该采购单？", "提示", { type: "warning" });
    await approvePurchase({ purchase_id: row.purchase_id });
    ElMessage.success("审批成功");
    fetchList();
  } catch (e) {
    if (e !== "cancel") ElMessage.error(e.msg || "审批失败");
  }
};

const storage = async (row) => {
  try {
    await ElMessageBox.confirm("确认入库？入库后库存将自动增加", "提示", { type: "warning" });
    await storagePurchase({ purchase_id: row.purchase_id });
    ElMessage.success("入库成功");
    fetchList();
  } catch (e) {
    if (e !== "cancel") ElMessage.error(e.msg || "入库失败");
  }
};

const cancel = async (row) => {
  try {
    await ElMessageBox.confirm("确认取消该采购单？", "提示", { type: "warning" });
    await cancelPurchase({ purchase_id: row.purchase_id });
    ElMessage.success("取消成功");
    fetchList();
  } catch (e) {
    if (e !== "cancel") ElMessage.error(e.msg || "取消失败");
  }
};

onMounted(fetchList);
</script>
