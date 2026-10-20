<template>
  <div class="app-container ai-management">
    <vab-page-header title="AI 管理中心" description="统一管理全院 AI 能力、模型、Prompt 版本、知识和访问授权" />
    <el-row :gutter="16" class="summary-row">
      <el-col v-for="item in summary" :key="item.label" :xs="12" :sm="6">
        <el-card shadow="never"><div class="summary-value">{{ item.value }}</div><div>{{ item.label }}</div></el-card>
      </el-col>
    </el-row>
    <el-card v-loading="loading">
      <el-tabs v-model="tab">
        <el-tab-pane label="能力与启用" name="features">
          <div class="page-toolbar">
            <el-input v-model="search" placeholder="搜索名称或功能编号" clearable class="page-search-input" />
            <el-select v-model="category" placeholder="全部分类" clearable style="width: 160px">
              <el-option v-for="(label, value) in categories" :key="value" :label="label" :value="value" />
            </el-select>
            <el-select v-model="setupFilter" aria-label="配置检查筛选" style="width: 170px"><el-option label="全部配置状态" value="all" /><el-option label="基础配置就绪" value="ready" /><el-option label="尚需补齐条件" value="pending" /></el-select>
            <el-button @click="refresh">刷新</el-button>
          </div>
          <el-table :data="pagedFeatures" empty-text="暂无能力配置">
            <el-table-column prop="number" label="编号" width="65" />
            <el-table-column prop="name" label="功能" min-width="190" />
            <el-table-column label="分类" width="115"><template #default="{ row }">{{ categories[row.category] }}</template></el-table-column>
            <el-table-column prop="priority" label="批次" width="70" />
            <el-table-column label="实现入口" width="150"><template #default="{ row }">{{ row.engine === 'llm' ? '文本任务网关' : '需专用适配器' }}</template></el-table-column>
            <el-table-column label="配置检查" width="145"><template #default="{ row }">
              <el-popover trigger="click" placement="left" :width="380" :title="row.name + '：配置检查'">
                <p v-for="item in row.setup_check?.issues || []" :key="item.code">{{ item.message }}</p>
                <p v-if="row.setup_check?.ready">基础配置已具备。</p><p class="setup-note">{{ row.setup_check?.scope_note || '实际执行仍按患者、科室、问题和资料范围重新核验。' }}</p>
                <template #reference><el-button link :type="row.setup_check?.ready ? 'success' : 'warning'" :aria-label="row.name + '配置检查'">{{ row.setup_check ? row.setup_check.ready ? '基础配置就绪' : '待补齐 ' + row.setup_check.issues.length + ' 项' : '待检查' }}</el-button></template>
              </el-popover>
            </template></el-table-column>
            <el-table-column label="验证状态" width="110"><template #default="{ row }"><el-tag :type="row.validation_status === 'validated' ? 'success' : 'info'">{{ validations[row.validation_status] }}</el-tag></template></el-table-column>
            <el-table-column label="启用" width="75"><template #default="{ row }"><el-tag :type="row.enabled ? 'success' : 'info'">{{ row.enabled ? '已启用' : '关闭' }}</el-tag></template></el-table-column>
            <el-table-column label="Prompt" width="85"><template #default="{ row }">v{{ row.prompt_version }}</template></el-table-column>
            <el-table-column label="操作" width="180" fixed="right"><template #default="{ row }"><el-button size="small" @click="editFeature(row)">配置</el-button><el-button size="small" @click="openPrompts(row)">Prompt</el-button></template></el-table-column>
          </el-table>
          <el-pagination v-model:current-page="page" :page-size="15" :total="filteredFeatures.length" layout="total, prev, pager, next" class="pagination-wrapper" />
        </el-tab-pane>

        <el-tab-pane label="模型服务" name="providers">
          <div class="page-toolbar"><el-button type="primary" @click="editProvider()">新增模型服务</el-button><span>模型地址、密钥和患者数据使用范围由超级管理员配置。</span></div>
          <el-table :data="providers" empty-text="尚未配置模型服务">
            <el-table-column prop="name" label="名称" /><el-table-column prop="model" label="模型标识" />
            <el-table-column label="类型"><template #default="{ row }">{{ row.kind === 'specialist' ? '专用适配器' : row.kind === 'responses' ? 'Responses API' : 'Chat Completions' }}</template></el-table-column>
            <el-table-column label="状态"><template #default="{ row }">{{ row.enabled ? '已启用' : '关闭' }}</template></el-table-column>
            <el-table-column label="密钥"><template #default="{ row }">{{ row.has_api_key ? '已配置，不回显' : '未配置' }}</template></el-table-column>
            <el-table-column label="患者资料"><template #default="{ row }">{{ row.allows_patient_data ? '已授权传输' : '禁止传输' }}</template></el-table-column>
            <el-table-column label="操作" width="90"><template #default="{ row }"><el-button size="small" @click="editProvider(row)">编辑</el-button></template></el-table-column>
          </el-table>
        </el-tab-pane>

        <el-tab-pane label="知识审核" name="knowledge">
          <div class="page-toolbar"><el-button type="primary" @click="openKnowledge">新增知识版本</el-button><span>新文档先保存草稿，审核发布后才参与检索。</span></div>
          <el-table :data="knowledge" empty-text="尚未录入知识">
            <el-table-column prop="title" label="标题" min-width="180" /><el-table-column prop="version" label="版本" width="100" />
            <el-table-column prop="source_uri" label="来源" min-width="180" show-overflow-tooltip />
            <el-table-column label="状态" width="90"><template #default="{ row }">{{ knowledgeStatuses[row.status] }}</template></el-table-column>
            <el-table-column label="操作" width="170"><template #default="{ row }"><el-button size="small" @click="inspectKnowledge(row)">查看与审核</el-button></template></el-table-column>
          </el-table>
        </el-tab-pane>

        <el-tab-pane label="患者访问授权" name="grants">
          <div class="page-toolbar"><el-button type="primary" @click="openGrant">新增限时授权</el-button><span>用于无法从现有诊疗关系确认的访问；授权不会扩大功能本身允许的角色。</span></div>
          <el-table :data="grants" empty-text="暂无显式授权">
            <el-table-column prop="user_id" label="用户ID" width="90" /><el-table-column prop="patient_id" label="患者ID" width="90" />
            <el-table-column label="范围" width="120"><template #default="{ row }">{{ categories[row.category] }}</template></el-table-column>
            <el-table-column prop="reason" label="用途" /><el-table-column prop="expires_at" label="到期时间" />
            <el-table-column label="状态" width="90"><template #default="{ row }">{{ row.revoked ? '已撤销' : new Date(row.expires_at + 'Z') <= new Date() ? '已到期' : '有效' }}</template></el-table-column>
            <el-table-column label="操作" width="85"><template #default="{ row }"><el-button v-if="!row.revoked" size="small" @click="revokeGrant(row)">撤销</el-button></template></el-table-column>
          </el-table>
        </el-tab-pane>

        <el-tab-pane label="配置审计" name="audit">
          <el-table :data="auditEvents" empty-text="暂无配置变更">
            <el-table-column prop="actor_id" label="操作者ID" width="100" /><el-table-column prop="action" label="操作" width="170" />
            <el-table-column prop="target" label="对象" width="200" /><el-table-column prop="create_time" label="时间" width="190" />
            <el-table-column label="变更摘要"><template #default="{ row }"><span class="break-text">{{ JSON.stringify(row.detail) }}</span></template></el-table-column>
          </el-table>
        </el-tab-pane>
        <el-tab-pane label="调用统计" name="usage">
          <el-table :data="usage" empty-text="暂无调用记录">
            <el-table-column label="功能"><template #default="{ row }">{{ featureName(row.feature_key) }}</template></el-table-column>
            <el-table-column prop="status" label="执行状态" /><el-table-column prop="count" label="次数" />
            <el-table-column prop="input_tokens" label="输入Token" /><el-table-column prop="output_tokens" label="输出Token" />
          </el-table>
        </el-tab-pane>
      </el-tabs>
    </el-card>

    <el-dialog v-model="featureDialog" :title="selectedFeature?.name + '：功能配置'" width="680px">
      <el-form v-if="selectedFeature" label-width="120px">
        <el-form-item v-if="selectedFeature.setup_check?.issues?.length" label="当前待补齐"><div><p v-for="item in selectedFeature.setup_check.issues" :key="item.code">{{ item.message }}</p></div></el-form-item>
        <el-form-item label="需要的资料"><span>{{ selectedFeature.inputs.join('、') }}</span></el-form-item>
        <el-form-item label="输出要求"><span>{{ selectedFeature.deliverables.join('；') }}</span></el-form-item>
        <el-form-item label="模型服务"><el-select v-model="featureForm.provider_id" clearable placeholder="选择已配置的服务"><el-option v-for="item in providers" :key="item.provider_id" :label="item.name" :value="item.provider_id" /></el-select></el-form-item>
        <el-form-item label="使用角色"><el-checkbox-group v-model="featureForm.allowed_roles"><el-checkbox v-for="role in selectedFeature.default_roles" :key="role" :value="role">{{ roles[role] || role }}</el-checkbox></el-checkbox-group></el-form-item>
        <el-form-item label="验证状态"><el-select v-model="featureForm.validation_status"><el-option v-for="(label, value) in validations" :key="value" :label="label" :value="value" /></el-select></el-form-item>
        <el-form-item label="验证记录"><el-input v-model="featureForm.validation_note" type="textarea" :rows="4" maxlength="5000" placeholder="记录适用范围、病例验证结果、负责人和依据；临床启用前需要完成验证" /></el-form-item>
        <el-form-item label="每日调用上限"><el-input-number v-model="featureForm.daily_limit" :min="1" :max="10000" /></el-form-item>
        <el-form-item label="面向业务启用"><el-switch v-model="featureForm.enabled" /></el-form-item>
      </el-form>
      <template #footer><el-button @click="featureDialog = false">取消</el-button><el-button type="primary" :loading="saving" @click="submitFeature">保存配置</el-button></template>
    </el-dialog>

    <el-dialog v-model="providerDialog" :title="providerId ? '编辑模型服务' : '新增模型服务'" width="700px" @closed="providerForm.api_key = ''">
      <el-form label-width="130px">
        <el-form-item label="服务名称"><el-input v-model="providerForm.name" maxlength="80" /></el-form-item>
        <el-form-item label="服务类型"><el-select v-model="providerForm.kind"><el-option label="Chat Completions 兼容接口" value="chat" /><el-option label="Responses API" value="responses" /><el-option label="专用模型适配器" value="specialist" /></el-select></el-form-item>
        <el-form-item label="API 基础地址"><el-input v-model="providerForm.api_base" placeholder="例如 http://localhost:11434/v1" /></el-form-item>
        <el-form-item label="模型标识"><el-input v-model="providerForm.model" placeholder="服务端实际提供的模型名称" /></el-form-item>
        <el-form-item label="API 密钥"><el-input v-model="providerForm.api_key" type="password" show-password autocomplete="new-password" placeholder="留空保留已保存密钥，保存后不回显" /></el-form-item>
        <el-form-item label="密钥环境变量"><el-input v-model="providerForm.api_key_env" placeholder="可选，填写部署环境中的变量名称" /></el-form-item>
        <el-form-item label="清除保存密钥"><el-checkbox v-model="providerForm.clear_api_key">清除加密保存的旧密钥</el-checkbox></el-form-item>
        <el-form-item label="患者资料传输"><el-switch v-model="providerForm.allows_patient_data" /><span class="field-hint">仅在该模型服务获授权处理患者资料时开启</span></el-form-item>
        <el-form-item label="超时秒数"><el-input-number v-model="providerForm.timeout_seconds" :min="3" :max="120" /></el-form-item>
        <el-form-item label="最大输出Token"><el-input-number v-model="providerForm.max_output_tokens" :min="256" :max="16000" /></el-form-item>
        <el-form-item label="生成温度"><el-input-number v-model="providerForm.temperature" :min="0" :max="1" :step="0.1" /></el-form-item>
        <template v-if="providerForm.kind === 'specialist'">
          <el-form-item label="适配功能"><el-select v-model="providerForm.supported_features" multiple filterable><el-option v-for="item in features.filter(f => f.engine !== 'llm')" :key="item.key" :label="item.name" :value="item.key" /></el-select></el-form-item>
          <el-form-item label="适配器验证报告"><el-input v-model="providerForm.validation_report" type="textarea" :rows="3" placeholder="登记模型版本、输入要求、适用范围和验证结果" /></el-form-item>
        </template>
        <el-form-item label="服务启用"><el-switch v-model="providerForm.enabled" /></el-form-item>
      </el-form>
      <el-alert type="info" :closable="false" title="服务主机需由部署配置 AI_PROVIDER_ALLOWED_HOSTS 允许；保存密钥需配置 AI_CREDENTIAL_KEY。更改模型会关闭其关联功能，等待重新评审启用。" />
      <template #footer><el-button @click="providerDialog = false">取消</el-button><el-button type="primary" :loading="saving" @click="submitProvider">保存服务</el-button></template>
    </el-dialog>

    <el-dialog v-model="promptDialog" :title="selectedFeature?.name + '：Prompt 版本'" width="850px">
      <el-form label-width="110px">
        <el-form-item label="历史版本"><el-select v-model="promptSelection" @change="selectPrompt"><el-option v-for="item in promptVersions" :key="item.prompt_id || 'baseline'" :label="'v' + item.version + ' · ' + item.change_note" :value="item.prompt_id || 'baseline'" /></el-select><el-button class="field-hint" @click="activateSelectedPrompt" :loading="saving">启用所选版本</el-button></el-form-item>
        <el-form-item label="任务 Prompt"><el-input v-model="taskPrompt" type="textarea" :rows="14" maxlength="20000" /></el-form-item>
        <el-form-item label="修改说明"><el-input v-model="promptChange" maxlength="1000" placeholder="说明本次修改目的和适用范围" /></el-form-item>
        <el-form-item label="保存后启用"><el-checkbox v-model="activateNewPrompt">启用后重新验证该功能</el-checkbox></el-form-item>
      </el-form>
      <el-collapse><el-collapse-item title="固定系统 Prompt（每次调用始终附加）"><pre class="prompt-text">{{ systemPrompt }}</pre></el-collapse-item></el-collapse>
      <template #footer><el-button @click="promptDialog = false">关闭</el-button><el-button type="primary" :disabled="taskPrompt.length < 30 || promptChange.length < 3" :loading="saving" @click="submitPrompt">保存为新版本</el-button></template>
    </el-dialog>

    <el-dialog v-model="knowledgeDialog" title="新增知识版本" width="760px">
      <el-form label-width="100px">
        <el-form-item label="标题"><el-input v-model="knowledgeForm.title" maxlength="200" /></el-form-item>
        <el-form-item label="版本"><el-input v-model="knowledgeForm.version" maxlength="80" /></el-form-item>
        <el-form-item label="来源"><el-input v-model="knowledgeForm.source_uri" placeholder="原始文件或官方地址；院内资料可填写 hospital://..." /></el-form-item>
        <el-form-item label="类别"><el-select v-model="knowledgeForm.category"><el-option label="临床规范" value="clinical" /><el-option label="药品资料" value="drug" /><el-option label="院内服务" value="hospital" /><el-option label="运维" value="operations" /><el-option label="模拟培训" value="training" /></el-select></el-form-item>
        <el-form-item label="适用功能"><el-select v-model="knowledgeForm.feature_keys" multiple filterable style="width: 100%"><el-option v-for="item in features" :key="item.key" :label="item.name" :value="item.key" /></el-select></el-form-item>
        <el-form-item label="科室ID"><el-input-number v-model="knowledgeForm.department_id" :min="1" /><span class="field-hint">可选，留空表示院内通用</span></el-form-item>
        <el-form-item label="生效时间"><el-date-picker v-model="knowledgeForm.effective_from" type="datetime" placeholder="可选" /></el-form-item>
        <el-form-item label="失效时间"><el-date-picker v-model="knowledgeForm.effective_to" type="datetime" placeholder="可选" /></el-form-item>
        <el-form-item label="正文"><el-input v-model="knowledgeForm.content" type="textarea" :rows="12" maxlength="200000" show-word-limit placeholder="保留章节、适用条件和原文出处，录入后审核发布" /></el-form-item>
      </el-form>
      <template #footer><el-button @click="knowledgeDialog = false">取消</el-button><el-button type="primary" :loading="saving" @click="submitKnowledge">保存草稿</el-button></template>
    </el-dialog>

    <el-dialog v-model="reviewDialog" :title="reviewDocument?.title + '：知识审核'" width="800px">
      <p>版本：{{ reviewDocument?.version }} · 状态：{{ knowledgeStatuses[reviewDocument?.status] }}</p>
      <pre class="prompt-text knowledge-text">{{ reviewDocument?.content }}</pre>
      <template #footer><el-button @click="reviewDialog = false">关闭</el-button><el-button v-if="reviewDocument?.status !== 'retired'" :loading="saving" @click="reviewDocumentAs('retired')">停用此版本</el-button><el-button v-if="reviewDocument?.status !== 'published'" type="primary" :loading="saving" @click="reviewDocumentAs('published')">确认审核并发布此版本</el-button></template>
    </el-dialog>

    <el-dialog v-model="grantDialog" title="新增限时患者访问授权" width="580px">
      <el-form label-width="110px">
        <el-form-item label="业务用户ID"><el-input-number v-model="grantForm.user_id" :min="1" /></el-form-item>
        <el-form-item label="患者ID"><el-input-number v-model="grantForm.patient_id" :min="1" /></el-form-item>
        <el-form-item label="功能范围"><el-select v-model="grantForm.category"><el-option v-for="(label, value) in categories" :key="value" :label="label" :value="value" /></el-select></el-form-item>
        <el-form-item label="授权用途"><el-input v-model="grantForm.reason" type="textarea" maxlength="500" /></el-form-item>
        <el-form-item label="到期时间"><el-date-picker v-model="grantForm.expires_at" type="datetime" /></el-form-item>
      </el-form>
      <template #footer><el-button @click="grantDialog = false">取消</el-button><el-button type="primary" :loading="saving" @click="submitGrant">保存授权</el-button></template>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, onMounted, ref, watch } from "vue";
