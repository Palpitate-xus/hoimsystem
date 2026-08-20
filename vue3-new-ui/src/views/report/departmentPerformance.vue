<template>
  <div class="app-container">
    <vab-page-header title="科室绩效核算" description="工作量×绩效系数 − 成本分摊（明细手工录入，服务端核算）" />
    <el-card>
      <div class="page-toolbar">
        <el-input v-model="query.period" placeholder="统计期 如 2026-08" clearable style="width: 150px" @keyup.enter="load" />
        <el-button type="primary" @click="load">查询</el-button>
        <el-button type="success" @click="openCreate">新建核算</el-button>
      </div>
      <el-table :data="tableData" v-loading="loading" border empty-text="暂无核算记录">
        <el-table-column prop="period" label="统计期" width="90" />
        <el-table-column prop="department_name" label="科室" width="120" />
        <el-table-column prop="total_workload" label="工作量总分" width="100" />
        <el-table-column prop="total_cost" label="总成本" width="100" />
        <el-table-column prop="coefficient" label="系数" width="70" />
        <el-table-column label="绩效总额" width="110">
          <template #default="{ row }">
            <span :style="{ color: row.performance_amount < 0 ? 'var(--el-color-danger)' : 'var(--el-color-success)' }">{{ row.performance_amount }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="status_text" label="状态" width="90">
          <template #default="{ row }">
            <el-tag size="small" :type="{ 0: 'info', 1: 'warning', 2: 'success' }[row.status]">{{ row.status_text }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="creator_name" label="创建人" width="90" />
        <el-table-column label="操作" width="230">
          <template #default="{ row }">
            <el-button size="small" @click="openDetail(row)">明细</el-button>
            <el-button v-if="row.status === 0" size="small" type="primary" @click="edit(row)">编辑</el-button>
            <el-button v-if="row.status === 0" size="small" type="warning" @click="submit(row)">提交</el-button>
            <template v-if="row.status === 1">
              <el-button size="small" type="success" @click="audit(row, true)">审核发放</el-button>
              <el-button size="small" @click="audit(row, false)">退回</el-button>
            </template>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <!-- 新建/编辑 -->
    <el-dialog v-model="dialogVisible" :title="form.performance_id ? '编辑核算（草稿）' : '新建核算'" width="760px">
      <el-form :model="form" label-width="100px">
        <el-form-item label="统计期"><el-input v-model="form.period" placeholder="2026-08" style="width: 200px" /></el-form-item>
        <el-form-item label="科室">
          <el-select v-model="form.department_id" filterable style="width: 260px">
            <el-option v-for="d in departments" :key="d.department_id" :label="d.name" :value="d.department_id" />
          </el-select>
        </el-form-item>
        <el-form-item label="绩效系数">
          <el-input-number v-model="form.coefficient" :min="0" :max="10" :step="0.1" :precision="3" />
        </el-form-item>
        <el-divider content-position="left">工作量明细（数量×单价 或直接填小计）</el-divider>
        <el-table :data="form.workload_items" size="small" border>
          <el-table-column label="项目"><template #default="{ row }"><el-input v-model="row['项目']" placeholder="门诊诊查/出院人次/手术台次" /></template></el-table-column>
          <el-table-column label="数量" width="110"><template #default="{ row }"><el-input-number v-model="row['数量']" :controls="false" style="width: 100%" /></template></el-table-column>
          <el-table-column label="单价" width="110"><template #default="{ row }"><el-input-number v-model="row['单价']" :controls="false" :precision="2" style="width: 100%" /></template></el-table-column>
          <el-table-column label="小计(可直填)" width="130"><template #default="{ row }"><el-input-number v-model="row['小计']" :controls="false" :precision="2" style="width: 100%" /></template></el-table-column>
          <el-table-column width="60"><template #default="{ $index }"><el-button type="danger" circle size="small" @click="form.workload_items.splice($index, 1)">−</el-button></template></el-table-column>
        </el-table>
        <el-button size="small" style="margin: 6px 0" @click="form.workload_items.push({ 项目: '', 数量: null, 单价: null, 小计: null })">+ 工作量项</el-button>

        <el-divider content-position="left">成本分摊明细（按科目金额）</el-divider>
        <el-table :data="form.cost_items" size="small" border>
          <el-table-column label="科目"><template #default="{ row }"><el-input v-model="row['科目']" placeholder="人力成本/耗材分摊/折旧" /></template></el-table-column>
          <el-table-column label="金额" width="160"><template #default="{ row }"><el-input-number v-model="row['金额']" :controls="false" :precision="2" style="width: 100%" /></template></el-table-column>
          <el-table-column width="60"><template #default="{ $index }"><el-button type="danger" circle size="small" @click="form.cost_items.splice($index, 1)">−</el-button></template></el-table-column>
        </el-table>
        <el-button size="small" style="margin: 6px 0" @click="form.cost_items.push({ 科目: '', 金额: null })">+ 成本项</el-button>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" @click="save">{{ form.performance_id ? "保存重算" : "创建" }}</el-button>
      </template>
    </el-dialog>

    <!-- 明细查看 -->
    <el-dialog v-model="detailVisible" title="核算明细" width="700px">
      <template v-if="detailRow">
        <el-descriptions :column="3" border size="small">
          <el-descriptions-item label="统计期">{{ detailRow.period }}</el-descriptions-item>
          <el-descriptions-item label="科室">{{ detailRow.department_name }}</el-descriptions-item>
          <el-descriptions-item label="系数">{{ detailRow.coefficient }}</el-descriptions-item>
          <el-descriptions-item label="工作量">{{ detailRow.total_workload }}</el-descriptions-item>
          <el-descriptions-item label="成本">{{ detailRow.total_cost }}</el-descriptions-item>
          <el-descriptions-item label="绩效">{{ detailRow.performance_amount }}</el-descriptions-item>
        </el-descriptions>
        <h4>工作量</h4>
        <el-table :data="detailRow.workload_items" size="small" border>
          <el-table-column prop="项目" label="项目" />
          <el-table-column prop="数量" label="数量" width="90" />
          <el-table-column prop="单价" label="单价" width="90" />
          <el-table-column prop="小计" label="小计" width="100" />
        </el-table>
        <h4>成本分摊</h4>
        <el-table :data="detailRow.cost_items" size="small" border>
          <el-table-column prop="科目" label="科目" />
          <el-table-column prop="金额" label="金额" width="120" />
        </el-table>
      </template>
    </el-dialog>
  </div>
</template>

<script>
import { getPerformanceList, createPerformance, updatePerformance, submitPerformance, auditPerformance } from "@/api/performance";
import { getDepartmentList } from "@/api/admin";
import { ElMessage, ElMessageBox } from "element-plus";

export default {
  name: "DepartmentPerformance",
  data() {
    return {
      loading: false,
      tableData: [],
      query: { period: "" },
      dialogVisible: false,
      form: { workload_items: [], cost_items: [], coefficient: 1 },
      departments: [],
      detailVisible: false,
      detailRow: null,
    };
  },
  created() {
    this.load();
    getDepartmentList().then(res => {
      this.departments = (res.data || []).filter(d => d.status === 0);
    });
  },
  methods: {
    async load() {
      this.loading = true;
      try {
        const res = await getPerformanceList(this.query);
        this.tableData = res.data || [];
      } finally {
        this.loading = false;
      }
    },
    openCreate() {
      this.form = { period: "", department_id: null, coefficient: 1, workload_items: [], cost_items: [] };
      this.dialogVisible = true;
    },
    edit(row) {
      this.form = {
        performance_id: row.performance_id,
        period: row.period,
        department_id: row.department_id,
        coefficient: row.coefficient,
        workload_items: row.workload_items.map(i => ({ ...i })),
        cost_items: row.cost_items.map(i => ({ ...i })),
      };
      this.dialogVisible = true;
    },
    async save() {
      const api = this.form.performance_id ? updatePerformance : createPerformance;
      const res = await api(this.form);
      if (res.code === 200) {
        ElMessage.success(`核算完成，绩效总额：${res.data.performance_amount}`);
        this.dialogVisible = false;
        this.load();
      } else ElMessage.error(res.msg);
    },
    openDetail(row) {
      this.detailRow = row;
      this.detailVisible = true;
    },
    async submit(row) {
      await ElMessageBox.confirm("提交后明细锁定，等待审核发放", "提交核算", { type: "warning" });
      const res = await submitPerformance({ performance_id: row.performance_id });
      if (res.code === 200) this.load();
      else ElMessage.error(res.msg);
    },
    async audit(row, approve) {
      if (approve) await ElMessageBox.confirm(`确认发放 ${row.department_name} ${row.period} 绩效 ${row.performance_amount}？`, "审核发放", { type: "warning" });
      const res = await auditPerformance({ performance_id: row.performance_id, approve });
      if (res.code === 200) {
        ElMessage.success(approve ? "已审核发放" : "已退回草稿");
        this.load();
      } else ElMessage.error(res.msg);
    },
  },
};
</script>
