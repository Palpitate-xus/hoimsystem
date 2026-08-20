<template>
  <div class="app-container">
    <vab-page-header title="不良事件 RCA 与 HQMS 指标" description="RCA 根因分析（PDCA 闭环）与医疗质量指标上报" />
    <el-tabs v-model="tab">
      <el-tab-pane label="RCA 根因分析" name="rca">
        <div class="page-toolbar">
          <el-button type="primary" @click="rcaDialogVisible = true">发起 RCA</el-button>
        </div>
        <el-table :data="rcaData" v-loading="rcaLoading" border empty-text="暂无 RCA 记录">
          <el-table-column prop="event_id" label="事件ID" width="80" />
          <el-table-column prop="event_summary" label="事件概述" min-width="180" show-overflow-tooltip />
          <el-table-column prop="responsible_dept" label="责任科室" width="110" />
          <el-table-column label="PDCA" width="60">
            <template #default="{ row }">
              <el-tag size="small" :type="{ P: 'info', D: 'warning', C: 'primary', A: 'success' }[row.pdca_cycle]">{{ row.pdca_cycle }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="due_date" label="整改期限" width="105" />
          <el-table-column prop="completed_date" label="完成日期" width="105" />
          <el-table-column label="操作" width="110">
            <template #default="{ row }">
              <el-button v-if="row.pdca_cycle !== 'A'" size="small" type="primary" @click="handleAdvance(row)">{{ { P: "执行(D)", D: "检查(C)", C: "处置(A)" }[row.pdca_cycle] }}</el-button>
            </template>
          </el-table-column>
        </el-table>
      </el-tab-pane>

      <el-tab-pane label="HQMS 指标" name="hqms">
        <div class="page-toolbar">
          <el-input v-model="hqmsQuery.period" placeholder="统计期 如 2026-08" clearable style="width: 150px" @keyup.enter="loadHqms" />
          <el-button type="primary" @click="loadHqms">查询</el-button>
          <el-button type="success" @click="hqmsDialogVisible = true">录入指标</el-button>
          <el-button @click="hqmsImportVisible = true">批量导入</el-button>
          <el-button type="warning" :disabled="!selectedHqms.length" @click="handleSubmitHqms">上报选中（{{ selectedHqms.length }}）</el-button>
        </div>
        <el-table :data="hqmsData" v-loading="hqmsLoading" border empty-text="暂无指标数据" @selection-change="(v) => (selectedHqms = v)">
          <el-table-column type="selection" :selectable="(row) => row.report_status === 0" width="45" />
          <el-table-column prop="period" label="统计期" width="90" />
          <el-table-column prop="indicator_code" label="编码" width="110" />
          <el-table-column prop="indicator_name" label="指标名称" min-width="170" show-overflow-tooltip />
          <el-table-column label="值" width="100">
            <template #default="{ row }">{{ row.indicator_value ?? "-" }} {{ row.unit }}</template>
          </el-table-column>
          <el-table-column label="分子/分母" width="110">
            <template #default="{ row }">{{ row.numerator ?? "-" }}/{{ row.denominator ?? "-" }}</template>
          </el-table-column>
          <el-table-column prop="department" label="科室" width="100" />
          <el-table-column prop="report_status_text" label="状态" width="80">
            <template #default="{ row }">
              <el-tag size="small" :type="row.report_status === 0 ? 'info' : 'success'">{{ row.report_status_text }}</el-tag>
            </template>
          </el-table-column>
        </el-table>
      </el-tab-pane>

      <el-tab-pane label="围术期抗菌药依从" name="antibiotic">
        <div class="page-toolbar">
          <el-date-picker v-model="abQuery.start_date" type="date" value-format="YYYY-MM-DD" placeholder="开始日期" />
          <el-date-picker v-model="abQuery.end_date" type="date" value-format="YYYY-MM-DD" placeholder="结束日期" />
          <el-button type="primary" @click="loadAntibiotic">统计</el-button>
        </div>
        <template v-if="abStats">
          <el-alert type="info" :closable="false" :title="abStats.rule" style="margin-bottom: 12px" />
          <el-descriptions :column="4" border>
            <el-descriptions-item label="已执行给药">{{ abStats.total_executed }}</el-descriptions-item>
            <el-descriptions-item label="依从例数">{{ abStats.compliant }}</el-descriptions-item>
            <el-descriptions-item label="依从率">
              <span :style="{ color: (abStats.compliance_rate ?? 0) < 90 ? 'var(--el-color-danger)' : 'var(--el-color-success)' }">{{ abStats.compliance_rate ?? "-" }}%</span>
            </el-descriptions-item>
            <el-descriptions-item label="过早(>2h)/过晚(<0.5h)">{{ abStats.too_early_gt120min }} / {{ abStats.too_late_lt30min }}</el-descriptions-item>
          </el-descriptions>
          <el-table v-if="abStats.by_level.length" :data="abStats.by_level" border style="margin-top: 12px">
            <el-table-column prop="level" label="手术级别" width="100">
              <template #default="{ row }">{{ { 1: "一级", 2: "二级", 3: "三级", 4: "四级" }[row.level] || "未分级" }}</template>
            </el-table-column>
            <el-table-column prop="total" label="例数" width="90" />
            <el-table-column prop="compliant" label="依从" width="90" />
            <el-table-column prop="rate" label="依从率">
              <template #default="{ row }">{{ row.rate ?? "-" }}%</template>
            </el-table-column>
          </el-table>
        </template>
      </el-tab-pane>
    </el-tabs>

    <el-dialog v-model="rcaDialogVisible" title="发起 RCA 分析" width="560px">
      <el-form :model="rcaForm" label-width="100px" class="dialog-form">
        <el-form-item label="不良事件ID">
          <el-input v-model="rcaForm.event_id" placeholder="不良事件上报列表中的事件编号" />
        </el-form-item>
        <el-form-item label="事件概述">
          <el-input v-model="rcaForm.event_summary" type="textarea" :rows="2" placeholder="留空自动取事件描述" />
        </el-form-item>
        <el-form-item label="时间线还原">
          <el-input v-model="rcaForm.timeline" type="textarea" :rows="3" placeholder="事件发生时间线（可选）" />
        </el-form-item>
        <el-form-item label="根因分析">
          <el-input v-model="rcaForm.root_cause" type="textarea" :rows="3" placeholder="从人/机/料/法/环五方面分析" />
        </el-form-item>
        <el-form-item label="改进措施">
          <el-input v-model="rcaForm.corrective_actions" type="textarea" :rows="3" />
        </el-form-item>
        <el-form-item label="责任科室">
          <el-input v-model="rcaForm.responsible_dept" />
        </el-form-item>
        <el-form-item label="整改期限">
          <el-date-picker v-model="rcaForm.due_date" type="date" value-format="YYYY-MM-DD" style="width: 100%" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="rcaDialogVisible = false">取消</el-button>
        <el-button type="primary" @click="handleCreateRca">创建</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="hqmsDialogVisible" title="录入 HQMS 指标" width="520px">
      <el-form :model="hqmsForm" label-width="100px" class="dialog-form">
        <el-form-item label="统计期">
          <el-input v-model="hqmsForm.period" placeholder="2026-08（月）或 2026（年）" />
        </el-form-item>
        <el-form-item label="指标编码">
          <el-input v-model="hqmsForm.indicator_code" />
        </el-form-item>
        <el-form-item label="指标名称">
          <el-input v-model="hqmsForm.indicator_name" />
        </el-form-item>
        <el-form-item label="分子">
          <el-input-number v-model="hqmsForm.numerator" :controls="false" style="width: 100%" />
        </el-form-item>
        <el-form-item label="分母">
          <el-input-number v-model="hqmsForm.denominator" :min="0" :controls="false" style="width: 100%" />
        </el-form-item>
        <el-form-item label="单位">
          <el-select v-model="hqmsForm.unit">
            <el-option label="%" value="%" />
            <el-option label="‰" value="‰" />
            <el-option label="天" value="天" />
            <el-option label="例" value="例" />
          </el-select>
        </el-form-item>
        <el-form-item label="科室">
          <el-input v-model="hqmsForm.department" placeholder="留空为全院" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="hqmsDialogVisible = false">取消</el-button>
        <el-button type="primary" @click="handleCreateHqms">保存</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="hqmsImportVisible" title="批量导入指标" width="640px">
      <el-alert type="info" :closable="false" title="按行粘贴（Tab 或逗号分隔）：统计期,指标编码,指标名称,分子,分母,单位,科室,备注" />
      <el-input v-model="hqmsImportText" type="textarea" :rows="10" style="margin-top: 12px" placeholder="2026-08,A01,住院患者死亡率,3,1000,‰,,&#10;2026-08,A02,31天再入院率,12,800,%,心内科," />
      <template #footer>
        <el-button @click="hqmsImportVisible = false">取消</el-button>
        <el-button type="primary" @click="doImportHqms">解析并导入</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script>
import { getRcaList, createRca, advanceRca, getHqmsList, createHqms, importHqms, submitHqms } from "@/api/hisModules";
import { getAntibioticCompliance } from "@/api/homeIcd";
import { ElMessage, ElMessageBox } from "element-plus";

export default {
  name: "QualityManagement",
  data() {
    return {
      tab: "rca",
      rcaLoading: false,
      rcaData: [],
      rcaDialogVisible: false,
      rcaForm: {},
      hqmsLoading: false,
      hqmsData: [],
      hqmsQuery: { period: "" },
      hqmsDialogVisible: false,
      hqmsForm: { unit: "%" },
      hqmsImportVisible: false,
      hqmsImportText: "",
      selectedHqms: [],
      abQuery: { start_date: "", end_date: "" },
      abStats: null,
    };
  },
  created() {
    this.loadRca();
    this.loadHqms();
    this.loadAntibiotic();
  },
  methods: {
    async loadRca() {
      this.rcaLoading = true;
      try {
        const res = await getRcaList({});
        this.rcaData = res.data || [];
      } finally {
        this.rcaLoading = false;
      }
    },
    async handleCreateRca() {
      const res = await createRca(this.rcaForm);
      if (res.code === 200) {
        ElMessage.success("RCA 已创建，进入 P 阶段");
        this.rcaDialogVisible = false;
        this.rcaForm = {};
        this.loadRca();
      } else ElMessage.error(res.msg);
    },
    async handleAdvance(row) {
      const next = { P: "D", D: "C", C: "A" }[row.pdca_cycle];
      let payload = { rca_id: row.rca_id, pdca_cycle: next };
      if (next === "A") {
        const { value } = await ElMessageBox.prompt("进入 A 阶段请填写效果评价", "效果评价", { inputPattern: /\S+/, inputErrorMessage: "必填" });
        payload.effect_evaluation = value;
      } else {
        await ElMessageBox.confirm(`确认将 RCA 推进到 ${next} 阶段？`, "PDCA 推进");
      }
      const res = await advanceRca(payload);
      if (res.code === 200) {
        ElMessage.success("已推进");
        this.loadRca();
      } else ElMessage.error(res.msg);
    },
    async loadHqms() {
      this.hqmsLoading = true;
      try {
        const res = await getHqmsList(this.hqmsQuery);
        this.hqmsData = res.data || [];
      } finally {
        this.hqmsLoading = false;
      }
    },
    async handleCreateHqms() {
      const res = await createHqms(this.hqmsForm);
      if (res.code === 200) {
        ElMessage.success("已录入");
        this.hqmsDialogVisible = false;
        this.hqmsForm = { unit: "%" };
        this.loadHqms();
      } else ElMessage.error(res.msg);
    },
    async doImportHqms() {
      const rows = this.hqmsImportText.split("\n").map((l) => l.trim()).filter(Boolean).map((line) => {
        const p = line.split(/[,\t，]/).map((s) => s.trim());
        return { 统计期: p[0], 指标编码: p[1], 指标名称: p[2], 分子: p[3], 分母: p[4], 单位: p[5], 科室: p[6], 备注: p[7] };
      });
      if (!rows.length) return ElMessage.warning("未解析到数据行");
      const res = await importHqms({ rows });
      if (res.code === 200) {
        ElMessage.success(`导入 ${res.data.imported} 行${res.data.errors.length ? `；错误：${res.data.errors.join("；")}` : ""}`);
        this.hqmsImportVisible = false;
        this.loadHqms();
      } else ElMessage.error(res.msg);
    },
    async handleSubmitHqms() {
      await ElMessageBox.confirm(`确认上报选中的 ${this.selectedHqms.length} 项指标？`, "上报", { type: "warning" });
      const res = await submitHqms({ ids: this.selectedHqms.map((r) => r.indicator_id) });
      if (res.code === 200) {
        ElMessage.success(`已上报 ${res.data.updated} 项`);
        this.loadHqms();
      } else ElMessage.error(res.msg);
    },
    async loadAntibiotic() {
      const params = {};
      if (this.abQuery.start_date) params.start_date = this.abQuery.start_date;
      if (this.abQuery.end_date) params.end_date = this.abQuery.end_date;
      const res = await getAntibioticCompliance(params);
      if (res.code === 200) this.abStats = res.data;
      else ElMessage.error(res.msg);
    },
  },
};
</script>