import { ElMessage } from "element-plus";
import {
  activateAIPrompt, createAIKnowledge, createAIPatientGrant, createAIPrompt,
  getAIAdminFeatures, getAIAudit, getAIKnowledge, getAIKnowledgeDetail, getAIPatientGrants,
  getAIPrompts, getAIProviders, getAIUsage, reviewAIKnowledge, revokeAIPatientGrant,
  saveAIFeature, saveAIProvider,
} from "@/api/ai";

const categories = { cdss: "临床 CDSS", pharmacy: "用药与药房", records: "病历文书", diagnostics: "检验影像体检", inpatient: "住院护理急诊", patient: "患者服务", operations: "运营与收费", knowledge: "知识科研质控" };
const validations = { unreviewed: "未评审", pilot: "试点评估", validated: "已验证", suspended: "已暂停" };
const knowledgeStatuses = { draft: "草稿", published: "已发布", retired: "已停用" };
const roles = { super_admin: "超级管理员", admin: "管理员", doctor: "医生", director: "科室主任", pharmacist: "药师", nurse: "护士", patient: "患者", guide: "导诊员", lab_technician: "检验技师" };
const loading = ref(false), saving = ref(false), tab = ref("features");
const features = ref([]), providers = ref([]), knowledge = ref([]), grants = ref([]), auditEvents = ref([]), usage = ref([]);
const search = ref(""), category = ref(""), setupFilter = ref("all"), page = ref(1);
const summary = computed(() => [
  { label: "规划能力", value: features.value.length },
  { label: "已启用", value: features.value.filter(item => item.enabled).length },
  { label: "已验证", value: features.value.filter(item => item.validation_status === "validated").length },
  { label: "已启用模型服务", value: providers.value.filter(item => item.enabled).length },
]);
const filteredFeatures = computed(() => features.value.filter(item => (!category.value || item.category === category.value) && (setupFilter.value === "all" || (setupFilter.value === "ready" ? item.setup_check?.ready : !item.setup_check?.ready)) && `${item.number} ${item.name} ${item.key}`.toLowerCase().includes(search.value.toLowerCase())));
const pagedFeatures = computed(() => filteredFeatures.value.slice((page.value - 1) * 15, page.value * 15));
watch([search, category, setupFilter], () => { page.value = 1; });
const featureName = key => features.value.find(item => item.key === key)?.name || key;
const selectedFeature = ref(null), featureForm = ref({}), featureDialog = ref(false);
const providerDialog = ref(false), providerId = ref(null), providerForm = ref({});
const promptDialog = ref(false), promptVersions = ref([]), promptSelection = ref("baseline"), taskPrompt = ref(""), systemPrompt = ref(""), promptChange = ref(""), activateNewPrompt = ref(false);
const knowledgeDialog = ref(false), knowledgeForm = ref({}), reviewDialog = ref(false), reviewDocument = ref(null);
const grantDialog = ref(false), grantForm = ref({});

