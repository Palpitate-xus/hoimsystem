<template>
  <div class="app-container">
    <vab-page-header title="费用管理" description="管理患者费用记录，支持缴费和退费处理" />
    <el-card>

      <div class="page-toolbar">
        <el-input
          v-model="searchQuery"
          placeholder="搜索..."
          clearable
          class="page-search-input"
        ></el-input>
        <el-button type="primary" @click="fetchList">搜索</el-button>
      </div>
      <el-table :data="paginatedList" v-loading="loading">
        <el-table-column prop="id" label="ID"  sortable />
        <el-table-column prop="charge_time" label="创建时间"  sortable />
        <el-table-column prop="time" label="缴费时间"  sortable />
        <el-table-column prop="pre_id" label="处方ID" />
        <el-table-column prop="amount" label="金额"  sortable />
        <el-table-column prop="status" label="状态">
          <template #default="{row}">
            <el-tag v-if="row.status===0" type="warning">未缴费</el-tag>
            <el-tag v-else-if="row.status===1" type="success">已缴费</el-tag>
            <el-tag v-else type="danger">已退费</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="200">
          <template #default="{row}">
            <el-button v-if="row.status===0" size="small" type="primary" @click="openPayDialog(row)">收费</el-button>
            <el-button v-if="row.status===1" size="small" type="danger" @click="refund(row)">退费</el-button>
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

    <el-dialog v-model="refundVisible" title="退费" width="500px">
      <el-form :model="refundForm" label-width="100px" class="dialog-form">
        <el-form-item label="退费原因">
          <el-input v-model="refundForm.reason" type="textarea" :rows="3" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="refundVisible=false">取消</el-button>
        <el-button type="primary" @click="submitRefund">确定</el-button>
      </template>
    </el-dialog>

    <!-- 支付方式选择 -->
    <el-dialog v-model="payChannelVisible" title="选择支付方式" width="400px">
      <el-form label-width="80px">
        <el-form-item label="支付金额">
          <span style="font-size: 18px; color: #f56c6c; font-weight: bold;">¥ {{ payForm.amount }}</span>
        </el-form-item>
        <el-form-item label="支付方式">
          <el-radio-group v-model="payForm.channel">
            <el-radio label="wechat">微信支付</el-radio>
            <el-radio label="alipay">支付宝</el-radio>
            <el-radio label="cash">现金支付</el-radio>
          </el-radio-group>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="payChannelVisible=false">取消</el-button>
        <el-button type="primary" @click="confirmPay">确认支付</el-button>
      </template>
    </el-dialog>

    <!-- 二维码支付 -->
    <el-dialog v-model="qrVisible" title="扫码支付" width="360px" :close-on-click-modal="false" @close="stopQuery">
      <div style="text-align: center;">
        <p style="margin-bottom: 10px; color: #606266;">
          {{ payForm.channel === 'wechat' ? '请使用微信扫一扫' : '请使用支付宝扫一扫' }}
        </p>
        <div style="width: 200px; height: 200px; margin: 0 auto; background: #f5f5f5; display: flex; align-items: center; justify-content: center; border: 1px solid #dcdfe6;">
          <qrcode-vue :value="qrData" :size="180" level="M" />
        </div>
        <p style="margin-top: 10px; font-size: 14px; color: #909399;">支付单号: {{ paymentNo }}</p>
        <p style="margin-top: 5px; font-size: 20px; color: #f56c6c; font-weight: bold;">¥ {{ payForm.amount }}</p>
        <el-button type="success" style="margin-top: 15px;" @click="mockPaySuccess">模拟支付成功</el-button>
      </div>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, onMounted, computed } from "vue";
import { ElMessage } from "element-plus";
import { getChargeList, commitCharge, refundCharge, createPayment, queryPayment, mockPaymentNotify } from "@/api/charge";
import QrcodeVue from "qrcode.vue";

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
const refundVisible = ref(false);
const refundForm = ref({});
const payChannelVisible = ref(false);
const qrVisible = ref(false);
const payForm = ref({ charge_id: "", amount: 0, channel: "wechat" });
const paymentNo = ref("");
const qrData = ref("");
let queryTimer = null;

const fetchList = async () => {
  loading.value = true;
  const res = await getChargeList(searchQuery.value);
  list.value = res.data || [];
  total.value = list.value.length;
  loading.value = false;
};

const openPayDialog = (row) => {
  payForm.value = { charge_id: row.id, amount: row.amount, channel: "wechat" };
  payChannelVisible.value = true;
};

const confirmPay = async () => {
  if (payForm.value.channel === "cash") {
    try {
      await commitCharge({ id: payForm.value.charge_id });
      ElMessage.success("现金收费成功");
      payChannelVisible.value = false;
      fetchList();
    } catch (e) {
      ElMessage.error(e.msg || "收费失败");
    }
    return;
  }
  try {
    const res = await createPayment(payForm.value);
    if (res.code === 200) {
      paymentNo.value = res.data.payment_no;
      qrData.value = res.data.qr_code_data;
      payChannelVisible.value = false;
      qrVisible.value = true;
      startQuery();
    } else {
      ElMessage.error(res.msg || "创建支付订单失败");
    }
  } catch (e) {
    ElMessage.error(e.msg || "创建支付订单失败");
  }
};

const startQuery = () => {
  stopQuery();
  queryTimer = setInterval(async () => {
    try {
      const res = await queryPayment(paymentNo.value);
      if (res.code === 200 && res.data.status === 1) {
        ElMessage.success("支付成功");
        stopQuery();
        qrVisible.value = false;
        fetchList();
      }
    } catch (e) {
      // ignore
    }
  }, 3000);
};

const stopQuery = () => {
  if (queryTimer) {
    clearInterval(queryTimer);
    queryTimer = null;
  }
};

const mockPaySuccess = async () => {
  try {
    await mockPaymentNotify({ payment_no: paymentNo.value });
    ElMessage.success("支付成功");
    stopQuery();
    qrVisible.value = false;
    fetchList();
  } catch (e) {
    ElMessage.error(e.msg || "支付失败");
  }
};

const refund = (row) => {
  refundForm.value = { charge_id: row.id, reason: "" };
  refundVisible.value = true;
};

const submitRefund = async () => {
  try {
    await refundCharge(refundForm.value);
    ElMessage.success("退费成功");
    refundVisible.value = false;
    fetchList();
  } catch (e) {
    ElMessage.error(e.msg || "退费失败");
  }
};

onMounted(fetchList);
</script>
