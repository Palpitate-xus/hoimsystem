<template>
  <div class="app-container">
    <vab-page-header title="医保目录对照" description="维护本院收费项目与医保目录的映射关系（用于费用上传与结算对照）" />
    <el-card>
      <div class="page-toolbar">
        <el-select v-model="query.local_item_type" placeholder="项目类型" clearable style="width: 130px" @change="load">
          <el-option v-for="(t, k) in typeText" :key="k" :label="t" :value="k" />
        </el-select>
        <el-input v-model="query.keyword" placeholder="本院项目/医保编码/名称" clearable style="width: 220px" @keyup.enter="load" />
        <el-button type="primary" @click="load">查询</el-button>
        <el-button type="success" @click="handleAdd">新增对照</el-button>
        <el-button @click="downloadTemplate">下载导入模板</el-button>
        <el-button @click="importDialogVisible = true">批量导入</el-button>
      </div>
      <el-table :data="tableData" v-loading="loading" border empty-text="暂无对照记录">
        <el-table-column prop="local_item_type_text" label="类型" width="80" />
        <el-table-column prop="local_item_name" label="本院项目" min-width="160" show-overflow-tooltip />
        <el-table-column prop="insurance_code" label="医保编码" width="120" />
        <el-table-column prop="insurance_name" label="医保名称" min-width="160" show-overflow-tooltip />
        <el-table-column prop="insurance_category" label="类别" width="70" />
        <el-table-column label="自付比例" width="90">
          <template #default="{ row }">{{ (row.self_pay_ratio * 100).toFixed(0) }}%</template>
        </el-table-column>
        <el-table-column prop="unit_price_limit" label="限价" width="90" />
        <el-table-column label="操作" width="150">
          <template #default="{ row }">
            <el-button size="small" @click="handleEdit(row)">编辑</el-button>
            <el-button size="small" type="danger" @click="handleDelete(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <el-dialog v-model="dialogVisible" :title="form.mapping_id ? '编辑对照' : '新增对照'" width="520px">
      <el-form :model="form" label-width="100px" class="dialog-form">
        <el-form-item label="项目类型">
          <el-select v-model="form.local_item_type">
            <el-option v-for="(t, k) in typeText" :key="k" :label="t" :value="k" />
          </el-select>
        </el-form-item>
        <el-form-item label="本院项目名">
          <el-input v-model="form.local_item_name" />
        </el-form-item>
        <el-form-item label="医保编码">
          <el-input v-model="form.insurance_code" />
        </el-form-item>
        <el-form-item label="医保名称">
          <el-input v-model="form.insurance_name" />
        </el-form-item>
        <el-form-item label="类别">
          <el-select v-model="form.insurance_category">
            <el-option label="甲类" value="甲类" />
            <el-option label="乙类" value="乙类" />
            <el-option label="丙类" value="丙类" />
            <el-option label="自费" value="自费" />
          </el-select>
        </el-form-item>
        <el-form-item label="自付比例">
          <el-slider v-model="ratioPercent" :min="0" :max="100" :step="5" show-input />
        </el-form-item>
        <el-form-item label="支付限价">
          <el-input-number v-model="form.unit_price_limit" :min="0" :controls="false" style="width: 100%" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="handleSave">保存</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="importDialogVisible" title="批量导入" width="640px">
      <el-alert type="info" :closable="false" title="先下载模板填写，再按行粘贴到下方（Tab 或逗号分隔），列顺序：本院项目类型、本院项目名称、医保编码、医保名称、类别、自付比例、限价" />
      <el-input v-model="importText" type="textarea" :rows="10" placeholder="药品,阿莫西林胶囊,XA01AB001,阿莫西林胶囊,甲类,0.1,&#10;检验,血常规,XA02,血常规(五分类),甲类,0," style="margin-top: 12px" />
      <template #footer>
        <el-button @click="importDialogVisible = false">取消</el-button>
        <el-button type="primary" @click="doImport">解析并导入</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script>
import { getInsuranceCatalogList, createInsuranceMapping, updateInsuranceMapping, deleteInsuranceMapping, importInsuranceMappings, downloadInsuranceTemplate } from "@/api/hisModules";
import { ElMessage, ElMessageBox } from "element-plus";

export default {
  name: "InsuranceCatalog",
  data() {
    return {
      typeText: { drug: "药品", consumable: "耗材", lab: "检验", exam: "检查", bed: "床位", surgery: "手术", anesthesia: "麻醉", registration: "挂号" },
      loading: false,
      saving: false,
      tableData: [],
      query: { local_item_type: null, keyword: "" },
      dialogVisible: false,
      form: {},
      importDialogVisible: false,
      importText: "",
    };
  },
  computed: {
    ratioPercent: {
      get() {
        return Math.round((this.form.self_pay_ratio || 0) * 100);
      },
      set(v) {
        this.form.self_pay_ratio = v / 100;
      },
    },
  },
  created() {
    this.load();
  },
  methods: {
    async load() {
      this.loading = true;
      try {
        const res = await getInsuranceCatalogList(this.query);
        this.tableData = res.data || [];
      } finally {
        this.loading = false;
      }
    },
    handleAdd() {
      this.form = { local_item_type: "drug", insurance_category: "甲类", self_pay_ratio: 0 };
      this.dialogVisible = true;
    },
    handleEdit(row) {
      this.form = { ...row };
      this.dialogVisible = true;
    },
    async handleSave() {
      this.saving = true;
      try {
        const api = this.form.mapping_id ? updateInsuranceMapping : createInsuranceMapping;
        const res = await api(this.form);
        if (res.code === 200) {
          ElMessage.success("保存成功");
          this.dialogVisible = false;
          this.load();
        } else ElMessage.error(res.msg);
      } finally {
        this.saving = false;
      }
    },
    async handleDelete(row) {
      await ElMessageBox.confirm("确认删除该对照？", "提示", { type: "warning" });
      const res = await deleteInsuranceMapping({ mapping_id: row.mapping_id });
      if (res.code === 200) this.load();
      else ElMessage.error(res.msg);
    },
    async downloadTemplate() {
      const blob = await downloadInsuranceTemplate();
      const url = URL.createObjectURL(new Blob([blob], { type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" }));
      const link = document.createElement("a");
      link.href = url;
      link.download = "insurance_catalog_template.xlsx";
      link.click();
      URL.revokeObjectURL(url);
    },
    async doImport() {
      const rows = this.importText.split("\n").map((line) => line.trim()).filter(Boolean).map((line) => {
        const parts = line.split(/[,\t，]/).map((s) => s.trim());
        return { 本院项目类型: parts[0], 本院项目名称: parts[1], 医保编码: parts[2], 医保名称: parts[3], 类别: parts[4], 自付比例: parts[5] || "0", 限价: parts[6] || "" };
      });
      if (!rows.length) return ElMessage.warning("未解析到数据行");
      const res = await importInsuranceMappings({ rows });
      if (res.code === 200) {
        ElMessage.success(`导入 ${res.data.imported} 行，跳过 ${res.data.skipped} 行${res.data.errors.length ? `；错误：${res.data.errors.join("；")}` : ""}`);
        this.importDialogVisible = false;
        this.load();
      } else ElMessage.error(res.msg);
    },
  },
};
</script>