async function refresh() {
  loading.value = true;
  try {
    const results = await Promise.all([getAIAdminFeatures(), getAIProviders(), getAIKnowledge(), getAIPatientGrants(), getAIAudit(), getAIUsage()]);
    [features.value, providers.value, knowledge.value, grants.value, auditEvents.value, usage.value] = results.map(item => item.data || []);
    if (selectedFeature.value) selectedFeature.value = features.value.find(item => item.key === selectedFeature.value.key);
  } finally { loading.value = false; }
}

function editFeature(row) {
  selectedFeature.value = row;
  featureForm.value = { expected_revision: row.revision, provider_id: row.provider_id, allowed_roles: row.allowed_roles.filter(role => row.default_roles.includes(role)), enabled: row.enabled, validation_status: row.validation_status, validation_note: row.validation_note, daily_limit: row.daily_limit };
  featureDialog.value = true;
}

async function submitFeature() {
  saving.value = true;
  try { await saveAIFeature(selectedFeature.value.key, featureForm.value); featureDialog.value = false; await refresh(); ElMessage.success("功能配置已保存"); }
  finally { saving.value = false; }
}

function editProvider(row) {
  providerId.value = row?.provider_id || null;
  providerForm.value = {
    name: row?.name || "", kind: row?.kind || "chat", api_base: row?.api_base || "", model: row?.model || "",
    api_key: "", api_key_env: row?.api_key_env || "", clear_api_key: false,
    enabled: !!row?.enabled, allows_patient_data: !!row?.allows_patient_data,
    timeout_seconds: row?.timeout_seconds || 30, max_output_tokens: row?.max_output_tokens || 2000,
    temperature: Number(row?.temperature ?? 0.2), supported_features: [...(row?.supported_features || [])],
    validation_report: row?.validation_report || "", expected_revision: row?.revision || 0,
  };
  providerDialog.value = true;
}

