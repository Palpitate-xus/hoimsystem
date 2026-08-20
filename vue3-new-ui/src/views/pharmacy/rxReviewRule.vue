<template>
  <div class="app-container">
    <vab-page-header title="审方规则引擎" description="药师维护用药安全规则，开方/审方时自动执行检查（不预置数据，由药师录入）" />
    <el-card>
      <div class="page-toolbar">
        <el-select v-model="query.rule_type" placeholder="规则类型" clearable style="width: 150px" @change="load">
          <el-option label="配伍禁忌" value="interaction" />
          <el-option label="禁忌" value="contraindication" />
          <el-option label="剂量范围" value="dose" />
          <el-option label="重复用药" value="duplicate" />
          <el-option label="过敏关键词" value="allergy_key" />
        </el-select>
        <el-button type="primary" @click="handleAdd">新增规则</el-button>
        <el-button @click="checkDialogVisible = true">处方预检</el-button>
      </div>
      <el-table :data="tableData" v-loading="loading" border empty-text="暂无规则，请点击「新增规则」录入">
        <el-table-column prop="rule_id" label="#" width="60" />
        <el-table-column prop="rule_type_text" label="类型" width="100" />
        <el-table-column label="药品条件" min-width="180">
          <template #default="{ row }">
            <span v-if="row.rule_type === 'interaction'">{{ row.drug_a }} × {{ row.drug_b }}</span>
            <span v-else-if="row.rule_type === 'dose'">
              {{ row.drug_a }}（{{ row.min_dose ?? '-' }} ~ {{ row.max_dose ?? '-' }} / 次；日限 {{ row.max_daily_dose ?? '-' }}）
            </span>
            <span v-else>{{ row.drug_a }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="severity_text" label="级别" width="80">
          <template #default="{ row }">
            <el-tag :type="row.severity === 3 ? 'danger' : row.severity === 2 ? 'warning' : 'info'">{{ row.severity_text }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="message" label="提示消息" min-width="200" show-overflow-tooltip />
        <el-table-column label="状态" width="80">
          <template #default="{ row }">
            <el-tag :type="row.status === 1 ? 'success' : 'info'">{{ row.status === 1 ? '启用' : '停用' }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="200">
          <template #default="{ row }">
            <el-button size="small" @click="handleEdit(row)">编辑</el-button>
            <el-button size="small" :type="row.status === 1 ? 'info' : 'success'" @click="toggleStatus(row)">{{ row.status === 1 ? '停用' : '启用' }}</el-button>
            <el-button size="small" type="danger" @click="handleDelete(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <el-dialog v-model="dialogVisible" :title="form.rule_id ? '编辑规则' : '新增规则'" width="560px">
      <el-form :model="form" label-width="110px" class="dialog-form">
        <el-form-item label="规则类型">
          <el-select v-model="form.rule_type" :disabled="!!form.rule_id">
            <el-option label="配伍禁忌（两药同开）" value="interaction" />
            <el-option label="禁忌（单药）" value="contraindication" />
            <el-option label="剂量范围" value="dose" />
            <el-option label="重复用药（同成分两药）" value="duplicate" />
            <el-option label="过敏关键词" value="allergy_key" />
          </el-select>
        </el-form-item>
        <el-form-item label="药品关键词A">
          <el-input v-model="form.drug_a" placeholder="药品名或名称片段，如：头孢" />
        </el-form-item>
        <el-form-item v-if="form.rule_type === 'interaction'" label="药品关键词B">
          <el-input v-model="form.drug_b" placeholder="如：酒精" />
        </el-form-item>
        <template v-if="form.rule_type === 'dose'">
          <el-form-item label="每次剂量下限">
            <el-input-number v-model="form.min_dose" :min="0" :controls="false" style="width: 100%" />
          </el-form-item>
          <el-form-item label="每次剂量上限">
            <el-input-number v-model="form.max_dose" :min="0" :controls="false" style="width: 100%" />
          </el-form-item>
          <el-form-item label="每日剂量上限">
            <el-input-number v-model="form.max_daily_dose" :min="0" :controls="false" style="width: 100%" />
          </el-form-item>
        </template>
        <el-form-item label="严重程度">
          <el-radio-group v-model="form.severity">
            <el-radio :label="1">提示</el-radio>
            <el-radio :label="2">警告</el-radio>
            <el-radio :label="3">禁止</el-radio>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="提示消息">
          <el-input v-model="form.message" type="textarea" :rows="2" placeholder="如：头孢与酒精同用可致双硫仑反应，禁止联用" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="handleSave">保存</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="checkDialogVisible" title="处方预检" width="640px">
      <el-form label-width="90px">
        <el-form-item label="患者ID">
          <el-input v-model="checkForm.patient_id" placeholder="选填，用于过敏史匹配" style="width: 200px" />
        </el-form-item>
        <el-form-item v-for="(item, i) in checkForm.items" :key="i" :label="`药品${i + 1}`">
          <div style="display: flex; gap: 8px; width: 100%">
            <el-input v-model="item.name" placeholder="药品名" style="flex: 1" />
            <el-input-number v-model="item.dosage" :min="0" placeholder="每次剂量" :controls="false" style="width: 110px" />
            <el-select v-model="item.frequency" style="width: 100px">
              <el-option v-for="f in ['qd', 'bid', 'tid', 'qid', 'q8h', 'q6h', 'qn', 'prn', 'st']" :key="f" :label="f" :value="f" />
            </el-select>
            <el-button type="danger" circle size="small" @click="checkForm.items.splice(i, 1)">−</el-button>
          </div>
        </el-form-item>
        <el-button size="small" @click="checkForm.items.push({ name: '', dosage: null, frequency: 'bid' })">+ 添加药品</el-button>
      </el-form>
      <el-divider content-position="left">检查结果</el-divider>
      <div v-if="checkResult">
        <el-alert v-if="checkResult.blocked" type="error" :closable="false" title="存在「禁止」级规则命中，处方不可通过" />
        <el-alert v-else-if="checkResult.findings.length" type="warning" :closable="false" title="存在提示/警告级命中" />
        <el-alert v-else type="success" :closable="false" title="未命中任何规则" />
        <el-table v-if="checkResult.findings.length" :data="checkResult.findings" border size="small" style="margin-top: 8px">
          <el-table-column prop="severity" label="级别" width="70">
            <template #default="{ row }">
              <el-tag size="small" :type="row.severity === 3 ? 'danger' : row.severity === 2 ? 'warning' : 'info'">{{ { 1: '提示', 2: '警告', 3: '禁止' }[row.severity] }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="message" label="消息" />
        </el-table>
      </div>
      <template #footer>
        <el-button @click="checkDialogVisible = false">关闭</el-button>
        <el-button type="primary" @click="runCheck">执行预检</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script>
import { getRxRuleList, createRxRule, updateRxRule, deleteRxRule, rxCheck } from "@/api/hisModules";
import { ElMessage, ElMessageBox } from "element-plus";

export default {
  name: "RxReviewRule",
  data() {
    return {
      loading: false,
      saving: false,
      tableData: [],
      query: { rule_type: null },
      dialogVisible: false,
      form: {},
      checkDialogVisible: false,
      checkForm: { patient_id: "", items: [{ name: "", dosage: null, frequency: "bid" }] },
      checkResult: null,
    };
  },
  created() {
    this.load();
  },
  methods: {
    async load() {
      this.loading = true;
      try {
        const res = await getRxRuleList(this.query);
        this.tableData = res.data || [];
      } finally {
        this.loading = false;
      }
    },
    handleAdd() {
      this.form = { rule_type: "interaction", severity: 2 };
      this.dialogVisible = true;
    },
    handleEdit(row) {
      this.form = { ...row };
      this.dialogVisible = true;
    },
    async handleSave() {
      this.saving = true;
      try {
        const api = this.form.rule_id ? updateRxRule : createRxRule;
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
    async toggleStatus(row) {
      const res = await updateRxRule({ rule_id: row.rule_id, status: row.status === 1 ? 0 : 1 });
      if (res.code === 200) this.load();
      else ElMessage.error(res.msg);
    },
    async handleDelete(row) {
      await ElMessageBox.confirm("确认删除该规则？", "提示", { type: "warning" });
      const res = await deleteRxRule({ rule_id: row.rule_id });
      if (res.code === 200) {
        ElMessage.success("已删除");
        this.load();
      } else ElMessage.error(res.msg);
    },
    async runCheck() {
      const res = await rxCheck({
        patient_id: this.checkForm.patient_id || undefined,
        items: this.checkForm.items.filter((i) => i.name),
      });
      if (res.code === 200) this.checkResult = res.data;
      else ElMessage.error(res.msg);
    },
  },
};
</script>
