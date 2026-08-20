<template>
  <div class="app-container">
    <vab-page-header title="日结对账" description="收费员每日结算和对账管理（支持开单日 / 缴费日两种口径）" />
    <el-card>
      <el-form :inline="true" class="page-toolbar">
        <el-form-item label="日期">
          <el-date-picker v-model="date" type="date" value-format="YYYY-MM-DD" />
        </el-form-item>
        <el-form-item label="统计口径">
          <el-radio-group v-model="basis">
            <el-radio-button label="charge">开单日（权责发生）</el-radio-button>
            <el-radio-button label="paid">缴费日（收付实现）</el-radio-button>
          </el-radio-group>
        </el-form-item>
        <el-form-item>
          <el-button type="primary" @click="query">查询</el-button>
        </el-form-item>
      </el-form>

      <!-- 缴费日口径：按支付渠道拆分 -->
      <template v-if="basis === 'paid' && result.date">
        <el-alert type="info" :closable="false" title="以 Payment.paid_time 实际资金发生日统计；跨日缴费/退费不再错配到开单日" style="margin-bottom: 12px" />
        <el-descriptions :column="3" border>
          <el-descriptions-item label="日期">{{ result.date }}</el-descriptions-item>
          <el-descriptions-item label="总收入">{{ result.total_income }}</el-descriptions-item>
          <el-descriptions-item label="总退费">{{ result.total_refund }}</el-descriptions-item>
          <el-descriptions-item label="净收入">{{ result.net_income }}</el-descriptions-item>
          <el-descriptions-item label="缴费笔数">{{ result.count_paid }}</el-descriptions-item>
          <el-descriptions-item label="退费笔数">{{ result.count_refund }}</el-descriptions-item>
        </el-descriptions>
        <el-row :gutter="12" style="margin-top: 12px">
          <el-col :span="12">
            <el-table :data="incomeRows" border size="small">
              <el-table-column prop="channel" label="收费渠道" />
              <el-table-column prop="amount" label="收入" />
            </el-table>
          </el-col>
          <el-col :span="12">
            <el-table :data="refundRows" border size="small">
              <el-table-column prop="channel" label="收费渠道" />
              <el-table-column prop="amount" label="退费" />
            </el-table>
          </el-col>
        </el-row>
      </template>

      <!-- 开单日口径（原有） -->
      <el-descriptions v-else-if="result.date" :column="3" border>
        <el-descriptions-item label="日期">{{ result.date }}</el-descriptions-item>
        <el-descriptions-item label="总收入">{{ result.total_income }}</el-descriptions-item>
        <el-descriptions-item label="总退费">{{ result.total_refund }}</el-descriptions-item>
        <el-descriptions-item label="待缴费">{{ result.total_pending }}</el-descriptions-item>
        <el-descriptions-item label="缴费笔数">{{ result.count_paid }}</el-descriptions-item>
        <el-descriptions-item label="退费笔数">{{ result.count_refund }}</el-descriptions-item>
        <el-descriptions-item label="待缴笔数">{{ result.count_pending }}</el-descriptions-item>
        <el-descriptions-item label="总笔数">{{ result.record_count }}</el-descriptions-item>
      </el-descriptions>
    </el-card>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from "vue";
import { dailySettlement, dailySettlementByPayDate } from "@/api/charge";
import { ElMessage } from "element-plus";

const date = ref("");
const basis = ref("charge");
const result = ref({});

const channelText = { wechat: "微信支付", alipay: "支付宝", cash: "现金", card: "银行卡", unknown: "未知" };
const incomeRows = computed(() =>
  Object.entries(result.value.income_by_channel || {}).map(([channel, amount]) => ({ channel: channelText[channel] || channel, amount }))
);
const refundRows = computed(() =>
  Object.entries(result.value.refund_by_channel || {}).map(([channel, amount]) => ({ channel: channelText[channel] || channel, amount }))
);

const query = async () => {
  try {
    const api = basis.value === "paid" ? dailySettlementByPayDate : dailySettlement;
    const res = await api({ date: date.value });
    result.value = res.data || {};
  } catch (e) {
    ElMessage.error(e.msg || "查询失败");
  }
};

onMounted(() => {
  date.value = new Date().toISOString().split("T")[0];
  query();
});
</script>
