<template>
  <div class="app-container">
    <vab-page-header title="库存预警" />
    <el-tabs v-model="activeTab">
      <el-tab-pane label="库存不足预警" name="lowStock">
        <el-form :inline="true">
          <el-form-item label="阈值">
            <el-input-number v-model="threshold" :min="1" :max="1000" />
          </el-form-item>
          <el-form-item>
            <el-input v-model="keyword1" placeholder="搜索药品..." clearable style="width:200px" />
          </el-form-item>
          <el-form-item>
            <el-button type="primary" @click="queryLowStock">查询</el-button>
          </el-form-item>
        </el-form>
        <el-alert v-if="lowStockList.length > 0" :title="`发现 ${lowStockList.length} 种药品库存不足`" type="warning" :closable="false" show-icon />
        <el-alert v-else title="所有药品库存充足" type="success" :closable="false" show-icon />
        <el-table :data="lowStockList" style="margin-top:15px">
          <el-table-column prop="id" label="ID" width="60" />
          <el-table-column prop="name" label="药品名称" />
          <el-table-column prop="stock" label="当前库存" sortable>
            <template #default="scope">
              <el-tag v-if="scope.row.stock <= 5" type="danger">{{ scope.row.stock }}</el-tag>
              <el-tag v-else-if="scope.row.stock <= 10" type="warning">{{ scope.row.stock }}</el-tag>
              <span v-else>{{ scope.row.stock }}</span>
            </template>
          </el-table-column>
          <el-table-column prop="threshold" label="预警阈值" />
          <el-table-column prop="price" label="单价" />
          <el-table-column prop="expireddate" label="过期日期" />
          <el-table-column prop="supplier" label="供应商" />
        </el-table>
      </el-tab-pane>

      <el-tab-pane label="有效期预警" name="nearExpiry">
        <el-form :inline="true">
          <el-form-item label="提前天数">
            <el-input-number v-model="days" :min="7" :max="365" />
          </el-form-item>
          <el-form-item>
            <el-input v-model="keyword2" placeholder="搜索药品..." clearable style="width:200px" />
          </el-form-item>
          <el-form-item>
            <el-button type="primary" @click="queryNearExpiry">查询</el-button>
          </el-form-item>
        </el-form>
        <el-alert v-if="nearExpiryList.length > 0" :title="`发现 ${nearExpiryList.length} 种药品即将过期`" type="warning" :closable="false" show-icon />
        <el-alert v-else title="暂无即将过期的药品" type="success" :closable="false" show-icon />
        <el-table :data="nearExpiryList" style="margin-top:15px">
          <el-table-column prop="id" label="ID" width="60" />
          <el-table-column prop="name" label="药品名称" />
          <el-table-column prop="stock" label="库存" />
          <el-table-column prop="expireddate" label="过期日期" sortable>
            <template #default="scope">
              <el-tag v-if="scope.row.days_left <= 7" type="danger">{{ scope.row.expireddate }} (剩{{ scope.row.days_left }}天)</el-tag>
              <el-tag v-else-if="scope.row.days_left <= 30" type="warning">{{ scope.row.expireddate }} (剩{{ scope.row.days_left }}天)</el-tag>
              <span v-else>{{ scope.row.expireddate }} (剩{{ scope.row.days_left }}天)</span>
            </template>
          </el-table-column>
          <el-table-column prop="supplier" label="供应商" />
        </el-table>
      </el-tab-pane>
    </el-tabs>
  </div>
</template>

<script setup>
import { ref, onMounted } from "vue";
import { getLowStockDrugs, getNearExpiryDrugs } from "@/api/pharmacy";
import { ElMessage } from "element-plus";

const activeTab = ref("lowStock");
const threshold = ref(10);
const days = ref(30);
const keyword1 = ref("");
const keyword2 = ref("");
const lowStockList = ref([]);
const nearExpiryList = ref([]);

const queryLowStock = async () => {
  try {
    const res = await getLowStockDrugs(threshold.value, keyword1.value);
    lowStockList.value = res.data || [];
  } catch (e) {
    ElMessage.error(e.msg || "查询失败");
  }
};

const queryNearExpiry = async () => {
  try {
    const res = await getNearExpiryDrugs(days.value, keyword2.value);
    nearExpiryList.value = res.data || [];
  } catch (e) {
    ElMessage.error(e.msg || "查询失败");
  }
};

onMounted(() => {
  queryLowStock();
  queryNearExpiry();
});
</script>