async function submitProvider() {
  saving.value = true;
  try {
    await saveAIProvider(providerId.value, { ...providerForm.value, api_key: providerForm.value.api_key || null });
    providerForm.value.api_key = ""; providerDialog.value = false; await refresh(); ElMessage.success("模型服务已保存");
  } finally { saving.value = false; }
}

function selectPrompt(id) { taskPrompt.value = promptVersions.value.find(item => (item.prompt_id || "baseline") === id)?.task_prompt || ""; }
async function openPrompts(row) {
  selectedFeature.value = row;
  const result = await getAIPrompts(row.key);
  promptVersions.value = result.data.versions; systemPrompt.value = result.data.system_prompt;
  promptSelection.value = row.active_prompt_id || "baseline"; selectPrompt(promptSelection.value);
  promptChange.value = ""; activateNewPrompt.value = false; promptDialog.value = true;
}
async function submitPrompt() {
  saving.value = true;
  try {
    await createAIPrompt(selectedFeature.value.key, { expected_revision: selectedFeature.value.revision, task_prompt: taskPrompt.value, change_note: promptChange.value, activate: activateNewPrompt.value });
    await refresh(); await openPrompts(selectedFeature.value); ElMessage.success("新 Prompt 版本已保存");
  } finally { saving.value = false; }
}
async function activateSelectedPrompt() {
  saving.value = true;
  try {
    await activateAIPrompt(selectedFeature.value.key, { expected_revision: selectedFeature.value.revision, prompt_id: promptSelection.value === "baseline" ? null : promptSelection.value });
    await refresh(); ElMessage.success("已切换版本，功能等待重新验证启用");
  } finally { saving.value = false; }
}

