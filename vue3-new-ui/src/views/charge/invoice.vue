<template>
  <div class="app-container">
    <vab-page-header title="发票管理" />
    <el-card>
      <el-table :data="list" v-loading="loading">
        <el-table-column prop="id" label="ID" />
        <el-table-column prop="invoice_no" label="发票号码" />
        <el-table-column prop="charge_id" label="收费记录ID" />
        <el-table-column prop="amount" label="金额" />
        <el-table-column prop="invoice_time" label="开票时间" />
        <el-table-column label="操作" width="200">
          <template #default="{row}">
            <el-button size="small" type="primary" @click="print(row)">打印</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>
  </div>
</template>

<script setup>
import { ref, onMounted } from "vue";
import { ElMessage } from "element-plus";
import { getInvoiceList, printInvoice } from "@/api/charge";

const list = ref([]);
const loading = ref(false);

const fetchList = async () => {
  loading.value = true;
  const res = await getInvoiceList();
  list.value = res.data || [];
  loading.value = false;
};

const print = async (row) => {
  try {
    const res = await printInvoice({ invoice_id: row.id });
    ElMessage.success("打印请求已提交: " + (res.data?.pdf_url || ""));
  } catch (e) {
    ElMessage.error(e.msg || "打印失败");
  }
};

onMounted(fetchList);
</script>
