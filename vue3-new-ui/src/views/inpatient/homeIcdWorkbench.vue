<template>
  <div class="app-container">
    <vab-page-header title="病案 ICD 编码工作台" description="将首页文本诊断/手术映射为 ICD 码（主诊断唯一），覆盖待编码病案列表与编码统计" />
    <el-tabs v-model="tab">
      <!-- 待编码 -->
      <el-tab-pane :label="`待编码（${uncoded.length}）`" name="todo">
        <el-table :data="uncoded" v-loading="loading" border empty-text="暂无待编码病案">
          <el-table-column prop="admission_no" label="住院号" width="130" />
          <el-table-column prop="patient_name" label="患者" width="90" />
          <el-table-column prop="admission_diagnosis" label="入院诊断" min-width="120" show-overflow-tooltip />
          <el-table-column prop="discharge_diagnosis" label="出院诊断" min-width="120" show-overflow-tooltip />
          <el-table-column prop="other_diagnosis" label="其他诊断" min-width="110" show-overflow-tooltip />
          <el-table-column prop="operation_summary" label="手术情况" min-width="110" show-overflow-tooltip />
          <el-table-column prop="status_text" label="首页状态" width="90" />
          <el-table-column label="操作" width="90">
            <template #default="{ row }">
              <el-button size="small" type="primary" @click="openBind(row)">编码</el-button>
            </template>
          </el-table-column>
        </el-table>
      </el-tab-pane>

      <!-- 编码统计 -->
      <el-tab-pane label="编码统计" name="stats">
        <el-descriptions v-if="stats" :column="3" border style="margin-bottom: 12px">
          <el-descriptions-item label="应编码病案">{{ stats.total_homes }}</el-descriptions-item>
          <el-descriptions-item label="已编码">{{ stats.coded_homes }}</el-descriptions-item>
          <el-descriptions-item label="覆盖率">{{ stats.coverage_rate ?? "-" }}%</el-descriptions-item>
        </el-descriptions>
        <el-table v-if="stats" :data="stats.top_primary_diagnosis" border empty-text="暂无主诊断统计">
          <el-table-column type="index" label="#" width="50" />
          <el-table-column prop="icd_code" label="ICD 编码" width="120" />
          <el-table-column prop="icd_name" label="诊断名称" min-width="200" />
          <el-table-column prop="count" label="病案数" width="90" />
        </el-table>
      </el-tab-pane>

      <!-- 全部绑定 -->
      <el-tab-pane label="编码记录" name="all">
        <el-table :data="bindings" v-loading="loading" border empty-text="暂无编码记录">
          <el-table-column prop="kind_text" label="类型" width="90" />
          <el-table-column prop="icd_code" label="ICD 编码" width="120" />
          <el-table-column prop="icd_name" label="名称" min-width="180" />
          <el-table-column label="主要" width="70">
            <template #default="{ row }">
              <el-tag v-if="row.is_primary" size="small" type="danger">主</el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="coder_name" label="编码员" width="90" />
          <el-table-column prop="code_time" label="编码时间" width="160" />
          <el-table-column label="操作" width="130">
            <template #default="{ row }">
              <el-button v-if="!row.is_primary" size="small" @click="markPrimary(row)">设为主</el-button>
              <el-button size="small" type="danger" @click="removeBind(row)">删除</el-button>
            </template>
          </el-table-column>
        </el-table>
      </el-tab-pane>
    </el-tabs>

    <!-- 绑定对话框 -->
    <el-dialog v-model="bindDialogVisible" :title="`ICD 编码 — ${currentHome ? currentHome.patient_name : ''}`" width="560px">
      <el-descriptions v-if="currentHome" :column="1" border size="small" style="margin-bottom: 12px">
        <el-descriptions-item label="出院诊断">{{ currentHome.discharge_diagnosis || currentHome.admission_diagnosis }}</el-descriptions-item>
        <el-descriptions-item v-if="currentHome.other_diagnosis" label="其他诊断">{{ currentHome.other_diagnosis }}</el-descriptions-item>
      </el-descriptions>
      <el-form label-width="90px">
        <el-form-item label="编码类型">
          <el-radio-group v-model="bindForm.kind">
            <el-radio label="diagnosis">诊断编码</el-radio>
            <el-radio label="operation">手术编码</el-radio>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="ICD 编码">
          <el-select v-model="bindForm.icd_code" filterable remote :remote-method="searchIcd" :loading="icdSearching" placeholder="输入编码/名称搜索字典" style="width: 100%">
            <el-option v-for="d in icdOptions" :key="d.code" :label="`${d.code} ${d.name}`" :value="d.code" />
          </el-select>
        </el-form-item>
        <el-form-item label="主要标记">
          <el-switch v-model="bindForm.is_primary" active-text="主要诊断/手术" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="bindDialogVisible = false">取消</el-button>
        <el-button type="primary" @click="doBind">绑定</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script>
import { getHomeIcdBindings, getUncodedHomes, bindHomeIcd, unbindHomeIcd, setPrimaryIcd, getIcdStatistics } from "@/api/homeIcd";
import request from "@/utils/request";
import { ElMessage, ElMessageBox } from "element-plus";

export default {
  name: "HomeIcdWorkbench",
  data() {
    return {
      tab: "todo",
      loading: false,
      uncoded: [],
      bindings: [],
      stats: null,
      bindDialogVisible: false,
      currentHome: null,
      bindForm: { kind: "diagnosis", icd_code: "", is_primary: true },
      icdOptions: [],
      icdSearching: false,
    };
  },
  created() {
    this.loadAll();
  },
  methods: {
    async loadAll() {
      this.loading = true;
      try {
        const [uncoded, bindings, stats] = await Promise.all([getUncodedHomes(), getHomeIcdBindings({}), getIcdStatistics()]);
        this.uncoded = uncoded.data || [];
        this.bindings = bindings.data || [];
        this.stats = stats.data;
      } finally {
        this.loading = false;
      }
    },
    openBind(row) {
      this.currentHome = row;
      this.bindForm = { kind: "diagnosis", icd_code: "", is_primary: true };
      this.icdOptions = [];
      this.bindDialogVisible = true;
    },
    async searchIcd(keyword) {
      if (!keyword || keyword.length < 1) return;
      this.icdSearching = true;
      try {
        const url = this.bindForm.kind === "diagnosis" ? "icd10/diagnosis/list" : "icd10/operation/list";
        const res = await request({ url, method: "get", params: { keyword } });
        this.icdOptions = (res.data || []).slice(0, 30);
      } finally {
        this.icdSearching = false;
      }
    },
    async doBind() {
      const res = await bindHomeIcd({ home_id: this.currentHome.home_id, ...this.bindForm });
      if (res.code === 200) {
        ElMessage.success("编码已绑定");
        this.bindDialogVisible = false;
        this.loadAll();
      } else ElMessage.error(res.msg);
    },
    async markPrimary(row) {
      const res = await setPrimaryIcd({ binding_id: row.binding_id });
      if (res.code === 200) {
        ElMessage.success("已设为主要编码");
        this.loadAll();
      } else ElMessage.error(res.msg);
    },
    async removeBind(row) {
      await ElMessageBox.confirm(`确认删除编码 ${row.icd_code} ${row.icd_name}？`, "删除", { type: "warning" });
      const res = await unbindHomeIcd({ binding_id: row.binding_id });
      if (res.code === 200) this.loadAll();
      else ElMessage.error(res.msg);
    },
  },
};
</script>
