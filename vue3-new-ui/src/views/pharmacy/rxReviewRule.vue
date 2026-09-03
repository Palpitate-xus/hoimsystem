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
          <el-option label="患者条件" value="context" />
        </el-select>
        <el-button v-if="canManage" type="primary" @click="handleAdd">新增规则</el-button>
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
            <span v-else-if="row.rule_type === 'context'">{{ row.drug_a }} · {{ formatCondition(row.condition) }}</span>
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
        <el-table-column v-if="canManage" label="操作" width="200">
          <template #default="{ row }">
            <el-button size="small" @click="handleEdit(row)">编辑</el-button>
            <el-button size="small" :type="row.status === 1 ? 'info' : 'success'" @click="toggleStatus(row)">{{ row.status === 1 ? '停用' : '启用' }}</el-button>
            <el-button size="small" type="danger" @click="handleDelete(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <el-dialog v-model="dialogVisible" :title="form.rule_id ? '编辑规则' : '新增规则'" width="720px">
      <el-form :model="form" label-width="110px" class="dialog-form">
        <el-form-item label="规则类型">
          <el-select v-model="form.rule_type" :disabled="!!form.rule_id">
            <el-option label="配伍禁忌（两药同开）" value="interaction" />
            <el-option label="禁忌（单药）" value="contraindication" />
            <el-option label="剂量范围" value="dose" />
            <el-option label="重复用药（同成分两药）" value="duplicate" />
            <el-option label="过敏关键词" value="allergy_key" />
            <el-option label="患者条件（年龄/肝肾功能/诊断/检验）" value="context" />
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
        <template v-if="form.rule_type === 'context'">
          <el-row :gutter="12">
            <el-col :span="12"><el-form-item label="年龄范围"><el-input-number v-model="form.condition.min_age" :min="0" :max="150" placeholder="最小" style="width: 48%" /> ～ <el-input-number v-model="form.condition.max_age" :min="0" :max="150" placeholder="最大" style="width: 48%" /></el-form-item></el-col>
            <el-col :span="12"><el-form-item label="体重范围"><el-input-number v-model="form.condition.min_weight" :min="0" placeholder="最小" style="width: 48%" /> ～ <el-input-number v-model="form.condition.max_weight" :min="0" placeholder="最大" style="width: 48%" /></el-form-item></el-col>
            <el-col :span="12"><el-form-item label="eGFR 范围"><el-input-number v-model="form.condition.min_egfr" :min="0" :max="300" placeholder="最小" style="width: 48%" /> ～ <el-input-number v-model="form.condition.max_egfr" :min="0" :max="300" placeholder="最大" style="width: 48%" /></el-form-item></el-col>
            <el-col :span="12"><el-form-item label="妊娠"><el-select v-model="form.condition.pregnant" clearable style="width: 100%"><el-option label="是" :value="true" /><el-option label="否" :value="false" /></el-select></el-form-item></el-col>
            <el-col :span="12"><el-form-item label="性别"><el-select v-model="form.condition.sex" clearable style="width: 100%"><el-option label="女" :value="0" /><el-option label="男" :value="1" /></el-select></el-form-item></el-col>
            <el-col :span="12"><el-form-item label="肝损害至少"><el-select v-model="form.condition.hepatic_min" clearable style="width: 100%"><el-option label="轻度" :value="1" /><el-option label="中度" :value="2" /><el-option label="重度" :value="3" /></el-select></el-form-item></el-col>
          </el-row>
          <el-form-item label="诊断关键词"><el-input v-model="conditionDiagnoses" placeholder="多个关键词用逗号分隔" /></el-form-item>
          <el-form-item label="检验条件 JSON"><el-input v-model="conditionLabs" type="textarea" :rows="2" placeholder='如 {"钾":{"min":5.5},"ALT":{"max":120}}' /></el-form-item>
        </template>
        <el-row :gutter="12">
          <el-col :span="12"><el-form-item label="规则来源"><el-input v-model="form.source" placeholder="药事委员会/指南名称" /></el-form-item></el-col>
          <el-col :span="12"><el-form-item label="版本"><el-input v-model="form.version" placeholder="如 2026.1" /></el-form-item></el-col>
          <el-col :span="12"><el-form-item label="生效日期"><el-date-picker v-model="form.effective_from" value-format="YYYY-MM-DD" style="width: 100%" /></el-form-item></el-col>
          <el-col :span="12"><el-form-item label="失效日期"><el-date-picker v-model="form.effective_to" value-format="YYYY-MM-DD" style="width: 100%" /></el-form-item></el-col>
        </el-row>
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
          <el-button v-if="checkForm.patient_id" style="margin-left: 8px" @click="openProfile">维护临床档案</el-button>
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

    <el-dialog v-model="profileDialogVisible" title="患者临床档案" width="620px">
      <el-alert v-if="profileDerived.age !== undefined" type="info" :closable="false" style="margin-bottom: 12px" :title="`系统推导：年龄 ${profileDerived.age ?? '未知'} 岁，最近体重 ${profileDerived.weight ?? '未知'} kg`" />
      <el-form :model="profileForm" label-width="110px" v-loading="profileLoading">
        <el-row :gutter="12">
          <el-col :span="12"><el-form-item label="妊娠状态"><el-select v-model="profileForm.pregnant" clearable style="width: 100%"><el-option label="是" :value="true" /><el-option label="否" :value="false" /></el-select></el-form-item></el-col>
          <el-col :span="12"><el-form-item label="eGFR"><el-input-number v-model="profileForm.egfr" :min="0" :max="300" :controls="false" style="width: 100%" /></el-form-item></el-col>
          <el-col :span="12"><el-form-item label="肝功能损害"><el-select v-model="profileForm.hepatic_impairment" style="width: 100%"><el-option label="无" :value="0" /><el-option label="轻度" :value="1" /><el-option label="中度" :value="2" /><el-option label="重度" :value="3" /></el-select></el-form-item></el-col>
        </el-row>
        <el-form-item label="结构化诊断"><el-input v-model="profileDiagnoses" type="textarea" :rows="3" placeholder="每行一个诊断" /></el-form-item>
        <el-form-item label="关键检验 JSON"><el-input v-model="profileLabs" type="textarea" :rows="3" placeholder='如 {"钾":4.2,"ALT":35}' /></el-form-item>
      </el-form>
      <template #footer><el-button @click="profileDialogVisible = false">取消</el-button><el-button type="primary" :loading="profileSaving" @click="saveProfile">保存档案</el-button></template>
    </el-dialog>
  </div>
