<template>
  <div class="app-container">
    <vab-page-header title="预交金管理" />
    <el-card>
      <el-form :inline="true" label-width="100px">
        <el-form-item label="患者身份证号">
          <el-input v-model="identity" placeholder="请输入身份证号" style="width: 280px;" />
        </el-form-item>
        <el-form-item>
          <el-button type="primary" @click="handleQuery">查询余额</el-button>
        </el-form-item>
      </el-form>

      <el-divider />

      <div v-if="balance !== null" style="text-align: center; margin: 32px 0;">
        <div style="font-size: 16px; color: #666; margin-bottom: 8px;">当前余额</div>
        <div style="font-size: 48px; font-weight: bold; color: #409EFF;">
          {{ balance.toFixed(2) }} 元
        </div>
      </div>

      <el-divider />

      <el-row :gutter="32">
        <el-col :span="12">
          <el-card shadow="never">
            <template #header>
              <span>预交金充值</span>
            </template>
            <el-form label-width="80px">
              <el-form-item label="充值金额">
                <el-input-number v-model="rechargeAmount" :min="0.01" :precision="2" style="width: 200px;" />
              </el-form-item>
              <el-form-item>
                <el-button type="primary" @click="handleRecharge">充值</el-button>
              </el-form-item>
            </el-form>
          </el-card>
        </el-col>
        <el-col :span="12">
          <el-card shadow="never">
            <template #header>
              <span>预交金扣费</span>
            </template>
            <el-form label-width="80px">
              <el-form-item label="扣费金额">
                <el-input-number v-model="deductAmount" :min="0.01" :precision="2" style="width: 200px;" />
              </el-form-item>
              <el-form-item>
                <el-button type="danger" @click="handleDeduct">扣费</el-button>
              </el-form-item>
            </el-form>
          </el-card>
        </el-col>
      </el-row>
    </el-card>
  </div>
</template>

<script setup>
import { ref } from "vue";
import { ElMessage } from "element-plus";
import { getPrepaidBalance, prepaidRecharge, prepaidDeduct } from "@/api/prepaid";

const identity = ref("");
const balance = ref(null);
const rechargeAmount = ref(100);
const deductAmount = ref(0);

const handleQuery = async () => {
  if (!identity.value.trim()) {
    ElMessage.warning("请输入身份证号");
    return;
  }
  try {
    const res = await getPrepaidBalance({ identity: identity.value });
    balance.value = res.data !== undefined ? res.data : res;
  } catch (error) {
    ElMessage.error("查询余额失败");
  }
};

const handleRecharge = async () => {
  if (!identity.value.trim()) {
    ElMessage.warning("请先输入身份证号并查询余额");
    return;
  }
  try {
    await prepaidRecharge({ identity: identity.value, amount: rechargeAmount.value });
    ElMessage.success("充值成功");
    handleQuery();
  } catch (error) {
    ElMessage.error("充值失败");
  }
};

const handleDeduct = async () => {
  if (!identity.value.trim()) {
    ElMessage.warning("请先输入身份证号并查询余额");
    return;
  }
  try {
    await prepaidDeduct({ identity: identity.value, amount: deductAmount.value });
    ElMessage.success("扣费成功");
    handleQuery();
  } catch (error) {
    ElMessage.error("扣费失败");
  }
};
</script>
