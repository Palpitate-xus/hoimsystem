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
            <el-table-column label="操作" width="230"><template #default="{ row }"><el-button size="small" @click="editProvider(row)">编辑</el-button><el-button v-if="row.kind === 'specialist' && row.supported_features?.includes('medical_transcription')" size="small" @click="openSpeechCheck(row)">检查本地语音服务</el-button><el-button v-if="row.kind === 'specialist' && row.supported_features?.includes('ecg_analysis')" size="small" @click="openEcgCheck(row)">检查本地心电服务</el-button><el-button v-if="canCheckImage && row.kind === 'specialist' && row.supported_features?.includes('imaging_detection')" size="small" @click="openImageCheck(row)">检查本地影像服务</el-button><el-button v-if="canCheckForecast && row.kind === 'specialist' && row.supported_features?.includes('deterioration_risk')" size="small" @click="openNews2Check(row)">检查本地NEWS2服务</el-button><el-button v-if="canCheckForecast && row.kind === 'specialist' && row.supported_features?.includes('aki_risk')" size="small" @click="openAkiCheck(row)">检查本地AKI服务</el-button><el-button v-if="canCheckForecast && row.kind === 'specialist' && row.supported_features?.includes('sepsis_risk')" size="small" @click="openQsofaCheck(row)">检查本地qSOFA服务</el-button><el-button v-if="canCheckForecast && row.kind === 'specialist' && row.supported_features?.includes('sepsis_risk')" size="small" @click="openSofaCheck(row)">检查本地SOFA服务</el-button><el-button v-if="canCheckForecast&&row.kind==='specialist'&&row.supported_features?.includes('roster_optimization')" size="small" @click="openRosterCheck(row)">检查本地排班服务</el-button><el-button v-if="canCheckForecast&&row.kind==='specialist'&&row.supported_features?.includes('bed_forecast')" size="small" @click="openBedCheck(row)">检查本地床位服务</el-button><el-button v-if="canCheckForecast&&row.kind==='specialist'&&row.supported_features?.includes('surgery_scheduling')" size="small" @click="openSurgeryCheck(row)">检查本地手术排程服务</el-button><el-button v-if="canCheckForecast&&row.kind==='specialist'&&row.supported_features?.includes('supply_forecast')" size="small" @click="openSupplyCheck(row)">检查本地物资预测服务</el-button><el-button v-if="canCheckForecast&&row.kind==='specialist'&&row.supported_features?.includes('inventory_optimization')" size="small" @click="openInventoryCheck(row)">检查本地库存候选比较服务</el-button><el-button v-if="canCheckForecast && row.kind === 'specialist' && row.supported_features?.includes('visit_forecast')" size="small" @click="openForecastCheck(row)">检查本地统计服务</el-button></template></el-table-column>
          </el-table>
        </el-tab-pane>

        <el-tab-pane label="知识审核" name="knowledge">
          <div class="page-toolbar"><el-button type="primary" @click="openKnowledge">新增知识版本</el-button><el-button @click="openPathwayImport">从临床路径导入</el-button><span>新文档先保存草稿，审核发布后才参与检索。</span></div>
          <el-table :data="knowledge" empty-text="尚未录入知识">
            <el-table-column prop="title" label="标题" min-width="180" /><el-table-column prop="version" label="版本" width="100" />
            <el-table-column prop="source_uri" label="来源" min-width="180" show-overflow-tooltip />
            <el-table-column label="状态" width="90"><template #default="{ row }">{{ knowledgeStatuses[row.status] }}</template></el-table-column>
            <el-table-column label="原来源核对" min-width="150"><template #default="{ row }">{{ row.document_evidence_bound ? documentSourceStates[row.source_state] || '原文证据链待核对' : row.source_kind ? pathwaySourceStates[row.source_state] || '来源待核对' : '独立知识文档' }}</template></el-table-column>
            <el-table-column label="操作" width="170"><template #default="{ row }"><el-button size="small" @click="inspectKnowledge(row)">查看与审核</el-button></template></el-table-column>
          </el-table>
        </el-tab-pane>

        <el-tab-pane label="挂号预测来源" name="forecast_sources" lazy><ai-forecast-series-management v-if="tab === 'forecast_sources'" /></el-tab-pane>
        <el-tab-pane label="住院观测窗" name="observation_windows" lazy><ai-observation-window-management v-if="tab === 'observation_windows'" /></el-tab-pane>
        <el-tab-pane label="检验项目与来源" name="laboratory_mappings" lazy><ai-lab-mapping-management v-if="tab === 'laboratory_mappings'" /></el-tab-pane>
        <el-tab-pane label="风险规则与评估" name="risk_rules" lazy><ai-risk-rule-management v-if="tab === 'risk_rules'" /></el-tab-pane>
        <el-tab-pane label="受审排班计划治理" name="roster_plans" lazy><ai-roster-input v-if="tab==='roster_plans'" governance /></el-tab-pane>
        <el-tab-pane label="排班人员来源治理" name="roster_sources" lazy><ai-roster-sources v-if="tab==='roster_sources'" governance /></el-tab-pane>
        <el-tab-pane label="床位完整序列治理" name="bed_series" lazy><ai-bed-series v-if="tab==='bed_series'" governance /></el-tab-pane>
        <el-tab-pane label="床位原来源治理" name="bed_sources" lazy><ai-bed-sources v-if="tab==='bed_sources'" governance /></el-tab-pane>
        <el-tab-pane label="手术原资料与资源治理" name="surgery_sources" lazy><ai-surgery-sources v-if="tab==='surgery_sources'" governance /></el-tab-pane>
        <el-tab-pane label="物资原计量与每日原量治理" name="supply_sources" lazy><ai-supply-sources v-if="tab==='supply_sources'" governance /></el-tab-pane>
        <el-tab-pane label="完整物资原量序列治理" name="supply_series" lazy><ai-supply-series v-if="tab==='supply_series'" governance /></el-tab-pane>
        <el-tab-pane label="库存原观察与采购候选治理" name="inventory_sources" lazy><ai-inventory-sources v-if="tab==='inventory_sources'" audit-only /></el-tab-pane>
        <el-tab-pane label="完整库存候选场景治理" name="inventory_scenarios" lazy><ai-inventory-scenarios v-if="tab==='inventory_scenarios'" audit-only /></el-tab-pane>
        <el-tab-pane v-if="canCheckForecast" label="指南原文与摘录治理" name="document_evidence" lazy><document-evidence-panel v-if="tab==='document_evidence' && canCheckForecast" :active="tab==='document_evidence' && canCheckForecast" @knowledge-published="refresh" /></el-tab-pane>
        <el-tab-pane v-if="canManageDrugLabels" label="说明书原文与独立签署治理" name="drug_label_sources" lazy><template v-if="tab==='drug_label_sources'&&canManageDrugLabels"><el-checkbox v-model="drugLabelAuditOnly">明确只读冻结说明书来源</el-checkbox><drug-label-source-panel :key="String(drugLabelAuditOnly)" :active="tab==='drug_label_sources'&&canManageDrugLabels" :audit-only="drugLabelAuditOnly" /></template></el-tab-pane>
        <el-tab-pane v-if="canCheckForecast" label="病案编码证据与本地规则治理" name="coding_evidence" lazy><ai-coding-evidence-sources v-if="tab==='coding_evidence'&&canCheckForecast" audit-only /></el-tab-pane>
        <el-tab-pane v-if="canCheckForecast" label="完整住院账目来源治理" name="charge_sources" lazy><charge-reconciliation-source-panel v-if="tab==='charge_sources'&&canCheckForecast" :active="tab==='charge_sources'&&canCheckForecast" audit-only /></el-tab-pane>
        <el-tab-pane v-if="canCheckForecast" label="完整评价与人工摘录治理" name="satisfaction_sources" lazy><satisfaction-source-panel v-if="tab==='satisfaction_sources'&&canCheckForecast" :active="tab==='satisfaction_sources'&&canCheckForecast" audit-only /></el-tab-pane>
        <el-tab-pane label="完整手术排程场景治理" name="surgery_scenarios" lazy><ai-surgery-scenarios v-if="tab==='surgery_scenarios'" governance /></el-tab-pane>
        <el-tab-pane label="SOFA独立规则与全院评估" name="sofa" lazy><ai-sofa-management v-if="tab==='sofa'" /></el-tab-pane>
        <el-tab-pane label="器官支持来源与映射" name="organ_support" lazy><ai-organ-support-management v-if="tab === 'organ_support'" /></el-tab-pane>
        <el-tab-pane label="录音治理" name="audio"><ai-audio-management v-if="tab === 'audio'" /></el-tab-pane>
        <el-tab-pane label="影像原文件" name="images"><ai-image-management v-if="tab === 'images'" /></el-tab-pane>
        <el-tab-pane label="心电原文件" name="ecg"><ai-ecg-management v-if="tab === 'ecg'" /></el-tab-pane>

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
        <el-tab-pane label="任务与反馈" name="runs" lazy><ai-run-history :features="features" :active="tab === 'runs'" /></el-tab-pane>
        <el-tab-pane label="反馈脱敏审核" name="review_excerpts" lazy><ai-review-curation :active="tab === 'review_excerpts'" /></el-tab-pane>
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
        <el-form-item label="验证记录"><el-input v-model="featureForm.validation_note" type="textarea" :rows="4" maxlength="5000" :placeholder="selectedFeature.requires_operational_validation ? '记录实际科室、输入覆盖、离线回放与边界验证结果、负责人和依据；普通运营执行与启用前须完成验证' : '记录适用范围、病例验证结果、负责人和依据；临床启用前需要完成验证'" /></el-form-item>
        <el-form-item label="每日调用上限"><el-input-number v-model="featureForm.daily_limit" :min="1" :max="10000" /></el-form-item>
        <el-form-item label="面向业务启用"><el-switch v-model="featureForm.enabled" :disabled="selectedFeature.requires_operational_validation && !featureForm.enabled && featureForm.validation_status!=='validated'" /><p v-if="selectedFeature.requires_operational_validation">此运营能力须完成实际范围验证后才能面向业务启用和普通执行；管理员预览不代表本地验证、候选获批或实际排班已改变。</p></el-form-item>
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

    <AiForecastProviderCheck v-if="forecastCheckTarget" :target="forecastCheckTarget" :providers="providers" @close="forecastCheckTarget = null" @edit-model="editActualForecastModel" />
    <AiNews2ProviderCheck v-if="news2CheckTarget" :target="news2CheckTarget" :providers="providers" @close="news2CheckTarget = null" @edit-model="editActualNews2Model" />
    <AiAkiProviderCheck v-if="akiCheckTarget" :target="akiCheckTarget" :providers="providers" @close="akiCheckTarget = null" @edit-model="editActualAkiModel" />
    <AiRosterProviderCheck v-if="rosterCheckTarget" :target="rosterCheckTarget" :providers="providers" @close="rosterCheckTarget=null" @edit-model="editActualRosterModel" />
    <AiBedProviderCheck v-if="bedCheckTarget" :target="bedCheckTarget" :providers="providers" @close="bedCheckTarget=null" @edit-model="editActualBedModel" />
    <AiSupplyProviderCheck v-if="supplyCheckTarget" :target="supplyCheckTarget" :providers="providers" @close="supplyCheckTarget=null" @edit-model="editActualSupplyModel" />
    <AiInventoryProviderCheck v-if="inventoryCheckTarget" :target="inventoryCheckTarget" :providers="providers" @close="inventoryCheckTarget=null" @edit-model="editActualInventoryModel" />
    <AiSurgeryProviderCheck v-if="surgeryCheckTarget" :target="surgeryCheckTarget" :providers="providers" @close="surgeryCheckTarget=null" @edit-model="editActualSurgeryModel" />
    <AiSofaProviderCheck v-if="sofaCheckTarget" :target="sofaCheckTarget" :providers="providers" @close="sofaCheckTarget=null" @edit-model="editActualSofaModel" />
    <AiQsofaProviderCheck v-if="qsofaCheckTarget" :target="qsofaCheckTarget" :providers="providers" @close="qsofaCheckTarget = null" @edit-model="editActualQsofaModel" />

    <el-dialog v-model="speechCheckDialog" title="本地语音服务核对" width="760px">
      <div v-loading="speechCheckLoading">
        <p>核对已保存服务：{{ speechCheckName }}。检查不发送录音或患者资料，不创建模型任务。</p>
        <template v-if="speechCheckResult">
          <el-alert :type="speechCheckResult.compatible ? 'success' : 'warning'" :closable="false" :title="speechCheckResult.compatible ? '服务声明与登记配置匹配；仍须完成医疗场景验证' : '登记配置与服务声明存在差异'" />
          <p v-for="issue in speechCheckResult.issues" :key="issue">{{ issue }}</p>
          <el-descriptions :column="1" border>
            <el-descriptions-item label="实际模型标识"><span class="prompt-text">{{ speechCheckResult.capabilities.model_version }}</span></el-descriptions-item>
            <el-descriptions-item label="模型来源版本">{{ speechCheckResult.capabilities.model_repository }} · {{ speechCheckResult.capabilities.model_revision }}</el-descriptions-item>
            <el-descriptions-item label="处理范围">语言 {{ speechCheckResult.capabilities.language }}；最长 {{ speechCheckResult.capabilities.max_duration_seconds }} 秒；最大 {{ Math.floor(speechCheckResult.capabilities.max_bytes / 1048576) }} MiB</el-descriptions-item>
            <el-descriptions-item label="服务处理时限">{{ speechCheckResult.capabilities.timeout_seconds }} 秒，模型请求超时需另留传输时间</el-descriptions-item>
          </el-descriptions>
          <p>本地声学识别只转写原音，未区分说话人。修改任务Prompt不会让识别器补写未听到的内容；专科术语和医疗质量须另行验证。</p>
          <p>{{ speechCheckResult.scope_note }}</p>
        </template>
      </div>
      <template #footer><el-button @click="speechCheckDialog = false">关闭</el-button><el-button v-if="speechCheckResult && speechCheckResult.configured_model !== speechCheckResult.capabilities.model_version" @click="editActualSpeechModel">填写实际模型，待保存</el-button></template>
    </el-dialog>

    <el-dialog v-model="ecgCheckDialog" title="本地心电服务核对" width="800px">
      <div v-loading="ecgCheckLoading">
        <p>核对已保存服务：{{ ecgCheckName }}。检查只获取服务声明，不发送心电波形或患者资料，不创建模型任务。</p>
        <template v-if="ecgCheckResult">
          <el-alert :type="ecgCheckResult.compatible ? 'success' : 'warning'" :closable="false" :title="ecgCheckResult.compatible ? '服务声明与登记配置匹配；临床质量仍待验证' : '登记配置与服务声明存在差异'" />
          <p v-for="issue in ecgCheckResult.issues" :key="issue">{{ issue }}</p>
          <el-descriptions :column="1" border>
            <el-descriptions-item label="实际模型标识"><span class="prompt-text">{{ ecgCheckResult.capabilities.model_version }}</span></el-descriptions-item>
            <el-descriptions-item label="模型来源版本">{{ ecgCheckResult.capabilities.model_repository }} · {{ ecgCheckResult.capabilities.model_revision }}</el-descriptions-item>
            <el-descriptions-item label="运行引擎">{{ ecgCheckResult.capabilities.engine }}；<span v-for="(version, engine) in ecgCheckResult.capabilities.engine_versions" :key="engine">{{ engine }} {{ version }} </span></el-descriptions-item>
            <el-descriptions-item label="协议">v{{ ecgCheckResult.capabilities.schema_version }} · {{ ecgCheckResult.capabilities.feature_key }}</el-descriptions-item>
            <el-descriptions-item label="要求的原始导联">{{ ecgCheckResult.capabilities.required_leads.join('、') }}</el-descriptions-item>
            <el-descriptions-item label="采样与时长">{{ ecgCheckResult.capabilities.sample_rate_hz }} Hz；每导联 {{ ecgCheckResult.capabilities.samples_per_lead }} 个样本，{{ ecgCheckResult.capabilities.samples_per_lead / ecgCheckResult.capabilities.sample_rate_hz }} 秒</el-descriptions-item>
            <el-descriptions-item label="模型训练标签">{{ ecgCheckResult.capabilities.labels.join('、') }}</el-descriptions-item>
            <el-descriptions-item label="缺失样本策略">{{ ecgCheckResult.capabilities.missing_sample_policy }}（拒绝含缺失样本的输入）</el-descriptions-item>
            <el-descriptions-item label="Prompt 处理方式">{{ ecgCheckResult.capabilities.prompt_handling }}：仅对真实信号分类。Prompt 不参与信号推断，不能补造缺失导联、波形或临床信息。</el-descriptions-item>
            <el-descriptions-item label="请求限制">最大 {{ Math.floor(ecgCheckResult.capabilities.max_bytes / 1048576) }} MiB；服务处理时限 {{ ecgCheckResult.capabilities.timeout_seconds }} 秒，模型请求超时需另留传输时间</el-descriptions-item>
            <el-descriptions-item label="模型文件摘要"><span class="prompt-text">{{ ecgCheckResult.capabilities.model_digest }}</span></el-descriptions-item>
            <el-descriptions-item label="运行环境摘要"><span class="prompt-text">{{ ecgCheckResult.capabilities.runtime_digest }}</span></el-descriptions-item>
            <el-descriptions-item label="预处理摘要"><span class="prompt-text">{{ ecgCheckResult.capabilities.preprocessing_digest }}</span></el-descriptions-item>
            <el-descriptions-item label="临床验证声明">{{ ecgCheckResult.capabilities.clinical_validation }}（未提供临床验证）</el-descriptions-item>
          </el-descriptions>
          <p>来源模型和格式匹配不代表临床准确性。填写模型标识仅更新待保存表单，仍需另行保存、评审及配置启用。</p>
          <p>{{ ecgCheckResult.scope_note }}</p>
        </template>
      </div>
      <template #footer><el-button @click="ecgCheckDialog = false">关闭</el-button><el-button v-if="ecgCheckResult && ecgCheckResult.configured_model !== ecgCheckResult.capabilities.model_version" @click="editActualEcgModel">填写实际模型，待保存</el-button></template>
    </el-dialog>

    <el-dialog v-model="imageCheckDialog" title="本地影像服务核对" width="min(900px, 95vw)">
      <div v-loading="imageCheckLoading">
        <p>核对已保存服务：{{ imageCheckName }}。检查只读取服务能力声明，不发送患者资料或原始像素，不创建模型任务。</p>
        <template v-if="imageCheckResult">
          <el-alert :type="imageCheckResult.compatible ? 'success' : 'warning'" :closable="false" :title="imageCheckResult.compatible ? '服务声明与登记配置匹配；临床质量仍待验证' : '登记配置与服务声明存在差异'" />
          <p v-for="issue in imageCheckResult.issues || []" :key="issue">{{ issue }}</p>
          <el-descriptions :column="1" border>
            <el-descriptions-item label="实际模型标识"><span class="prompt-text">{{ imageCheckResult.capabilities.model_version }}</span></el-descriptions-item>
            <el-descriptions-item label="模型来源版本">{{ imageCheckResult.capabilities.model_repository }} · {{ imageCheckResult.capabilities.model_revision }}</el-descriptions-item>
            <el-descriptions-item label="运行引擎">{{ imageCheckResult.capabilities.engine }}；<span v-for="(version, engine) in imageCheckResult.capabilities.engine_versions" :key="engine">{{ engine }} {{ version }} </span></el-descriptions-item>
            <el-descriptions-item label="协议">v{{ imageCheckResult.capabilities.schema_version }} · {{ imageCheckResult.capabilities.feature_key }}</el-descriptions-item>
            <el-descriptions-item label="研究预处理配置">{{ imageCheckResult.capabilities.profile }}</el-descriptions-item>
            <el-descriptions-item label="模型原始标签">{{ imageCheckResult.capabilities.labels?.join('、') }}</el-descriptions-item>
            <el-descriptions-item label="输入范围"><pre class="prompt-text">{{ JSON.stringify(imageCheckResult.capabilities.preprocessing?.input_profile || {}, null, 2) }}</pre></el-descriptions-item>
            <el-descriptions-item label="实际预处理声明"><pre class="prompt-text">{{ JSON.stringify(imageCheckResult.capabilities.preprocessing || {}, null, 2) }}</pre></el-descriptions-item>
            <el-descriptions-item label="Prompt 处理方式">{{ imageCheckResult.capabilities.prompt_handling }}：仅原始像素参与分类；Prompt 不改变固定分类算法，不补造影像或临床信息。</el-descriptions-item>
            <el-descriptions-item label="请求限制">最大 {{ Math.floor(imageCheckResult.capabilities.max_bytes / 1048576) }} MiB；服务时限 {{ imageCheckResult.capabilities.timeout_seconds }} 秒，模型请求超时需另留传输时间。</el-descriptions-item>
            <el-descriptions-item label="模型文件摘要"><span class="prompt-text">{{ imageCheckResult.capabilities.model_digest }}</span></el-descriptions-item>
            <el-descriptions-item label="运行环境摘要"><span class="prompt-text">{{ imageCheckResult.capabilities.runtime_digest }}</span></el-descriptions-item>
            <el-descriptions-item label="预处理摘要"><span class="prompt-text">{{ imageCheckResult.capabilities.preprocessing_digest }}</span></el-descriptions-item>
            <el-descriptions-item label="人群适用性">{{ imageCheckResult.capabilities.population_applicability }}：未核实采集时人群与模型适用性。</el-descriptions-item>
            <el-descriptions-item label="临床验证">{{ imageCheckResult.capabilities.clinical_validation }}：未提供临床验证。</el-descriptions-item>
          </el-descriptions>
          <p>研究配置按原 BitsStored 可表示范围归一化，MONOCHROME1 只反转一次，再按原作者中心方形裁剪并缩放为224×224（双线性、抗锯齿）。不应用DICOM VOI显示窗、不自动minmax或旋转；不声称与原训练数据预处理等价。</p>
          <p>该流程与原图查看器的DICOM显示窗分别保留。模型只提供单图分类原始分数，不提供病灶框或完整序列判断；分数不是患病概率。</p>
          <p>填写实际模型仅更新待保存表单；保存服务、启用功能及临床评审仍须分别明确操作。</p>
          <p>{{ imageCheckResult.scope_note }}</p>
        </template>
      </div>
      <template #footer><el-button @click="imageCheckDialog = false">关闭</el-button><el-button v-if="canCheckImage && imageCheckResult && imageCheckResult.configured_model !== imageCheckResult.capabilities.model_version" @click="editActualImageModel">填写实际模型，待保存</el-button></template>
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

    <el-dialog v-model="pathwayImportDialog" title="导入临床路径待审核快照" width="760px">
      <div v-loading="pathwaySourcesLoading">
        <p>从原路径生成独立版本，保留适用条件、排除条件和完整步骤。保存后须检查全文并审核发布；原路径修改或停用后，旧快照不再用于生成。</p>
        <el-form label-width="110px">
          <el-form-item label="原临床路径"><el-select v-model="pathwayImportForm.pathway_id" filterable clearable placeholder="选择可导入的原路径" style="width: 100%" aria-label="待导入临床路径"><el-option v-for="item in pathwaySources.items || []" :key="item.pathway_id" :value="item.pathway_id" :disabled="!item.importable" :label="`${item.name} · #${item.pathway_id}${item.importable ? '' : ' · ' + item.issues.join('；')}`" /></el-select></el-form-item>
          <p v-if="selectedPathwaySource">原病种：{{ selectedPathwaySource.disease_name || '未记录' }} · 原编码：{{ selectedPathwaySource.disease_code || '未记录' }} · 预计天数：{{ selectedPathwaySource.expected_days ?? '未记录' }}（不作个体出院目标）</p>
          <el-form-item label="适用AI功能"><el-select v-model="pathwayImportForm.feature_keys" multiple filterable style="width: 100%" aria-label="路径知识适用功能"><el-option v-for="item in features" :key="item.key" :value="item.key" :label="item.name" /></el-select></el-form-item>
          <el-form-item label="适用科室ID"><el-input-number v-model="pathwayImportForm.department_id" :min="1" /><span class="field-hint">可选；留空表示院内通用，仍须审核适用条件</span></el-form-item>
          <el-form-item label="生效时间"><el-date-picker v-model="pathwayImportForm.effective_from" type="datetime" placeholder="可选" /></el-form-item>
          <el-form-item label="失效时间"><el-date-picker v-model="pathwayImportForm.effective_to" type="datetime" placeholder="可选" /></el-form-item>
        </el-form>
        <p v-if="pathwaySources.truncated">仅显示最近300项原路径，当前目录已截断。</p>
      </div>
      <template #footer><el-button @click="pathwayImportDialog = false">取消</el-button><el-button :loading="pathwaySourcesLoading" @click="loadPathwaySources">刷新来源</el-button><el-button type="primary" :loading="saving" :disabled="pathwaySourcesLoading || !selectedPathwaySource?.importable || !pathwayImportForm.feature_keys?.length" @click="submitPathwayImport">保存待审核快照</el-button></template>
    </el-dialog>

    <el-dialog v-model="reviewDialog" :title="(reviewDocument?.title || '文档') + '：知识审核'" width="800px">
      <p>版本：{{ reviewDocument?.version }} · 状态：{{ knowledgeStatuses[reviewDocument?.status] }}</p>
      <p v-if="reviewDocument?.document_evidence_bound">原文证据：{{ documentSourceStates[reviewDocument.source_state] || '原文证据链待核对' }}。发布和撤销须在“指南原文与摘录治理”中核对原件、条款和审核版本。</p>
      <p v-else-if="reviewDocument?.source_kind">原路径 #{{ reviewDocument.source_reference_id }}：{{ pathwaySourceStates[reviewDocument.source_state] || '来源待核对' }}。审核时须核对完整纳入、排除条件和步骤依据。</p>
      <pre class="prompt-text knowledge-text">{{ reviewDocument?.content }}</pre>
      <p v-if="!reviewDocument?.document_evidence_bound && reviewDocument?.source_kind && !canPublishDocument && reviewDocument.status !== 'published'">来源失效或版本已停用，须重新导入当前原路径后审核。</p>
      <template #footer><el-button @click="reviewDialog = false">关闭</el-button><el-button v-if="reviewDocument?.document_evidence_bound && canCheckForecast" @click="reviewDialog=false; tab='document_evidence'">核对原文证据链</el-button><el-button v-if="!reviewDocument?.document_evidence_bound && reviewDocument?.status !== 'retired'" :loading="saving" @click="reviewDocumentAs('retired')">停用此版本</el-button><el-button v-if="!reviewDocument?.document_evidence_bound && reviewDocument?.status !== 'published'" type="primary" :disabled="!canPublishDocument" :loading="saving" @click="reviewDocumentAs('published')">确认审核并发布此版本</el-button></template>
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
import { computed, defineAsyncComponent, onMounted, onBeforeUnmount, onDeactivated, ref, watch } from "vue";
import { ElMessage } from "element-plus";
import store from "@/store";
import AiRunHistory from "@/components/AIRunHistory/index.vue";
import AiReviewCuration from "@/components/AIReviewCuration/index.vue";
import AiAudioManagement from "@/components/AIAudioManagement/index.vue";
import AiImageManagement from "@/components/AIImageManagement/index.vue";
import AiEcgManagement from "@/components/AIEcgManagement/index.vue";
const AiForecastSeriesManagement = defineAsyncComponent(() => import("@/components/AIForecastSeriesManagement.vue"));
const AiObservationWindowManagement = defineAsyncComponent(() => import("@/views/system/AIObservationWindowManagement.vue"));
const AiLabMappingManagement = defineAsyncComponent(() => import("@/views/system/AILabMappingManagement.vue"));
const AiForecastProviderCheck = defineAsyncComponent(() => import("@/components/AIForecastProviderCheck/index.vue"));
const AiNews2ProviderCheck = defineAsyncComponent(() => import("@/components/AINews2ProviderCheck/index.vue"));
const AiAkiProviderCheck = defineAsyncComponent(() => import("@/components/AIAkiProviderCheck/index.vue"));
const AiRosterInput=defineAsyncComponent(()=>import("@/components/AIRosterInput/index.vue"));
const AiRosterProviderCheck=defineAsyncComponent(()=>import("@/components/AIRosterProviderCheck/index.vue"));
const AiRosterSources=defineAsyncComponent(()=>import("@/components/AIRosterSources/index.vue"));
const AiBedSeries=defineAsyncComponent(()=>import("@/components/AIBedSeries/index.vue"));
const AiBedSources=defineAsyncComponent(()=>import("@/components/AIBedSources/index.vue"));
const AiBedProviderCheck=defineAsyncComponent(()=>import("@/components/AIBedProviderCheck/index.vue"));
const AiSupplySources=defineAsyncComponent(()=>import("@/components/SupplySourcesPanel.vue"));
const AiSupplySeries=defineAsyncComponent(()=>import("@/components/SupplySeriesPanel.vue"));
const AiSupplyProviderCheck=defineAsyncComponent(()=>import("@/components/SupplyProviderCapabilityCheck.vue"));
const AiInventoryProviderCheck=defineAsyncComponent(()=>import("@/components/InventoryProviderCapabilityCheck.vue"));
const AiInventorySources=defineAsyncComponent(()=>import("@/components/InventorySources.vue"));
const AiInventoryScenarios=defineAsyncComponent(()=>import("@/components/InventoryScenarios.vue"));
const DocumentEvidencePanel=defineAsyncComponent(()=>import("@/components/ai/DocumentEvidencePanel.vue"));
const DrugLabelSourcePanel=defineAsyncComponent(()=>import("@/components/ai/DrugLabelSources.vue"));
const drugLabelAuditOnly=ref(false);
const canManageDrugLabels=computed(()=>typeof store.state.user.accessToken==='string'&&store.state.user.accessToken.length>0&&Array.isArray(store.state.user.permissions)&&store.state.user.permissions.includes('super_admin'));
watch([()=>store.state.user.accessToken,()=>JSON.stringify(store.state.user.permissions)],()=>{drugLabelAuditOnly.value=false;},{flush:'sync'});
const AiCodingEvidenceSources=defineAsyncComponent(()=>import("@/components/CodingEvidenceSources.vue"));
const ChargeReconciliationSourcePanel=defineAsyncComponent(()=>import("@/components/ai/ChargeReconciliationSourcePanel.vue"));
const SatisfactionSourcePanel=defineAsyncComponent(()=>import("@/components/ai/SatisfactionSourcePanel.vue"));
const AiSurgerySources=defineAsyncComponent(()=>import("@/components/AISurgerySources.vue"));
const AiSurgeryScenarios=defineAsyncComponent(()=>import("@/components/AISurgeryScenarios.vue"));
const AiSurgeryProviderCheck=defineAsyncComponent(()=>import("@/components/AISurgeryProviderCheck.vue"));
const AiSofaManagement=defineAsyncComponent(()=>import("@/components/AISofaManagement/index.vue"));
const AiSofaProviderCheck=defineAsyncComponent(()=>import("@/components/AISofaProviderCheck/index.vue"));
const AiQsofaProviderCheck = defineAsyncComponent(() => import("@/components/AIQsofaProviderCheck/index.vue"));
const AiOrganSupportManagement = defineAsyncComponent(() => import("./AIOrganSupportManagement.vue"));
const AiRiskRuleManagement = defineAsyncComponent(() => import("@/views/system/AIRiskRuleManagement.vue"));
import {
  activateAIPrompt, createAIKnowledge, createAIPatientGrant, createAIPrompt,
  getAIAdminFeatures, getAIAudit, getAIKnowledge, getAIKnowledgeDetail, getAIPatientGrants, getAIPathwaySources, importAIPathway,
  getAIPrompts, getAIProviders, getAIUsage, reviewAIKnowledge, revokeAIPatientGrant,
  saveAIFeature, saveAIProvider, checkAISpeechProvider, checkAIEcgProvider, checkAIImageProvider,
} from "@/api/ai";

