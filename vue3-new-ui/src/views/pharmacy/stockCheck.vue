<template>
  <div class="app-container">
    <vab-page-header title="库存盘点" description="定期盘点药品库存，生成盘盈盘亏报告" />
    <el-card>
      <el-alert title="请逐一输入各药品的实盘数量，系统将自动对比系统库存并生成盈亏" type="info" :closable="false" show-icon />
      <el-table :data="drugList" v-loading="loading" empty-text="暂无记录">
        <el-table-column prop="name" label="药品名称" />
        <el-table-column prop="stock" label="系统库存" />
        <el-table-column label="实盘数量">
          <template #default="{row}">
            <el-input-number v-model="row.actual_stock" :min="0" style="width:120px" />
          </template>
        </el-table-column>
      </el-table>
      <div style="margin-top: 15px; text-align: center;">
        <el-button type="primary" @click="submitCheck">提交盘点</el-button>
      </div>
    </el-card>

    <el-card v-if="result.length > 0" style="margin-top: 15px;">
      <template #header>盘点结果</template>
      <el-table :data="result" empty-text="暂无记录">
        <el-table-column prop="name" label="药品" />
        <el-table-column prop="system_stock" label="系统库存" />
        <el-table-column prop="actual_stock" label="实盘数量" />
        <el-table-column prop="diff" label="盈亏">
          <template #default="{row}">
            <el-tag v-if="row.diff > 0" type="success">+{{ row.diff }}</el-tag>
            <el-tag v-else-if="row.diff < 0" type="danger">{{ row.diff }}</el-tag>
            <span v-else>0</span>
          </template>
        </el-table-column>
      </el-table>
    </el-card>
  </div>
</template>

<script setup>
import { ref, onMounted } from "vue";
import { getPharmaceuticalList, stockCheck } from "@/api/pharmacy";
import { ElMessage } from "element-plus";

const drugList = ref([]);
const result = ref([]);
const loading = ref(false);

const loadDrugs = async () => {
  loading.value = true;
  try {
    const res = await getPharmaceuticalList();
    drugList.value = (res.data || []).map(d => ({ ...d, actual_stock: d.stock }));
  } finally {
    loading.value = false;
  }
};

const submitCheck = async () => {
  try {
    const items = drugList.value.map(d => ({
      pharmaceutical_id: d.id,
      actual_stock: d.actual_stock,
    }));
    const res = await stockCheck({ items });
    result.value = res.data || [];
    ElMessage.success("盘点完成");
    loadDrugs();
  } catch (e) {
    ElMessage.error(e.msg || "盘点失败");
  }
};

onMounted(loadDrugs);
</script>