</template>

<script>
import { getClinicalProfile, getRxRuleList, createRxRule, updateRxRule, deleteRxRule, rxCheck, saveClinicalProfile } from "@/api/hisModules";
import { ElMessage, ElMessageBox } from "element-plus";
import { mapGetters } from "vuex";

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
      conditionDiagnoses: "",
      conditionLabs: "",
      profileDialogVisible: false,
      profileLoading: false,
      profileSaving: false,
      profileDerived: {},
      profileForm: { pregnant: null, egfr: null, hepatic_impairment: 0 },
      profileDiagnoses: "",
      profileLabs: "{}",
    };
  },
  computed: {
    ...mapGetters({ permissions: "user/permissions" }),
    canManage() {
      return (this.permissions || []).some((role) => ["admin", "super_admin", "pharmacist"].includes(role));
    },
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
      this.form = { rule_type: "interaction", severity: 2, condition: {} };
      this.conditionDiagnoses = "";
      this.conditionLabs = "";
      this.dialogVisible = true;
    },
    handleEdit(row) {
      this.form = { ...row, condition: { ...(row.condition || {}) } };
      this.conditionDiagnoses = (row.condition?.diagnosis_keywords || []).join(",");
      this.conditionLabs = row.condition?.labs ? JSON.stringify(row.condition.labs) : "";
      this.dialogVisible = true;
    },
    async handleSave() {
      this.saving = true;
      try {
        const payload = { ...this.form };
        if (payload.rule_type === "context") {
          const condition = Object.fromEntries(Object.entries(payload.condition || {}).filter(([, value]) => value !== null && value !== "" && value !== undefined));
          delete condition.diagnosis_keywords;
          delete condition.labs;
          const diagnoses = this.conditionDiagnoses.split(/[,，\n]/).map((item) => item.trim()).filter(Boolean);
          if (diagnoses.length) condition.diagnosis_keywords = diagnoses;
          if (this.conditionLabs.trim()) condition.labs = JSON.parse(this.conditionLabs);
          payload.condition = condition;
        }
        const api = this.form.rule_id ? updateRxRule : createRxRule;
        const res = await api(payload);
        if (res.code === 200) {
          ElMessage.success("保存成功");
          this.dialogVisible = false;
          this.load();
        } else ElMessage.error(res.msg);
      } catch (error) {
        ElMessage.error(error instanceof SyntaxError ? "检验条件必须是合法 JSON" : error.msg || "保存失败");
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
    formatCondition(condition) {
      if (!condition) return "未配置";
      return Object.entries(condition).map(([key, value]) => `${key}=${typeof value === "object" ? JSON.stringify(value) : value}`).join("；");
    },
    async openProfile() {
      this.profileDialogVisible = true;
      this.profileLoading = true;
      try {
        const res = await getClinicalProfile(this.checkForm.patient_id);
        const recorded = res.data?.recorded || {};
        this.profileDerived = res.data || {};
        this.profileForm = { pregnant: recorded.pregnant ?? null, egfr: recorded.egfr ?? null, hepatic_impairment: recorded.hepatic_impairment ?? 0 };
        this.profileDiagnoses = (recorded.diagnoses || []).join("\n");
        this.profileLabs = JSON.stringify(recorded.labs || {}, null, 2);
      } finally { this.profileLoading = false; }
    },
    async saveProfile() {
      this.profileSaving = true;
      try {
        const labs = JSON.parse(this.profileLabs || "{}");
        const diagnoses = this.profileDiagnoses.split("\n").map((item) => item.trim()).filter(Boolean);
        const res = await saveClinicalProfile(this.checkForm.patient_id, { ...this.profileForm, diagnoses, labs });
        if (res.code === 200) { ElMessage.success("临床档案已保存"); this.profileDialogVisible = false; }
      } catch (error) {
        ElMessage.error(error instanceof SyntaxError ? "关键检验必须是合法 JSON" : error.msg || "保存失败");
      } finally { this.profileSaving = false; }
    },
  },
};
</script>