const categories = { cdss: "临床 CDSS", pharmacy: "用药与药房", records: "病历文书", diagnostics: "检验影像体检", inpatient: "住院护理急诊", patient: "患者服务", operations: "运营与收费", knowledge: "知识科研质控" };
const validations = { unreviewed: "未评审", pilot: "试点评估", validated: "已验证", suspended: "已暂停" };
const knowledgeStatuses = { draft: "草稿", published: "已发布", retired: "已停用" };
const pathwaySourceStates = { current: "与当前原路径一致", changed: "原路径已变更，须重新导入", disabled: "原路径已停用", missing: "原路径不存在", invalid_link: "来源关联异常" };
const documentSourceStates = { current: "当前原文、摘录及审核版本一致", original_not_current: "原文或原审核版本失效", candidate_not_approved: "条款候选审核失效", publication_revoked: "原文发布件已撤销", knowledge_not_published: "知识版本已停用", knowledge_changed: "知识内容或元数据已改变", invalid_binding: "完整原文证据链核对失败" };
const roles = { super_admin: "超级管理员", admin: "管理员", doctor: "医生", director: "科室主任", pharmacist: "药师", nurse: "护士", patient: "患者", guide: "导诊员", lab_technician: "检验技师", cashier: "收费员" };
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
const forecastCheckTarget = ref(null);
const news2CheckTarget = ref(null);
const canCheckForecast = computed(() => !!store.state.user.accessToken && store.state.user.permissions.includes("super_admin"));
function openNews2Check(row) {
  if (!canCheckForecast.value) return;
  news2CheckTarget.value = { provider_id: row.provider_id, revision: row.revision, model: row.model, name: row.name, session: store.state.user.accessToken };
}
function editActualNews2Model(result) {
  const row = providers.value.find(item => item.provider_id === result.provider_id && item.revision === result.revision && item.model === result.configured_model && item.kind === "specialist" && item.supported_features?.includes("deterioration_risk"));
  if (!canCheckForecast.value || result.session !== store.state.user.accessToken || !row || !/^news2:[a-f0-9]{64}$/.test(result.model || "")) { ElMessage.warning("NEWS2服务配置或管理会话已变化，请重新核对"); return; }
  editProvider(row); providerForm.value.model = result.model;
}
const akiCheckTarget = ref(null);
function openAkiCheck(row) {
  if (!canCheckForecast.value) return;
  akiCheckTarget.value = { provider_id: row.provider_id, revision: row.revision, model: row.model, name: row.name, session: store.state.user.accessToken };
}
function editActualAkiModel(result) {
  const row = providers.value.find(item => item.provider_id === result.provider_id && item.revision === result.revision && item.model === result.configured_model && item.kind === "specialist" && item.supported_features?.includes("aki_risk"));
  if (!canCheckForecast.value || result.session !== store.state.user.accessToken || !row || !/^aki:[a-f0-9]{64}$/.test(result.model || "")) { ElMessage.warning("KDIGO AKI服务配置或管理会话已变化，请重新核对"); return; }
  editProvider(row); providerForm.value.model = result.model;
}
const inventoryCheckTarget=ref(null);
function openInventoryCheck(row){if(canCheckForecast.value)inventoryCheckTarget.value={provider_id:row.provider_id,revision:row.revision,model:row.model,name:row.name,session:store.state.user.accessToken,username:store.state.user.username};}
function editActualInventoryModel(result){const row=providers.value.find(item=>item.provider_id===result.provider_id&&item.revision===result.revision&&item.model===result.configured_model&&item.kind==='specialist'&&item.supported_features?.includes('inventory_optimization'));if(!canCheckForecast.value||result.session!==store.state.user.accessToken||result.username!==store.state.user.username||!row||!/^inventory:[a-f0-9]{64}$/.test(result.model||'')){ElMessage.warning('库存候选比较配置或管理身份已变化，请重新核对');return;}editProvider(row);providerForm.value.model=result.model;}
watch(()=>JSON.stringify([store.state.user.accessToken,store.state.user.username,store.state.user.permissions]),()=>{inventoryCheckTarget.value=null;},{flush:'sync'});
onDeactivated(()=>{inventoryCheckTarget.value=null;});onBeforeUnmount(()=>{inventoryCheckTarget.value=null;});
const supplyCheckTarget=ref(null);
function openSupplyCheck(row){if(canCheckForecast.value)supplyCheckTarget.value={provider_id:row.provider_id,revision:row.revision,model:row.model,name:row.name,session:store.state.user.accessToken};}
function editActualSupplyModel(result){const row=providers.value.find(item=>item.provider_id===result.provider_id&&item.revision===result.revision&&item.model===result.configured_model&&item.kind==='specialist'&&item.supported_features?.includes('supply_forecast'));if(!canCheckForecast.value||result.session!==store.state.user.accessToken||!row||!/^supply:[a-f0-9]{64}$/.test(result.model||'')){ElMessage.warning('物资预测配置或管理会话已变化，请重新核对');return;}editProvider(row);providerForm.value.model=result.model;}
const surgeryCheckTarget=ref(null);
function openSurgeryCheck(row){if(canCheckForecast.value)surgeryCheckTarget.value={provider_id:row.provider_id,revision:row.revision,model:row.model,name:row.name,session:store.state.user.accessToken};}
function editActualSurgeryModel(result){const row=providers.value.find(item=>item.provider_id===result.provider_id&&item.revision===result.revision&&item.model===result.configured_model&&item.kind==='specialist'&&item.supported_features?.includes('surgery_scheduling'));if(!canCheckForecast.value||result.session!==store.state.user.accessToken||!row||!/^surgery:[a-f0-9]{64}$/.test(result.model||'')){ElMessage.warning('手术排程服务配置或管理会话已变化，请重新核对');return;}editProvider(row);providerForm.value.model=result.model;}
const bedCheckTarget=ref(null);
function openBedCheck(row){if(canCheckForecast.value)bedCheckTarget.value={provider_id:row.provider_id,revision:row.revision,model:row.model,name:row.name,session:store.state.user.accessToken};}
function editActualBedModel(result){const row=providers.value.find(item=>item.provider_id===result.provider_id&&item.revision===result.revision&&item.model===result.configured_model&&item.kind==='specialist'&&item.supported_features?.includes('bed_forecast'));if(!canCheckForecast.value||result.session!==store.state.user.accessToken||!row||!/^bed:[a-f0-9]{64}$/.test(result.model||'')){ElMessage.warning('床位服务配置或管理会话已变化，请重新核对');return;}editProvider(row);providerForm.value.model=result.model;}
const rosterCheckTarget=ref(null);
function openRosterCheck(row){if(canCheckForecast.value)rosterCheckTarget.value={provider_id:row.provider_id,revision:row.revision,model:row.model,name:row.name,session:store.state.user.accessToken};}
function editActualRosterModel(result){const row=providers.value.find(item=>item.provider_id===result.provider_id&&item.revision===result.revision&&item.model===result.configured_model&&item.kind==='specialist'&&item.supported_features?.includes('roster_optimization'));if(!canCheckForecast.value||result.session!==store.state.user.accessToken||!row||!/^roster:[a-f0-9]{64}$/.test(result.model||'')){ElMessage.warning('排班服务配置或管理会话已变化，请重新核对');return;}editProvider(row);providerForm.value.model=result.model;}
const sofaCheckTarget=ref(null);
function openSofaCheck(row){if(canCheckForecast.value)sofaCheckTarget.value={provider_id:row.provider_id,revision:row.revision,model:row.model,name:row.name,session:store.state.user.accessToken};}
function editActualSofaModel(result){const row=providers.value.find(item=>item.provider_id===result.provider_id&&item.revision===result.revision&&item.model===result.configured_model&&item.kind==="specialist"&&item.supported_features?.includes("sepsis_risk"));if(!canCheckForecast.value||result.session!==store.state.user.accessToken||!row||!/^sofa1:[a-f0-9]{64}$/.test(result.model||"")){ElMessage.warning("SOFA服务配置或管理会话已变化，请重新核对");return;}editProvider(row);providerForm.value.model=result.model;}
const qsofaCheckTarget = ref(null);
function openQsofaCheck(row) {
  if (!canCheckForecast.value) return;
  qsofaCheckTarget.value = { provider_id: row.provider_id, revision: row.revision, model: row.model, name: row.name, session: store.state.user.accessToken };
}
function editActualQsofaModel(result) {
  const row = providers.value.find(item => item.provider_id === result.provider_id && item.revision === result.revision && item.model === result.configured_model && item.kind === "specialist" && item.supported_features?.includes("sepsis_risk"));
  if (!canCheckForecast.value || result.session !== store.state.user.accessToken || !row || !/^qsofa:[a-f0-9]{64}$/.test(result.model || "")) { ElMessage.warning("qSOFA服务配置或管理会话已变化，请重新核对"); return; }
  editProvider(row); providerForm.value.model = result.model;
}
watch([() => store.state.user.accessToken, () => JSON.stringify(store.state.user.permissions)], () => { news2CheckTarget.value = null; akiCheckTarget.value = null; qsofaCheckTarget.value = null;sofaCheckTarget.value=null;rosterCheckTarget.value=null;bedCheckTarget.value=null;surgeryCheckTarget.value=null;supplyCheckTarget.value=null; });
onDeactivated(() => { news2CheckTarget.value = null; akiCheckTarget.value = null; qsofaCheckTarget.value = null;sofaCheckTarget.value=null;rosterCheckTarget.value=null;bedCheckTarget.value=null;surgeryCheckTarget.value=null;supplyCheckTarget.value=null; });
onBeforeUnmount(() => { news2CheckTarget.value = null; akiCheckTarget.value = null; qsofaCheckTarget.value = null;sofaCheckTarget.value=null;rosterCheckTarget.value=null;bedCheckTarget.value=null;surgeryCheckTarget.value=null;supplyCheckTarget.value=null; });
watch([() => store.state.user.accessToken, () => JSON.stringify(store.state.user.permissions)], () => { forecastCheckTarget.value = null; });
onDeactivated(() => { forecastCheckTarget.value = null; });
onBeforeUnmount(() => { forecastCheckTarget.value = null; });
function openForecastCheck(row) {
  if (!canCheckForecast.value) return;
  forecastCheckTarget.value = { provider_id: row.provider_id, revision: row.revision, model: row.model, name: row.name, session: store.state.user.accessToken };
}
function editActualForecastModel(result) {
  const row = providers.value.find(item => item.provider_id === result.provider_id && item.revision === result.revision && item.model === result.configured_model && item.kind === "specialist" && item.supported_features?.includes("visit_forecast"));
  if (!canCheckForecast.value || result.session !== store.state.user.accessToken || !row) { ElMessage.warning("统计服务配置或管理会话已变化，请重新核对"); return; }
  editProvider(row); providerForm.value.model = result.model;
}
const speechCheckDialog = ref(false), speechCheckLoading = ref(false), speechCheckResult = ref(null), speechCheckName = ref("");
let speechCheckRequest = 0;
watch(speechCheckDialog, visible => { if (!visible) speechCheckRequest += 1; });
onBeforeUnmount(() => { speechCheckRequest += 1; });
const ecgCheckDialog = ref(false), ecgCheckLoading = ref(false), ecgCheckResult = ref(null), ecgCheckName = ref("");
let ecgCheckRequest = 0;
watch(ecgCheckDialog, visible => { if (!visible) { ecgCheckRequest += 1; ecgCheckResult.value = null; ecgCheckLoading.value = false; } });
function clearEcgCheck() { ecgCheckRequest += 1; ecgCheckDialog.value = false; ecgCheckResult.value = null; ecgCheckLoading.value = false; }
onDeactivated(clearEcgCheck);
onBeforeUnmount(clearEcgCheck);
const canCheckImage = computed(() => !!store.state.user.accessToken && store.state.user.permissions.includes("super_admin"));
const imageCheckDialog = ref(false), imageCheckLoading = ref(false), imageCheckResult = ref(null), imageCheckName = ref("");
let imageCheckRequest = 0, imageCheckTarget = null;
function clearImageCheck() { imageCheckRequest++; imageCheckTarget = null; imageCheckDialog.value = false; imageCheckResult.value = null; imageCheckLoading.value = false; }
watch(imageCheckDialog, visible => { if (!visible) clearImageCheck(); });
watch([() => store.state.user.accessToken, () => JSON.stringify(store.state.user.permissions)], clearImageCheck);
onDeactivated(clearImageCheck);
onBeforeUnmount(clearImageCheck);
const promptDialog = ref(false), promptVersions = ref([]), promptSelection = ref("baseline"), taskPrompt = ref(""), systemPrompt = ref(""), promptChange = ref(""), activateNewPrompt = ref(false);
const knowledgeDialog = ref(false), knowledgeForm = ref({}), reviewDialog = ref(false), reviewDocument = ref(null);
const pathwayImportDialog = ref(false), pathwaySourcesLoading = ref(false), pathwaySources = ref({}), pathwayImportForm = ref({});
const selectedPathwaySource = computed(() => pathwaySources.value.items?.find(item => item.pathway_id === pathwayImportForm.value.pathway_id));
const canPublishDocument = computed(() => !!reviewDocument.value && !reviewDocument.value.document_evidence_bound && (!reviewDocument.value.source_kind || (reviewDocument.value.status === "draft" && reviewDocument.value.source_state === "current")));
let pathwaySourceRequest = 0, knowledgeInspection = 0;
watch(pathwayImportDialog, visible => { if (!visible) pathwaySourceRequest += 1; });
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