function openKnowledge() {
  knowledgeForm.value = { title: "", version: "", source_uri: "", category: "clinical", content: "", feature_keys: [], department_id: null, effective_from: null, effective_to: null };
  knowledgeDialog.value = true;
}
const isoOrNull = value => value ? new Date(value).toISOString() : null;
async function submitKnowledge() {
  saving.value = true;
  try {
    await createAIKnowledge({ ...knowledgeForm.value, department_id: knowledgeForm.value.department_id || null, effective_from: isoOrNull(knowledgeForm.value.effective_from), effective_to: isoOrNull(knowledgeForm.value.effective_to) });
    knowledgeDialog.value = false; await refresh(); ElMessage.success("知识草稿已保存");
  } finally { saving.value = false; }
}
async function inspectKnowledge(row) { reviewDocument.value = (await getAIKnowledgeDetail(row.document_id)).data; reviewDialog.value = true; }
async function reviewDocumentAs(status) {
  saving.value = true;
  try { await reviewAIKnowledge(reviewDocument.value.document_id, { status, content_hash: reviewDocument.value.content_hash }); reviewDialog.value = false; await refresh(); ElMessage.success("知识状态已更新"); }
  finally { saving.value = false; }
}

function openGrant() { grantForm.value = { user_id: null, patient_id: null, category: "inpatient", reason: "", expires_at: new Date(Date.now() + 7 * 86400000) }; grantDialog.value = true; }
async function submitGrant() {
  saving.value = true;
  try { await createAIPatientGrant({ ...grantForm.value, expires_at: isoOrNull(grantForm.value.expires_at) }); grantDialog.value = false; await refresh(); ElMessage.success("限时授权已保存"); }
  finally { saving.value = false; }
}
async function revokeGrant(row) { await revokeAIPatientGrant(row.grant_id); await refresh(); }
onMounted(refresh);
</script>

<style scoped>
.summary-row { margin-bottom: 20px; }
.summary-row .el-col { margin-bottom: 12px; }
.summary-value { font-size: 30px; font-weight: 600; margin-bottom: 8px; }
.setup-note { font-size: 12px; color: var(--el-text-color-secondary); line-height: 1.6; }
.field-hint { margin-left: 12px; font-size: 12px; color: #606266; }
.prompt-text { white-space: pre-wrap; overflow-wrap: anywhere; line-height: 1.7; font-family: inherit; }
.knowledge-text { max-height: 55vh; overflow: auto; }
.break-text { overflow-wrap: anywhere; }
</style>
