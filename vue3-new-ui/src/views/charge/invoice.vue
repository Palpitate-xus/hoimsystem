<template>
  <div class="app-container">
    <vab-page-header title="发票管理" description="生成、查询和打印医疗收费发票" />
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
      <el-table :data="paginatedList" v-loading="loading" border empty-text="暂无发票记录">
        <el-table-column prop="invoice_no" label="发票号码" sortable min-width="180"
          ><template #default="{row}"><code style="font-size:13px">{{ row.invoice_no }}</code></template></el-table-column>
        <el-table-column prop="patient_name" label="患者姓名" width="120"
          ><template #default="{row}"><el-tag v-if="row.patient_name" type="info" effect="plain">{{ row.patient_name }}</el-tag><span v-else style="color:#999">-</span></template></el-table-column>
        <el-table-column prop="amount" label="金额" sortable width="120"
          ><template #default="{row}"><span style="color:#f56c6c;font-weight:bold">¥{{ row.amount }}</span></template></el-table-column>
        <el-table-column prop="invoice_time" label="开票时间" sortable width="180" />
        <el-table-column label="操作" width="100" fixed="right">
          <template #default="{row}">
            <el-button size="small" type="primary" @click="print(row)">打印</el-button>
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
  </div>
</template>

<script setup>
import { ref, onMounted, computed } from "vue";
import { ElMessage } from "element-plus";
import { getInvoiceList, printInvoice } from "@/api/charge";

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

const fetchList = async () => {
  loading.value = true;
  const res = await getInvoiceList(searchQuery.value);
  list.value = res.data || [];
  total.value = list.value.length;
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