async function openSpeechCheck(row) {
  const version = ++speechCheckRequest;
  speechCheckName.value = row.name; speechCheckResult.value = null; speechCheckLoading.value = true; speechCheckDialog.value = true;
  try {
    const result = await checkAISpeechProvider(row.provider_id, row.revision);
    if (version === speechCheckRequest && speechCheckDialog.value) speechCheckResult.value = result.data;
  } catch { /* The request layer reports configuration/connection errors. */ }
  finally { if (version === speechCheckRequest) speechCheckLoading.value = false; }
}

function editActualSpeechModel() {
  const result = speechCheckResult.value;
  const row = providers.value.find(item => item.provider_id === result?.provider_id);
  if (!row || row.revision !== result.provider_revision) { ElMessage.warning("已保存配置版本已变化，请刷新后重新检查"); return; }
  speechCheckDialog.value = false;
  editProvider(row); providerForm.value.model = result.capabilities.model_version;
  if (providerForm.value.timeout_seconds <= result.capabilities.timeout_seconds) providerForm.value.timeout_seconds = 120;
}

async function openEcgCheck(row) {
  const version = ++ecgCheckRequest;
  const target = { provider_id: row.provider_id, revision: row.revision, model: row.model };
  ecgCheckName.value = row.name; ecgCheckResult.value = null; ecgCheckLoading.value = true; ecgCheckDialog.value = true;
  try {
    const response = await checkAIEcgProvider(target.provider_id, target.revision);
    if (version !== ecgCheckRequest || !ecgCheckDialog.value) return;
    const result = response.data;
    if (result?.provider_id !== target.provider_id || result.provider_revision !== target.revision || result.configured_model !== target.model) {
      ElMessage.warning("服务核对回执与已保存配置不一致，请刷新后重新检查"); return;
    }
    ecgCheckResult.value = result;
  } catch { /* The request layer reports configuration/connection errors. */ }
  finally { if (version === ecgCheckRequest) ecgCheckLoading.value = false; }
}

