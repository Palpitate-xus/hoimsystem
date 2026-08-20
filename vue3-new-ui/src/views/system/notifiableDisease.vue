<template>
  <div class="app-container">
    <vab-page-header title="传染病报告卡" description="法定传染病院内登记与网直上报状态跟踪（上报状态机：待上报→已上报→已审核→订正）" />
    <el-card>
      <div class="page-toolbar">
        <el-select v-model="query.report_status" placeholder="上报状态" clearable style="width: 130px" @change="load">
          <el-option label="待上报" :value="0" />
          <el-option label="已上报网直" :value="1" />
          <el-option label="已审核" :value="2" />
          <el-option label="订正" :value="3" />
        </el-select>
        <el-button type="primary" @click="dialogVisible = true">填报报告卡</el-button>
      </div>
      <el-table :data="tableData" v-loading="loading" border empty-text="暂无报告卡">
        <el-table-column prop="patient_name" label="患者" width="90" />
        <el-table-column prop="disease_name" label="病种" min-width="130" />
        <el-table-column prop="disease_class" label="分类" width="70">
          <template #default="{ row }">
            <el-tag :type="row.disease_class === '甲类' ? 'danger' : row.disease_class === '乙类' ? 'warning' : 'info'" size="small">{{ row.disease_class || "-" }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="diagnosis_date" label="确诊日期" width="105" />
        <el-table-column prop="case_classification" label="病例分类" width="100" />
        <el-table-column prop="report_status_text" label="状态" width="100" />
        <el-table-column prop="report_card_no" label="网直卡号" width="120" />
        <el-table-column label="操作" width="200">
          <template #default="{ row }">
            <el-button v-if="row.report_status === 0 || row.report_status === 3" size="small" type="primary" @click="handleSubmit(row)">上报</el-button>
            <el-button v-if="row.report_status === 1" size="small" type="success" @click="handleAudit(row)">审核</el-button>
            <el-button v-if="row.report_status === 2" size="small" type="warning" @click="handleCorrect(row)">订正</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <el-dialog v-model="dialogVisible" title="填报传染病报告卡" width="520px">
      <el-form :model="form" label-width="100px" class="dialog-form">
        <el-form-item label="患者ID">
          <el-input v-model="form.patient_id" />
        </el-form-item>
        <el-form-item label="病种名称">
          <el-input v-model="form.disease_name" placeholder="如：肺结核、手足口病（将自动判甲/乙/丙类）" />
        </el-form-item>
        <el-form-item label="发病日期">
          <el-date-picker v-model="form.onset_date" type="date" value-format="YYYY-MM-DD" style="width: 100%" />
        </el-form-item>
        <el-form-item label="确诊日期">
          <el-date-picker v-model="form.diagnosis_date" type="date" value-format="YYYY-MM-DD" style="width: 100%" />
        </el-form-item>
        <el-form-item label="病例分类">
          <el-select v-model="form.case_classification">
            <el-option label="疑似病例" value="疑似病例" />
            <el-option label="临床诊断病例" value="临床诊断病例" />
            <el-option label="实验室确诊病例" value="实验室确诊病例" />
            <el-option label="病原携带者" value="病原携带者" />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" @click="handleCreate">填报</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script>
import { getNotifiableList, createNotifiable, submitNotifiable, auditNotifiable, correctNotifiable } from "@/api/hisModules";
import { ElMessage, ElMessageBox } from "element-plus";

export default {
  name: "NotifiableDisease",
  data() {
    return {
      loading: false,
      tableData: [],
      query: { report_status: null },
      dialogVisible: false,
      form: { case_classification: "临床诊断病例" },
    };
  },
  created() {
    this.load();
  },
  methods: {
    async load() {
      this.loading = true;
      try {
        const res = await getNotifiableList(this.query);
        this.tableData = res.data || [];
      } finally {
        this.loading = false;
      }
    },
    async handleCreate() {
      const res = await createNotifiable(this.form);
      if (res.code === 200) {
        ElMessage.success(`填报成功（${res.data.disease_class || "未识别分类，请人工核对"}）`);
        this.dialogVisible = false;
        this.load();
      } else ElMessage.error(res.msg);
    },
    async handleSubmit(row) {
      const { value } = await ElMessageBox.prompt("请输入网络直报系统返回的报卡编号", "上报网直", { inputPattern: /\S+/, inputErrorMessage: "卡号不能为空" });
      const res = await submitNotifiable({ report_id: row.report_id, report_card_no: value });
      if (res.code === 200) {
        ElMessage.success("已标记上报");
        this.load();
      } else ElMessage.error(res.msg);
    },
    async handleAudit(row) {
      await ElMessageBox.confirm("确认审核通过该报告卡？", "审核", { type: "warning" });
      const res = await auditNotifiable({ report_id: row.report_id });
      if (res.code === 200) this.load();
      else ElMessage.error(res.msg);
    },
    async handleCorrect(row) {
      const { value } = await ElMessageBox.prompt("订正后的病种名称", "订正", { inputValue: row.disease_name });
      const res = await correctNotifiable({ report_id: row.report_id, disease_name: value });
      if (res.code === 200) {
        ElMessage.success("已置为订正态，请重新上报");
        this.load();
      } else ElMessage.error(res.msg);
    },
  },
};
</script>
