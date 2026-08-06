<template>
  <div class="app-container">
    <vab-page-header title="转诊/会诊审批" description="按本科室范围处理医生提交的转诊和多学科会诊申请" />
    <el-tabs v-model="activeTab">
      <el-tab-pane label="转诊申请" name="referral">
        <el-table :data="referrals" v-loading="loading" border empty-text="暂无待审批转诊">
          <el-table-column prop="patient_name" label="患者" width="120" />
          <el-table-column prop="from_department" label="转出科室" width="140" />
          <el-table-column prop="to_department" label="转入科室" width="140" />
          <el-table-column prop="reason" label="申请原因" min-width="220" show-overflow-tooltip />
          <el-table-column prop="applicant_name" label="申请人" width="120" />
          <el-table-column prop="create_time" label="申请时间" width="170" />
          <el-table-column label="操作" width="180" fixed="right">
            <template #default="{ row }">
              <el-button size="small" type="success" @click="reviewReferral(row, 1)">通过</el-button>
              <el-button size="small" type="danger" @click="reviewReferral(row, 2)">退回</el-button>
            </template>
          </el-table-column>
        </el-table>
      </el-tab-pane>
      <el-tab-pane label="会诊申请" name="mdt">
        <el-table :data="mdtCases" v-loading="loading" border empty-text="暂无待审批会诊">
          <el-table-column prop="patient_name" label="患者" width="120" />
          <el-table-column prop="diagnosis" label="初步诊断" min-width="220" show-overflow-tooltip />
          <el-table-column label="参与科室" min-width="200">
            <template #default="{ row }">
              <el-tag v-for="name in row.department_names" :key="name" size="small" style="margin-right: 4px">{{ name }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="applicant_name" label="申请人" width="120" />
          <el-table-column prop="create_time" label="申请时间" width="170" />
          <el-table-column label="操作" width="180" fixed="right">
            <template #default="{ row }">
              <el-button size="small" type="success" @click="reviewMdt(row, 1)">通过</el-button>
              <el-button size="small" type="danger" @click="reviewMdt(row, 2)">退回</el-button>
            </template>
          </el-table-column>
        </el-table>
      </el-tab-pane>
    </el-tabs>
  </div>
</template>

<script setup>
import { onMounted, ref } from "vue";
import { ElMessage, ElMessageBox } from "element-plus";
import { approveMdt, getMdtApprovalList } from "@/api/mdt";
import { approveReferral, getReferralApprovalList } from "@/api/referral";

const activeTab = ref("referral");
const loading = ref(false);
const referrals = ref([]);
const mdtCases = ref([]);

const reviewNote = async (action) => {
  try {
    const result = await ElMessageBox.prompt("可填写审批意见", action === 1 ? "通过申请" : "退回申请", {
      inputPlaceholder: "审批意见（可选）",
      inputValidator: (value) => value.length <= 200 || "审批意见不能超过200字",
      confirmButtonText: "确认",
      cancelButtonText: "取消",
    });
    return result.value || "";
  } catch {
    return null;
  }
};

const loadData = async () => {
  loading.value = true;
  try {
    const [referralRes, mdtRes] = await Promise.all([getReferralApprovalList(), getMdtApprovalList()]);
    referrals.value = referralRes.data || [];
    mdtCases.value = mdtRes.data || [];
  } catch (error) {
    ElMessage.error(error.msg || "获取审批列表失败");
  } finally {
    loading.value = false;
  }
};

const reviewReferral = async (row, status) => {
  const note = await reviewNote(status);
  if (note === null) return;
  try {
    await approveReferral({ referral_id: row.referral_id, status, note });
    ElMessage.success("审批完成");
    await loadData();
  } catch (error) {
    ElMessage.error(error.msg || "审批失败");
  }
};

const reviewMdt = async (row, status) => {
  const note = await reviewNote(status);
  if (note === null) return;
  try {
    await approveMdt({ mdt_id: row.mdt_id, status, note });
    ElMessage.success("审批完成");
    await loadData();
  } catch (error) {
    ElMessage.error(error.msg || "审批失败");
  }
};

onMounted(loadData);
</script>
