<template>
  <div class="app-container">
    <vab-page-header title="费用管理" />
    <el-card>
      
      <el-input
        v-model="searchQuery"
        placeholder="搜索..."
        clearable
        style="width: 200px; margin-left: 10px;"
      ></el-input>
      <el-table :data="paginatedList" v-loading="loading">
        <el-table-column prop="id" label="ID" />
        <el-table-column prop="charge_time" label="创建时间" />
        <el-table-column prop="time" label="缴费时间" />
        <el-table-column prop="pre_id" label="处方ID" />
        <el-table-column prop="amount" label="金额" />
        <el-table-column prop="status" label="状态">
          <template #default="{row}">
            <el-tag v-if="row.status===0" type="warning">未缴费</el-tag>
            <el-tag v-else-if="row.status===1" type="success">已缴费</el-tag>
            <el-tag v-else type="danger">已退费</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="200">
          <template #default="{row}">
            <el-button v-if="row.status===0" size="small" type="primary" @click="pay(row)">收费</el-button>
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
        style="margin-top: 15px; justify-content: flex-end;"
      />

    </el-card>

    <el-dialog v-model="refundVisible" title="退费" width="500px">
      <el-form :model="refundForm" label-width="100px">
        <el-form-item label="退费原因">
          <el-input v-model="refundForm.reason" type="textarea" :rows="3" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="refundVisible=false">取消</el-button>
        <el-button type="primary" @click="submitRefund">确定</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, onMounted, computed } from "vue";
import { ElMessage } from "element-plus";
import { getChargeList, commitCharge, refundCharge } from "@/api/charge";

const list = ref([]);
const searchQuery = ref("");
const currentPage = ref(1);
const pageSize = ref(10);
const total = ref(0);
const filteredList = computed(() => {
  if (!searchQuery.value) return list.value;
  const kw = searchQuery.value.toLowerCase();
  return list.value.filter((item) =>
    Object.values(item).some((val) =>
      String(val ?? "").toLowerCase().includes(kw)
    )
  );
});

const paginatedList = computed(() => {
  const start = (currentPage.value - 1) * pageSize.value;
  return filteredList.value.slice(start, start + pageSize.value);
});

const loading = ref(false);
const refundVisible = ref(false);
const refundForm = ref({});

const fetchList = async () => {
  loading.value = true;
  const res = await getChargeList(searchQuery.value);
  list.value = res.data || [];
  total.value = filteredList.value.length;
  loading.value = false;
};

const pay = async (row) => {
  try {
    await commitCharge({ id: row.id });
    ElMessage.success("收费成功");
    fetchList();
  } catch (e) {
    ElMessage.error(e.msg || "收费失败");
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