function editActualEcgModel() {
  const result = ecgCheckResult.value;
  if (!ecgCheckDialog.value || !result) return;
  const row = providers.value.find(item => item.provider_id === result.provider_id);
  if (!row || row.revision !== result.provider_revision || row.model !== result.configured_model || row.kind !== "specialist" || !row.supported_features?.includes("ecg_analysis")) {
    ElMessage.warning("已保存配置版本已变化，请刷新后重新检查"); return;
  }
  ecgCheckDialog.value = false;
  editProvider(row); providerForm.value.model = result.capabilities.model_version;
  if (providerForm.value.timeout_seconds <= result.capabilities.timeout_seconds) providerForm.value.timeout_seconds = 120;
}

function currentImageTarget(target) {
  if (!canCheckImage.value || !target || target.session !== store.state.user.accessToken) return null;
  return providers.value.find(item => item.provider_id === target.provider_id && item.revision === target.revision && item.model === target.model && item.kind === "specialist" && item.supported_features?.includes("imaging_detection")) || null;
}
async function openImageCheck(row) {
  const target = { provider_id: row.provider_id, revision: row.revision, model: row.model, session: store.state.user.accessToken };
  if (!currentImageTarget(target)) { ElMessage.warning("当前影像服务配置或超级管理员权限已变化，请刷新后重新检查"); return; }
  const version = ++imageCheckRequest;
  imageCheckTarget = target; imageCheckName.value = row.name; imageCheckResult.value = null; imageCheckLoading.value = true; imageCheckDialog.value = true;
  try {
    const response = await checkAIImageProvider(target.provider_id, target.revision);
    if (version !== imageCheckRequest || !imageCheckDialog.value || !currentImageTarget(target)) return;
    const result = response.data;
    if (result?.provider_id !== target.provider_id || result.provider_revision !== target.revision || result.configured_model !== target.model) {
      ElMessage.warning("影像服务核对回执与已保存配置不一致，请刷新后重新检查"); return;
    }
    imageCheckResult.value = result;
  } catch { /* The request layer reports configuration/connection errors. */ }
  finally { if (version === imageCheckRequest) imageCheckLoading.value = false; }
}
function editActualImageModel() {
  const result = imageCheckResult.value, row = currentImageTarget(imageCheckTarget);
  if (!imageCheckDialog.value || !result || !row || row.provider_id !== result.provider_id || row.revision !== result.provider_revision || row.model !== result.configured_model) {
    ElMessage.warning("已保存影像配置或超级管理员权限已变化，请刷新后重新检查"); return;
  }
  imageCheckDialog.value = false;
  editProvider(row); providerForm.value.model = result.capabilities.model_version;
  if (providerForm.value.timeout_seconds <= result.capabilities.timeout_seconds) providerForm.value.timeout_seconds = 120;
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
async function loadPathwaySources() {
  const version = ++pathwaySourceRequest;
  pathwaySourcesLoading.value = true; pathwayImportForm.value.pathway_id = null;
  try { const response = await getAIPathwaySources({ limit: 300 }); if (version === pathwaySourceRequest) pathwaySources.value = response.data || {}; }
  finally { if (version === pathwaySourceRequest) pathwaySourcesLoading.value = false; }
}
function openPathwayImport() {
  pathwayImportForm.value = { pathway_id: null, feature_keys: ["treatment_pathway", "response_review"], department_id: null, effective_from: null, effective_to: null };
  pathwaySources.value = {}; pathwayImportDialog.value = true; loadPathwaySources();
}
async function submitPathwayImport() {
  const source = selectedPathwaySource.value; if (!source?.importable) return;
  saving.value = true;
  try {
    const form = pathwayImportForm.value;
    const response = await importAIPathway(source.pathway_id, { expected_source_hash: source.source_hash, feature_keys: [...form.feature_keys], department_id: form.department_id || null, effective_from: isoOrNull(form.effective_from), effective_to: isoOrNull(form.effective_to) });
    pathwayImportDialog.value = false; await refresh(); await inspectKnowledge(response.data); ElMessage.success("路径快照已保存，请核对全文后审核");
  } finally { saving.value = false; }
}
async function inspectKnowledge(row) { const version = ++knowledgeInspection; const response = await getAIKnowledgeDetail(row.document_id); if (version === knowledgeInspection) { reviewDocument.value = response.data; reviewDialog.value = true; } }
async function reviewDocumentAs(status) {
  if (reviewDocument.value?.document_evidence_bound) { reviewDialog.value=false; tab.value='document_evidence'; return; }
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
