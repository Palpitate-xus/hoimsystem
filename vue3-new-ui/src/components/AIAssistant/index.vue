<template>
  <div class="ai-assistant" v-loading="loading">
    <el-form label-position="top">
      <el-form-item label="AI 功能">
        <el-select v-model="featureKey" filterable placeholder="选择本次需要的辅助功能" style="width: 100%">
          <el-option v-for="item in features" :key="item.key" :label="item.number + ' · ' + item.name" :value="item.key" />
        </el-select>
      </el-form-item>
      <template v-if="selected">
        <div class="feature-description"><strong>需要的资料：</strong>{{ selected.inputs.join('、') }}<br /><strong>预期产出：</strong>{{ selected.deliverables.join('；') }}</div>
        <p v-if="boundClinicalReferences.length">本次绑定资料：{{ boundClinicalReferences.join('、') }}。所选记录未注明对应就诊；选择就诊仅补充临床背景，不确认其归属。</p>
        <p v-if="boundPathwayReferences.length">本次绑定：{{ boundPathwayReferences.join('、') }}。住院关联以原记录核实；路径适用条件和已审核版本仍须核对。</p>
        <p v-if="boundNursingReferences.length && !needsRiskWindow">本次绑定：{{ boundNursingReferences.join('、') }}。按原患者与原住院核对，不能通过补充JSON替换；缺项、历史默认值及人工评分来源仍须复核。</p>
        <p v-if="needsRiskWindow">本任务使用明确选择的原住院观测窗；NEWS2模式另需核对本窗的原点测与适用性评估，补充文字或JSON不能填补原数据缺项。</p>
        <p v-if="props.initialInput.audio_asset_id">本次绑定原录音 {{ props.initialInput.audio_asset_id }}；以原登记资料核对患者与就诊，不能通过补充JSON替换。</p>
        <p v-if="props.initialInput.ecg_asset_id">本次绑定原始心电 {{ props.initialInput.ecg_asset_id }}；以原登记资料核对患者与就诊，不能通过补充JSON替换。</p>
        <p v-if="props.initialInput.imaging_order_id">本次绑定真实影像申请 {{ props.initialInput.imaging_order_id }}；原像素与患者须一致，不能通过补充JSON替换申请。</p>
        <el-alert v-if="!selected.enabled" type="info" :closable="false" title="此功能尚未面向业务启用，由超级管理员配置模型和验证状态。" class="spaced" />
        <el-form-item v-if="selected.scope === 'patient'" label="患者">
          <el-select v-model="patientId" :disabled="!!props.patientId" filterable remote :remote-method="searchPatients" placeholder="搜索有访问权限的患者" style="width: 100%">
            <el-option v-for="item in patients" :key="item.patient_id" :label="item.label" :value="item.patient_id" />
          </el-select>
        </el-form-item>
        <el-form-item v-if="selected.scope === 'patient' && patientId && !needsIncident" label="本次就诊">
          <el-select v-model="encounterRef" clearable :disabled="!!props.encounterRef" :placeholder="needsRiskWindow ? '选择原住院，不能按日期归入门诊或其他住院' : '选择门诊或住院记录；治疗路径推荐需要本次就诊'" style="width: 100%">
            <el-option v-for="item in encounterOptions" :key="item.encounter_ref" :label="item.label" :value="item.encounter_ref" />
          </el-select>
        </el-form-item>
        <el-form-item v-if="needsIncident" label="不良事件标识"><el-input v-model="incidentId" :disabled="!!props.initialInput.adverse_event_id" maxlength="10" placeholder="明确选择本患者事件的正整数标识" /><p>事件未记录就诊关联，不能按上报日期推定属于某次门诊或住院。</p></el-form-item>
        <ai-audio-input v-if="needsAudio && patientId" v-model="audioAssetId" :patient-id="patientId" :encounter-ref="encounterRef" :locked="!!props.initialInput.audio_asset_id" @availability="audioReady = $event" />
        <ai-ecg-input v-if="needsEcg && patientId" v-model="ecgAssetId" :patient-id="patientId" :encounter-ref="encounterRef" :locked="!!props.initialInput.ecg_asset_id" @availability="ecgReady = $event" />
        <ai-observation-window-input v-if="needsRiskWindow && patientId" :patient-id="patientId" :admission-id="encounterRef" :initial-window-id="String(props.initialInput.observation_window_id || '')" :disabled="submitting" @selection="riskWindowSelection = $event" @availability="riskWindowReady = $event" />
        <ai-news2-input v-if="needsNews2 && patientId && riskWindowReady && riskWindowSelection" :patient-id="patientId" :admission-id="encounterRef" :window-id="riskWindowSelection.observation_window_id" @selection="news2Selection = $event" @availability="news2Ready = $event" />
        <ai-image-input v-if="needsImage && patientId" v-model="imageAssetId" :patient-id="patientId" :encounter-ref="encounterRef" :locked-order-id="String(props.initialInput.imaging_order_id || '')" :disabled="submitting" @select="selectImage" @availability="imageReady = $event" />
        <el-form-item v-if="needsPathway && patientId && !props.initialInput.pathway_enrollment_id" label="院内路径（可选）">
          <el-select v-model="pathwayId" :disabled="!!props.initialInput.pathway_id || pathwayOptionsLoading" :clearable="!props.initialInput.pathway_id" filterable placeholder="选择待比选的院内路径；也可仅使用审核指南" style="width: 100%" aria-label="待比选院内路径"><el-option v-for="item in pathwayOptions.items || []" :key="item.pathway_id" :value="String(item.pathway_id)" :disabled="!item.reviewed_for_current_scope" :label="`${item.name} · #${item.pathway_id}${item.reviewed_for_current_scope ? '' : ' · 当前范围未审核'}`" /></el-select>
          <p>{{ pathwayOptions.scope_note }}</p>
        </el-form-item>
        <el-form-item v-if="needsPrescription && patientId" label="待核查处方">
          <el-select v-model="prescriptionId" :clearable="!props.initialInput.prescription_id" :disabled="!!props.initialInput.prescription_id" placeholder="选择实际处方" style="width: 100%"><el-option v-for="item in prescriptions" :key="item.prescription_id" :label="item.label" :value="item.prescription_id" /></el-select>
        </el-form-item>
        <el-form-item v-if="needsCoding" label="编码检索词"><el-input v-model="codingQuery" maxlength="500" placeholder="已记录诊断、手术名称或已有编码；多个词用逗号分隔" /></el-form-item>
        <ai-forecast-input v-if="needsForecast" :initial-series-id="String(props.initialInput.forecast_series_id || '')" @selection="forecastSelection = $event" @availability="forecastReady = $event" />
        <template v-if="needsOperations && !needsForecast">
          <el-form-item label="运营资料日期"><el-date-picker v-model="operationsRange" type="daterange" value-format="YYYY-MM-DD" start-placeholder="开始日期" end-placeholder="结束日期" /></el-form-item>
          <el-form-item v-if="needsPlanning" :label="featureKey === 'surgery_scheduling' ? '排台计划日期' : '排班计划日期'"><el-date-picker v-model="operationsPlanRange" type="daterange" value-format="YYYY-MM-DD" start-placeholder="计划开始日期" end-placeholder="计划结束日期" /></el-form-item>
          <el-form-item v-if="!needsInventory" label="运营科室范围"><el-select v-model="serviceDepartment" clearable filterable :placeholder="serviceOptions.allow_hospital_scope ? '默认全院范围' : '默认所属科室范围'"><el-option v-for="item in serviceOptions.departments || []" :key="item.department_id" :value="item.department_id" :label="item.name" /></el-select></el-form-item>
          <template v-if="needsInventory">
            <el-form-item label="库存药品"><el-select v-model="inventoryDrugs" multiple filterable clearable :disabled="serviceOptions.inventory_scope_available === false" placeholder="选择真实目录药品"><el-option v-for="item in serviceOptions.inventory_drugs || []" :key="item.item_id" :value="item.item_id" :label="item.name" /></el-select></el-form-item>
            <el-form-item label="库存耗材"><el-select v-model="inventoryConsumables" multiple filterable clearable :disabled="serviceOptions.inventory_scope_available === false" placeholder="选择真实目录耗材"><el-option v-for="item in serviceOptions.inventory_consumables || []" :key="item.item_id" :value="item.item_id" :label="item.name" /></el-select></el-form-item>
          </template>
          <p>{{ serviceOptions.scope_note }}</p>
        </template>
        <template v-if="needsAppointment">
          <el-form-item label="预约科室"><el-select v-model="serviceDepartment" clearable filterable :disabled="!!props.initialInput.schedule_id" placeholder="可选：限定科室"><el-option v-for="item in serviceOptions.departments || []" :key="item.department_id" :value="item.department_id" :label="item.name" /></el-select></el-form-item>
          <el-form-item label="预约医生"><el-select v-model="serviceDoctor" clearable filterable :disabled="!!props.initialInput.schedule_id" placeholder="可选：限定医生"><el-option v-for="item in serviceDoctors" :key="item.doctor_id" :value="item.doctor_id" :label="item.name" /></el-select></el-form-item>
          <el-form-item label="预约日期"><el-date-picker v-model="serviceDate" type="date" value-format="YYYY-MM-DD" :disabled="!!props.initialInput.schedule_id" placeholder="默认查询明日至第6日" /></el-form-item>
        </template>
        <template v-if="needsNavigation">
          <el-form-item label="导航起点"><el-select v-model="navigationStart" clearable filterable placeholder="选择已配置起点"><el-option v-for="item in serviceOptions.navigation_nodes || []" :key="item.node_id" :value="item.node_id" :label="[item.name, item.floor, item.location].filter(Boolean).join(' · ')" /></el-select></el-form-item>
          <el-form-item label="导航终点"><el-select v-model="navigationEnd" clearable filterable placeholder="选择已配置终点"><el-option v-for="item in serviceOptions.navigation_nodes || []" :key="item.node_id" :value="item.node_id" :label="[item.name, item.floor, item.location].filter(Boolean).join(' · ')" /></el-select></el-form-item>
        </template>
        <p v-if="(needsNavigation || needsAppointment || needsOperations) && serviceOptions.truncated">当前选项为有限列表；可从具体业务记录进入，或补充更明确的办理需求。</p>
        <el-form-item label="补充资料或问题"><el-input v-model="question" type="textarea" :rows="5" maxlength="12000" show-word-limit :placeholder="'请提供与' + selected.name + '相关的信息，明确哪些是已确认事实'" /></el-form-item>
        <el-collapse v-if="canPreview" class="spaced">
          <el-collapse-item title="联调与预览选项">
            <el-checkbox v-model="preview">超级管理员预览（结果仅供评估）</el-checkbox>
            <p v-if="needsForecast">统计预测只使用所选冻结来源和7/14天跨度；此处JSON不参与计算，也不能改写来源、口径、时区或日计数。</p>
            <p v-if="needsRiskWindow">此处JSON不参与风险观测输入，不能覆盖患者、原住院、窗口、截止时点或原数值。</p>
            <el-input v-model="extraInput" type="textarea" :rows="4" placeholder="可选：专用适配器的结构化输入 JSON，由服务契约规定" class="spaced" />
          </el-collapse-item>
        </el-collapse>
        <el-alert v-if="needsForecast" type="info" :closable="false" title="本功能使用固定统计计算；Prompt仅用于来源审计，不由文本模型推测数值。" class="spaced" />
        <el-alert v-else-if="needsNews2" type="info" :closable="false" title="NEWS2使用固定规则计算；Prompt不改变分数。规则分类及小计下界不表示风险概率或自动处置。" class="spaced" />
        <el-alert v-else-if="selected.engine !== 'llm'" type="info" :closable="false" title="此能力通过专用模型处理，需要对应原始资料和已登记的适配服务。" class="spaced" />
        <div class="actions">
          <el-button v-if="selected.scope === 'patient'" :disabled="!patientId || patientLoading || pathwayOptionsLoading || (needsRiskWindow && !riskWindowReady) || (needsNews2 && !news2Ready) || (needsAudio && (!audioAssetId || !audioReady)) || (needsEcg && (!ecgAssetId || !ecgReady)) || (needsImage && (!imageAssetId || !imageOrderId || !imageReady))" @click="inspectContext">查看本次资料</el-button>
          <el-button v-if="needsOperations" :disabled="serviceOptionsLoading || (needsForecast && !forecastReady)" @click="inspectOperationalContext">查看本次运营资料</el-button>
          <el-button type="primary" :loading="submitting" :disabled="(needsRiskWindow && !riskWindowReady) || (needsNews2 && !news2Ready) || (needsForecast && !forecastReady) || busy || patientLoading || serviceOptionsLoading || pathwayOptionsLoading || (needsAudio && (!audioAssetId || !audioReady)) || (needsEcg && (!ecgAssetId || !ecgReady)) || (needsImage && (!imageAssetId || !imageOrderId || !imageReady)) || (!selected.enabled && !preview) || (selected.scope === 'patient' && !patientId) || (needsInventory && (!inventoryDrugs.length && !inventoryConsumables.length || serviceOptions.inventory_scope_available === false))" @click="submit">生成辅助建议</el-button>
          <el-button v-if="busy" @click="cancel">取消接收结果</el-button>
        </div>
      </template>
      <el-empty v-else-if="!loading" description="当前角色暂无可用 AI 能力" />
    </el-form>

    <el-card v-if="run" shadow="never" class="spaced" aria-label="AI任务结果">
      <template #header><div class="result-header"><strong>{{ run.feature_name }}</strong><el-tag>{{ statuses[run.status] || run.status }}</el-tag><el-tag v-if="run.patient_id" type="info">患者 #{{ run.patient_id }}</el-tag><el-tag v-if="run.preview" type="warning">评估预览</el-tag><el-button v-if="busy" link @click="refreshRun">刷新状态</el-button></div></template>
      <el-alert v-if="busy" type="info" :closable="false" title="任务已保存，正在等待处理或生成结果。" />
      <el-alert v-if="run.status === 'failed'" type="error" :closable="false" :title="run.error_message || '生成失败，请联系管理员检查服务状态'" />
      <ai-service-findings :findings="run.tool_findings" @inspect="inspectEvidence" />
      <ai-operational-findings :findings="run.operational_findings" @inspect="inspectEvidence" />
      <ai-forecast-findings v-if="run.feature_key === 'visit_forecast'" :findings="run.forecast_findings" :analysis="run.result?.forecast_analysis" @inspect="inspectEvidence" />
      <ai-incident-findings :findings="run.incident_findings" @inspect="inspectEvidence" />
      <ai-consultation-findings :findings="run.consultation_findings" @inspect="inspectEvidence" />
      <ai-adr-findings :findings="run.adr_findings" @inspect="inspectEvidence" />
      <ai-pathway-findings :findings="run.pathway_findings" @inspect="inspectEvidence" />
      <ai-nursing-findings :findings="run.nursing_findings" @inspect="inspectEvidence" />
      <ai-observation-findings :findings="run.observation_findings" :expected-patient-id="run.patient_id" :expected-admission-id="run.encounter_ref || encounterRef" @inspect="inspectEvidence" />
      <ai-news2-findings v-if="run.news2_findings" :source="run.news2_findings.news2_source" :scope="run.news2_findings.news2_assessment" :analysis="run.result?.news2_analysis" :expected-patient-id="run.patient_id" :expected-admission-id="run.encounter_ref || encounterRef" @inspect="inspectEvidence" />
      <ai-speech-findings :findings="run.audio_findings" :transcription="run.result?.transcription" :allow-copy="run.status === 'succeeded'" @inspect="inspectEvidence" @copy="copyDraft" />
      <ai-image-findings :findings="run.image_findings" :analysis="run.result?.image_analysis" :allow-copy="run.status === 'succeeded'" @inspect="inspectEvidence" @copy="copyDraft" />
      <ai-ecg-findings :findings="run.ecg_findings" :analysis="run.result?.ecg_analysis" :allow-copy="run.status === 'succeeded'" @inspect="inspectEvidence" @copy="copyDraft" />
      <div v-if="run.tool_findings?.billing_reconciliation" class="spaced">
        <h4>原始账目与执行关联核对</h4><p>{{ run.tool_findings.billing_reconciliation.scope_note }}</p>
        <el-table v-if="run.tool_findings.billing_reconciliation.scope?.kind === 'inpatient'" :data="run.tool_findings.billing_reconciliation.checks" max-height="320" empty-text="本次范围暂无可核对住院费用">
          <el-table-column prop="item_name" label="收费项目" min-width="130" />
          <el-table-column label="账务状态" width="85"><template #default="{ row }">{{ ({ 0: '未结算', 1: '已结算', 2: '已退费' })[row.charge_status] || '未知' }}</template></el-table-column>
          <el-table-column prop="quantity" label="原数量" width="90" /><el-table-column prop="unit_price" label="原单价" width="90" /><el-table-column prop="stored_amount" label="保存金额" width="95" />
          <el-table-column label="核对提示" min-width="260"><template #default="{ row }"><p v-for="(finding, index) in row.findings" :key="index">{{ finding }}</p><span v-if="!row.findings.length">未产生上述核对提示，收费资格仍需人工核实</span></template></el-table-column>
          <el-table-column label="原始依据" width="110"><template #default="{ row }"><el-button v-for="id in row.source_ids" :key="id" link @click="inspectEvidence(id)">{{ evidenceTitle(id) }}</el-button></template></el-table-column>
        </el-table>
        <el-table v-if="run.tool_findings.billing_reconciliation.scope?.kind === 'outpatient'" :data="run.tool_findings.billing_reconciliation.outpatient_checks" max-height="320" empty-text="本次范围暂无可核对门诊费用">
          <el-table-column prop="charge_type" label="原收费分类" width="130" /><el-table-column prop="expected_amount" label="保存应收金额" width="120" />
          <el-table-column label="账务状态" width="85"><template #default="{ row }">{{ ({ 0: '未缴费', 1: '已缴费', 2: '已退费' })[row.charge_status] || '未知' }}</template></el-table-column>
          <el-table-column label="核对提示" min-width="270"><template #default="{ row }"><p v-for="(finding, index) in row.findings" :key="index">{{ finding }}</p><span v-if="!row.findings.length">未产生上述核对提示，仍需结合原始账务复核</span></template></el-table-column>
          <el-table-column label="原始依据" width="160"><template #default="{ row }"><el-button v-for="id in row.source_ids" :key="id" link @click="inspectEvidence(id)">{{ evidenceTitle(id) }}</el-button></template></el-table-column>
        </el-table>
        <template v-if="run.tool_findings.billing_reconciliation.executed_without_charge_link?.length">
          <h4>已记录执行、未保存收费关联的待核实医嘱</h4><p>此列表不构成漏收费或应补费结论。</p>
          <el-table :data="run.tool_findings.billing_reconciliation.executed_without_charge_link" max-height="240">
            <el-table-column prop="order_id" label="医嘱标识" min-width="240" /><el-table-column prop="category" label="原分类" width="110" />
            <el-table-column label="原始依据" width="140"><template #default="{ row }"><el-button v-for="id in row.source_ids" :key="id" link @click="inspectEvidence(id)">查看执行汇总</el-button></template></el-table-column>
          </el-table>
        </template>
        <p v-if="run.tool_findings.billing_reconciliation.truncated_sources?.length">本次资料已截断，请结合完整业务清单核查。</p>
      </div>
      <div v-if="run.tool_findings?.icd_candidates" class="spaced">
        <h4>院内字典文字匹配候选</h4><p>{{ run.tool_findings.icd_candidates.scope_note }}</p>
        <el-table :data="run.tool_findings.icd_candidates.candidates" max-height="290" empty-text="当前检索词未匹配到有效条目，请补充已记录的诊断或手术检索词">
          <el-table-column label="类型" width="90"><template #default="{ row }">{{ row.kind === 'diagnosis' ? '诊断' : '手术' }}</template></el-table-column>
          <el-table-column prop="code" label="字典编码" width="120" /><el-table-column prop="name" label="当前标准名称" min-width="200" />
          <el-table-column label="依据" width="130"><template #default="{ row }"><el-button link @click="inspectEvidence(row.source_id)">查看字典依据</el-button></template></el-table-column>
        </el-table>
        <p v-if="run.tool_findings.icd_candidates.truncated">候选较多，已限制展示范围，可补充更具体检索词。</p>
      </div>
      <template v-if="run.status === 'succeeded'">
        <el-alert type="info" :closable="false" title="以下内容为辅助建议或草稿，请核对事实和引用依据后使用。" />
        <p class="plain-text">{{ run.result?.summary }}</p>
        <el-alert v-for="(item, index) in run.result?.warnings || []" :key="'warning-' + index" type="warning" :closable="false" :title="item" class="spaced" />
        <div v-if="run.result?.missing_data?.length" class="spaced"><strong>仍需补充或核实：</strong><ul><li v-for="(item, index) in run.result.missing_data" :key="index">{{ item }}</li></ul></div>
        <section v-for="(section, index) in run.result?.sections || []" :key="index" class="result-section">
          <h4>{{ section.title }}</h4><p class="plain-text">{{ section.content }}</p>
          <el-button v-for="id in section.source_ids" :key="id" link type="primary" @click="inspectEvidence(id)">查看依据：{{ evidenceTitle(id) }}</el-button>
        </section>
        <div class="actions"><el-button v-if="!run.result?.transcription" @click="copyDraft">复制草稿</el-button><el-button @click="feedbackDialog = true">记录复核反馈</el-button></div>
        <p class="metadata">Prompt v{{ run.prompt_version }} · 模型配置 v{{ run.provider_revision }} · 输入/输出 {{ run.input_tokens }}/{{ run.output_tokens }} Token</p>
      </template>
    </el-card>

    <el-collapse class="spaced" @change="loadHistory">
      <el-collapse-item title="最近任务"><el-table :data="history" :empty-text="selected?.scope === 'patient' && !patientId ? '先选择患者查看相应任务' : '当前范围暂无历史任务'"><el-table-column prop="feature_name" label="功能" /><el-table-column prop="patient_id" label="患者ID" width="85" /><el-table-column label="状态" width="90"><template #default="{ row }">{{ statuses[row.status] || row.status }}</template></el-table-column><el-table-column prop="create_time" label="时间" /><el-table-column label="操作" width="80"><template #default="{ row }"><el-button link @click="openRun(row.run_id)">查看</el-button></template></el-table-column></el-table></el-collapse-item>
    </el-collapse>
    <el-dialog v-model="contextDialog" :title="needsOperations ? '本次提供给 AI 的运营资料' : '本次提供给 AI 的患者资料'" width="min(1000px, 96vw)">
      <el-alert type="info" :closable="false" title="资料保留时间和状态，缺失信息会单独标记。" />
      <ai-operational-findings v-if="needsOperations && !needsForecast" :findings="contextData?.context" @inspect="inspectPreviewEvidence" />
      <ai-forecast-findings v-if="needsForecast && contextDialog" :findings="contextData?.context" @inspect="inspectPreviewEvidence" />
      <ai-incident-findings v-if="needsIncident" :findings="contextData?.context" @inspect="inspectPreviewEvidence" />
      <ai-consultation-findings :findings="contextData?.context?.consultation_sources" @inspect="inspectPreviewEvidence" />
      <ai-adr-findings :findings="contextData?.context?.adr_sources" @inspect="inspectPreviewEvidence" />
      <ai-pathway-findings :findings="contextData?.context?.pathway_sources" @inspect="inspectPreviewEvidence" />
      <ai-nursing-findings :findings="contextData?.context?.nursing_source_review" @inspect="inspectPreviewEvidence" />
      <ai-observation-findings :findings="contextData?.context?.observation_window" :expected-patient-id="patientId" :expected-admission-id="encounterRef" @inspect="inspectPreviewEvidence" />
      <ai-news2-findings v-if="contextData?.context?.news2_source" :source="contextData.context.news2_source" :scope="contextData.context.news2_assessment" :expected-patient-id="patientId" :expected-admission-id="encounterRef" @inspect="inspectPreviewEvidence" />
      <ai-speech-findings v-if="contextDialog" :findings="contextData?.context" @inspect="inspectPreviewEvidence" />
      <ai-image-findings v-if="contextDialog" :findings="contextData?.context" @inspect="inspectPreviewEvidence" />
      <ai-ecg-findings v-if="contextDialog" :findings="contextData?.context" @inspect="inspectPreviewEvidence" />
      <el-collapse v-if="needsOperations"><el-collapse-item title="查看原始资料字段"><pre class="plain-text">{{ JSON.stringify(contextData, null, 2) }}</pre></el-collapse-item></el-collapse>
      <pre v-else class="plain-text">{{ JSON.stringify(contextData, null, 2) }}</pre>
    </el-dialog>
    <el-dialog v-model="evidenceDialog" title="核查引用依据" width="760px"><template v-if="evidence"><p><strong>{{ evidence.title }}</strong> {{ evidence.version ? '· ' + evidence.version : '' }}</p><p v-if="evidence.source_uri" class="plain-text">来源：{{ evidence.source_uri }}</p><p v-if="evidence.observed_at">记录时间：{{ evidence.observed_at }}</p><pre class="plain-text">{{ evidence.content }}</pre></template></el-dialog>
    <el-dialog v-model="feedbackDialog" title="人工复核反馈" width="540px"><el-radio-group v-model="feedback.outcome"><el-radio value="accepted">采纳</el-radio><el-radio value="rejected">驳回</el-radio><el-radio value="modified">修改后采纳</el-radio></el-radio-group><el-input v-model="feedback.comment" type="textarea" :rows="4" maxlength="2000" placeholder="说明核查结果或修改内容；反馈不会自动写入病历、处方或医嘱" class="spaced" /><template #footer><el-button @click="feedbackDialog = false">取消</el-button><el-button type="primary" @click="submitFeedback">保存反馈</el-button></template></el-dialog>
  </div>
</template>

<script setup>
import { computed, defineAsyncComponent, onActivated, onBeforeUnmount, onDeactivated, onMounted, ref, watch } from "vue";
import { useStore } from "vuex";
import { ElMessage } from "element-plus";
import { cancelAIRun, createAIRun, getAIClinicalContext, getAIOperationalContext, getAIEncounters, getAIFeatures, getAIPatients, getAIPrescriptions, getAIPathwayOptions, getAIServiceOptions, getAIRun, getAIRuns, reviewAIRun } from "@/api/ai";
import AiServiceFindings from "@/components/AIServiceFindings/index.vue";
import AiOperationalFindings from "@/components/AIOperationalFindings/index.vue";
import AiIncidentFindings from "@/components/AIIncidentFindings/index.vue";
import AiConsultationFindings from "@/components/AIConsultationFindings/index.vue";
import AiAdrFindings from "@/components/AIAdrFindings/index.vue";
import AiPathwayFindings from "@/components/AIPathwayFindings/index.vue";
import AiNursingFindings from "@/components/AINursingFindings/index.vue";
import AiAudioInput from "@/components/AIAudioInput/index.vue";
import AiSpeechFindings from "@/components/AISpeechFindings/index.vue";
import AiImageInput from "@/components/AiImageInput.vue";
import AiImageFindings from "@/components/AIImageFindings/index.vue";
import AiEcgInput from "@/components/AIEcgInput/index.vue";
import AiEcgFindings from "@/components/AIEcgFindings/index.vue";

const AiForecastInput = defineAsyncComponent(() => import("@/components/AIForecastInput/index.vue"));
const AiForecastFindings = defineAsyncComponent(() => import("@/components/AIForecastFindings/index.vue"));
const AiObservationWindowInput = defineAsyncComponent(() => import("@/components/AIObservationWindowInput/index.vue"));
const AiObservationFindings = defineAsyncComponent(() => import("@/components/AIObservationFindings/index.vue"));
const AiNews2Input = defineAsyncComponent(() => import("@/components/AINews2Input/index.vue"));
const AiNews2Findings = defineAsyncComponent(() => import("@/components/AINews2Findings/index.vue"));

const props = defineProps({ featureKeys: { type: Array, default: () => [] }, initialFeature: { type: String, default: "" }, patientId: { type: Number, default: null }, encounterRef: { type: String, default: "" }, initialInput: { type: Object, default: () => ({}) } });
const store = useStore();
const canPreview = computed(() => store.getters["user/permissions"].includes("super_admin"));
const statuses = { queued: "已排队", running: "生成中", succeeded: "待复核", failed: "失败", cancelled: "已取消" };
const loading = ref(false), submitting = ref(false), patientLoading = ref(false), features = ref([]), featureKey = ref("");
const patientId = ref(null), encounterRef = ref(""), prescriptionId = ref(null), patients = ref([]), encounters = ref([]), prescriptions = ref([]);
const question = ref(""), codingQuery = ref(""), extraInput = ref(""), preview = ref(false), run = ref(null), history = ref([]);
const contextDialog = ref(false), contextData = ref(null), evidenceDialog = ref(false), evidence = ref(null), feedbackDialog = ref(false), feedback = ref({ outcome: "accepted", comment: "" });
const selected = computed(() => features.value.find(item => item.key === featureKey.value));
const needsRiskWindow = computed(() => ["deterioration_risk", "sepsis_risk", "aki_risk"].includes(featureKey.value)), riskWindowSelection = ref(null), riskWindowReady = ref(false);
const needsNews2 = computed(() => featureKey.value === "deterioration_risk" && selected.value?.input_mode === "news2"), news2Selection = ref(null), news2Ready = ref(false);
const encounterOptions = computed(() => needsRiskWindow.value ? encounters.value.filter(item => item.kind === "inpatient") : encounters.value);
const needsPrescription = computed(() => ["interaction_review", "allergy_review", "dose_review", "antimicrobial_review"].includes(featureKey.value));
const needsCoding = computed(() => ["icd_candidates", "drg_evidence_review"].includes(featureKey.value));
const needsAppointment = computed(() => featureKey.value === "appointment_assistant"), needsNavigation = computed(() => featureKey.value === "hospital_navigation");
const needsOperations = computed(() => selected.value?.scope === "hospital"), needsInventory = computed(() => ["supply_forecast", "inventory_optimization"].includes(featureKey.value));
const needsForecast = computed(() => featureKey.value === "visit_forecast"), forecastSelection = ref(null), forecastReady = ref(false);
const needsPlanning = computed(() => ["roster_optimization", "surgery_scheduling"].includes(featureKey.value));
const needsIncident = computed(() => featureKey.value === "incident_rca"), incidentId = ref("");
const needsAudio = computed(() => featureKey.value === "medical_transcription"), audioAssetId = ref(""), audioReady = ref(false);
const needsImage = computed(() => featureKey.value === "imaging_detection"), imageAssetId = ref(""), imageOrderId = ref(""), imageReady = ref(false);
function selectImage(id, asset) { imageOrderId.value = asset?.imaging_order_id || props.initialInput.imaging_order_id || ""; }
const needsEcg = computed(() => featureKey.value === "ecg_analysis"), ecgAssetId = ref(""), ecgReady = ref(false);
const needsPathway = computed(() => ["treatment_pathway", "response_review"].includes(featureKey.value)), pathwayId = ref(null), pathwayOptions = ref({}), pathwayOptionsLoading = ref(false);
const boundPathwayLabels = { pathway_id: "院内路径", pathway_enrollment_id: "原入径记录" };
const boundPathwayReferences = computed(() => Object.entries(boundPathwayLabels).filter(([key]) => props.initialInput[key] != null).map(([key, label]) => `${label} #${props.initialInput[key]}`));
const boundReferenceLabels = { referral_id: "转诊", mdt_id: "MDT", reaction_id: "ADR上报" };
const boundClinicalReferences = computed(() => Object.entries(boundReferenceLabels).filter(([key]) => props.initialInput[key] != null).map(([key, label]) => `${label} #${props.initialInput[key]}`));
const boundNursingLabels = { nursing_assessment_id: "原护理评估", nursing_plan_id: "原护理计划", critical_care_record_id: "原危重护理记录", icu_score_id: "原人工评分" };
const boundNursingReferences = computed(() => Object.entries(boundNursingLabels).filter(([key]) => props.initialInput[key] != null).map(([key, label]) => `${label} #${props.initialInput[key]}`));
const operationsRange = ref([]), operationsPlanRange = ref([]), inventoryDrugs = ref([]), inventoryConsumables = ref([]), serviceOptionsLoading = ref(false);
const serviceOptions = ref({}), serviceDepartment = ref(null), serviceDoctor = ref(null), serviceDate = ref(""), navigationStart = ref(null), navigationEnd = ref(null);
const serviceDoctors = computed(() => (serviceOptions.value.doctors || []).filter(item => !serviceDepartment.value || item.department_id === serviceDepartment.value));
const busy = computed(() => ["queued", "running"].includes(run.value?.status));
let timer = null, pollVersion = 0, formVersion = 0, patientLoadVersion = 0, historyVersion = 0, selectionVersion = 0, historyOpen = false, pathwayOptionsVersion = 0;

function stopPolling() { pollVersion += 1; clearTimeout(timer); timer = null; }
function startPolling() {
  stopPolling();
  if (!busy.value) return;
  const version = pollVersion, id = run.value.run_id;
  const poll = async () => {
    try {
      const response = await getAIRun(id);
      if (version !== pollVersion) return;
      run.value = response.data;
      if (busy.value) timer = setTimeout(poll, 2000);
    } catch { if (version === pollVersion) stopPolling(); }
  };
  timer = setTimeout(poll, 1200);
}
async function searchPatients(keyword = "") {
  if (selected.value?.scope !== "patient") return;
  const version = formVersion;
  const response = await getAIPatients({ feature_key: featureKey.value, keyword });
  if (version !== formVersion) return;
  patients.value = response.data || [];
  if (props.patientId && !patients.value.some(item => item.patient_id === props.patientId)) patients.value.push({ patient_id: props.patientId, label: `患者 #${props.patientId}` });
}
watch(featureKey, async () => {
  formVersion += 1; stopPolling(); run.value = null; contextData.value = null;
  const featureVersion = formVersion;
  patientId.value = null; encounters.value = []; prescriptions.value = []; encounterRef.value = ""; prescriptionId.value = null;
  question.value = props.initialInput.question || ""; codingQuery.value = props.initialInput.icd_query || ""; extraInput.value = "";
  incidentId.value = props.initialInput.adverse_event_id == null ? "" : String(props.initialInput.adverse_event_id);
  pathwayId.value = props.initialInput.pathway_id == null ? null : String(props.initialInput.pathway_id);
  audioAssetId.value = props.initialInput.audio_asset_id == null ? "" : String(props.initialInput.audio_asset_id); audioReady.value = false;
  ecgAssetId.value = props.initialInput.ecg_asset_id == null ? "" : String(props.initialInput.ecg_asset_id); ecgReady.value = false;
  imageAssetId.value = props.initialInput.image_asset_id == null ? "" : String(props.initialInput.image_asset_id); imageOrderId.value = props.initialInput.imaging_order_id || ""; imageReady.value = false;
  forecastSelection.value = null; forecastReady.value = false;
  riskWindowSelection.value = null; riskWindowReady.value = false;
  serviceOptions.value = {}; serviceDepartment.value = props.initialInput.department_id || null; serviceDoctor.value = props.initialInput.doctor_id || null; serviceDate.value = props.initialInput.appointment_date || "";
  navigationStart.value = props.initialInput.start_node_id || null; navigationEnd.value = props.initialInput.end_node_id || null;
  operationsRange.value = props.initialInput.date_from && props.initialInput.date_to ? [props.initialInput.date_from, props.initialInput.date_to] : []; inventoryDrugs.value = [...(props.initialInput.drug_ids || [])]; inventoryConsumables.value = [...(props.initialInput.consumable_ids || [])]; serviceOptionsLoading.value = false;
  operationsPlanRange.value = props.initialInput.planning_date_from && props.initialInput.planning_date_to ? [props.initialInput.planning_date_from, props.initialInput.planning_date_to] : [];
  if (selected.value?.scope === "patient") { await searchPatients(); if (featureVersion !== formVersion) return; patientId.value = props.patientId || (patients.value.length === 1 ? patients.value[0].patient_id : null); }
  if (needsNavigation.value || needsAppointment.value || (needsOperations.value && !needsForecast.value)) {
    const version = formVersion; serviceOptionsLoading.value = true;
    try { const response = await getAIServiceOptions({ feature_key: featureKey.value }); if (version === formVersion) { serviceOptions.value = response.data || {}; if (needsOperations.value && !operationsRange.value?.length) operationsRange.value = serviceOptions.value.default_window || []; if (needsPlanning.value && !operationsPlanRange.value?.length) operationsPlanRange.value = serviceOptions.value.default_planning_window || []; } }
    finally { if (version === formVersion) serviceOptionsLoading.value = false; }
  }
});
watch(patientId, async id => {
  const patientVersion = ++patientLoadVersion;
  patientLoading.value = !!id;
  riskWindowSelection.value = null; riskWindowReady.value = false;
  stopPolling(); run.value = null;
  encounterRef.value = id && !needsIncident.value ? props.encounterRef || "" : ""; prescriptionId.value = id ? props.initialInput.prescription_id || null : null; contextData.value = null; encounters.value = []; prescriptions.value = [];
  pathwayId.value = props.initialInput.pathway_id == null ? null : String(props.initialInput.pathway_id);
  audioAssetId.value = props.initialInput.audio_asset_id == null ? "" : String(props.initialInput.audio_asset_id); audioReady.value = false;
  ecgAssetId.value = props.initialInput.ecg_asset_id == null ? "" : String(props.initialInput.ecg_asset_id); ecgReady.value = false;
  imageAssetId.value = props.initialInput.image_asset_id == null ? "" : String(props.initialInput.image_asset_id); imageOrderId.value = props.initialInput.imaging_order_id || ""; imageReady.value = false;
  if (needsIncident.value) { incidentId.value = props.initialInput.adverse_event_id == null ? "" : String(props.initialInput.adverse_event_id); patientLoading.value = false; return; }
  if (!id) return;
  const version = formVersion, key = featureKey.value;
  try {
    const response = await getAIEncounters({ feature_key: key, patient_id: id });
    if (version !== formVersion || patientVersion !== patientLoadVersion) return;
    encounters.value = response.data || [];
    if (needsPrescription.value) {
      const response = await getAIPrescriptions({ feature_key: key, patient_id: id });
      if (version === formVersion && patientVersion === patientLoadVersion) prescriptions.value = response.data || [];
    }
  } finally { if (patientVersion === patientLoadVersion) patientLoading.value = false; }
});
watch(encounterRef, () => { stopPolling(); run.value = null; contextData.value = null; riskWindowSelection.value = null; riskWindowReady.value = false; });
watch([needsNews2, () => riskWindowSelection.value?.observation_window_id, () => riskWindowSelection.value?.content_hash, riskWindowReady], () => { news2Selection.value = null; news2Ready.value = false; });
watch([needsNews2, () => JSON.stringify(news2Selection.value), news2Ready, () => JSON.stringify(riskWindowSelection.value), riskWindowReady, () => JSON.stringify(forecastSelection.value), forecastReady, featureKey, patientId, encounterRef, prescriptionId, incidentId, pathwayId, audioAssetId, ecgAssetId, imageAssetId, imageOrderId, serviceDepartment, serviceDoctor, serviceDate, navigationStart, navigationEnd, operationsRange, operationsPlanRange, () => inventoryDrugs.value.join(','), () => inventoryConsumables.value.join(','), () => JSON.stringify(props.initialInput)], () => {
  selectionVersion += 1; stopPolling(); run.value = null; contextData.value = null; contextDialog.value = false; evidenceDialog.value = false; feedbackDialog.value = false;
});
watch(() => run.value?.run_id, () => { evidenceDialog.value = false; feedbackDialog.value = false; feedback.value = { outcome: "accepted", comment: "" }; });
watch(serviceDepartment, id => { const doctor = serviceOptions.value.doctors?.find(item => item.doctor_id === serviceDoctor.value); if (id && doctor && doctor.department_id !== id) serviceDoctor.value = null; });
watch([featureKey, patientId, encounterRef], () => { historyVersion += 1; history.value = []; if (historyOpen) loadHistory(); });
watch(() => props.initialFeature, key => { if (features.value.some(item => item.key === key)) featureKey.value = key; });
watch(() => props.patientId, id => { formVersion += 1; patientId.value = id; });
watch(() => props.encounterRef, value => { encounterRef.value = needsIncident.value ? "" : value; });
watch(() => props.initialInput.adverse_event_id, value => { incidentId.value = value == null ? "" : String(value); });
watch(() => props.initialInput.pathway_id, value => { pathwayId.value = value == null ? null : String(value); });
watch(() => props.initialInput.audio_asset_id, value => { audioAssetId.value = value == null ? "" : String(value); });
watch(audioReady, ready => { if (needsAudio.value && !ready) { stopPolling(); run.value = null; contextData.value = null; } });
watch(() => props.initialInput.ecg_asset_id, value => { ecgAssetId.value = value == null ? "" : String(value); });
watch(() => props.initialInput.image_asset_id, value => { imageAssetId.value = value == null ? "" : String(value); });
watch(imageReady, ready => { if (needsImage.value && !ready) { stopPolling(); run.value = null; contextData.value = null; } });
watch(ecgReady, ready => { if (needsEcg.value && !ready) { stopPolling(); run.value = null; contextData.value = null; } });
watch([featureKey, patientId, encounterRef], async () => {
  const version = ++pathwayOptionsVersion;
  pathwayOptions.value = {}; pathwayOptionsLoading.value = false;
  if (!needsPathway.value || !patientId.value || props.initialInput.pathway_enrollment_id) return;
  pathwayOptionsLoading.value = true;
  try { const response = await getAIPathwayOptions({ feature_key: featureKey.value, patient_id: patientId.value, encounter_ref: encounterRef.value || undefined }); if (version === pathwayOptionsVersion) pathwayOptions.value = response.data || {}; }
  finally { if (version === pathwayOptionsVersion) pathwayOptionsLoading.value = false; }
}, { flush: "post" });
async function inspectContext() {
  const input = buildTaskInput(); if (!input) return;
  const version = selectionVersion;
  const sourceKeys = needsRiskWindow.value ? ["observation_window_id", "news2_assessment_id"] : selected.value?.source_reference_keys || ["record_id", "structured_record_id", "prescription_id", "lab_result_id", "imaging_report_id"];
  const references = Object.fromEntries(sourceKeys.filter(key => input[key]).map(key => [key, input[key]]));
  const response = await getAIClinicalContext({ ...references, feature_key: featureKey.value, patient_id: patientId.value, encounter_ref: encounterRef.value || undefined });
  if (version !== selectionVersion) return;
  contextData.value = response.data; contextDialog.value = true;
}
async function inspectOperationalContext() {
  const input = buildTaskInput(); if (!input) return;
  const version = selectionVersion;
  const response = await getAIOperationalContext({ feature_key: featureKey.value, input });
  if (version !== selectionVersion) return;
  contextData.value = response.data; contextDialog.value = true;
}
function buildTaskInput() {
  if (needsRiskWindow.value) {
    if (!riskWindowReady.value || !riskWindowSelection.value || !encounterRef.value) { ElMessage.warning("请先选择并核对原住院观测窗"); return; }
    if (needsNews2.value) {
      if (!news2Ready.value || !news2Selection.value) { ElMessage.warning("请明确选择并核对NEWS2原点测与适用性评估来源"); return; }
      return { observation_window_id: riskWindowSelection.value.observation_window_id, news2_assessment_id: news2Selection.value.news2_assessment_id, question: question.value };
    }
    return { observation_window_id: riskWindowSelection.value.observation_window_id, question: question.value };
  }
  if (needsForecast.value) {
    if (!forecastReady.value || !forecastSelection.value) { ElMessage.warning("请先选择并核对冻结预测来源"); return; }
    return { forecast_series_id: forecastSelection.value.forecast_series_id, horizon_days: forecastSelection.value.horizon_days, question: question.value };
  }
  let extra = {};
  if (canPreview.value && extraInput.value.trim()) {
    try { extra = JSON.parse(extraInput.value); if (!extra || Array.isArray(extra) || typeof extra !== "object") throw new Error(); }
    catch { ElMessage.error("结构化资料应为有效 JSON 对象"); return; }
  }
  const input = { ...props.initialInput, ...extra, question: question.value };
  for (const key of [...Object.keys(boundReferenceLabels), ...Object.keys(boundPathwayLabels), ...Object.keys(boundNursingLabels), "audio_asset_id", "ecg_asset_id", "image_asset_id", "imaging_order_id"]) if (props.initialInput[key] != null) input[key] = String(props.initialInput[key]);
  if (needsAudio.value && !props.initialInput.audio_asset_id) { if (audioAssetId.value) input.audio_asset_id = audioAssetId.value; else delete input.audio_asset_id; }
  if (needsEcg.value && !props.initialInput.ecg_asset_id) { if (ecgAssetId.value) input.ecg_asset_id = ecgAssetId.value; else delete input.ecg_asset_id; }
  if (needsImage.value) { if (imageAssetId.value) input.image_asset_id = imageAssetId.value; else delete input.image_asset_id; if (imageOrderId.value) input.imaging_order_id = String(props.initialInput.imaging_order_id || imageOrderId.value); else delete input.imaging_order_id; }
  if (needsPathway.value && !props.initialInput.pathway_id && !props.initialInput.pathway_enrollment_id) { if (pathwayId.value) input.pathway_id = String(pathwayId.value); else delete input.pathway_id; }
  if (needsCoding.value && codingQuery.value.trim()) input.icd_query = codingQuery.value.trim();
  if (needsAppointment.value) { for (const [key, value] of [["department_id", serviceDepartment.value], ["doctor_id", serviceDoctor.value], ["appointment_date", serviceDate.value]]) { if (value) input[key] = value; else delete input[key]; } }
  if (needsNavigation.value) { for (const [key, value] of [["start_node_id", navigationStart.value], ["end_node_id", navigationEnd.value]]) { if (value) input[key] = value; else delete input[key]; } }
  if (prescriptionId.value) input.prescription_id = prescriptionId.value;
  if (needsIncident.value && incidentId.value.trim()) input.adverse_event_id = incidentId.value.trim();
  if (needsOperations.value) {
    if (operationsRange.value?.length === 2) { input.date_from = operationsRange.value[0]; input.date_to = operationsRange.value[1]; } else { delete input.date_from; delete input.date_to; }
    if (needsPlanning.value && operationsPlanRange.value?.length === 2) { input.planning_date_from = operationsPlanRange.value[0]; input.planning_date_to = operationsPlanRange.value[1]; } else { delete input.planning_date_from; delete input.planning_date_to; }
    if (needsInventory.value) { input.drug_ids = [...inventoryDrugs.value]; input.consumable_ids = [...inventoryConsumables.value]; delete input.department_id; }
    else if (serviceDepartment.value) input.department_id = serviceDepartment.value; else delete input.department_id;
  }
  return input;
}
async function submit() {
  const input = buildTaskInput(); if (!input) return;
  submitting.value = true;
  stopPolling(); const selection = selectionVersion, view = pollVersion;
  try {
    const response = await createAIRun({ feature_key: featureKey.value, patient_id: selected.value.scope === "patient" ? patientId.value : null, encounter_ref: selected.value.scope === "patient" ? encounterRef.value || null : null, input, preview: canPreview.value && preview.value });
    if (selection !== selectionVersion || view !== pollVersion) return;
    run.value = response.data; startPolling();
  } finally { submitting.value = false; }
}
async function refreshRun() { if (run.value) { stopPolling(); const id = run.value.run_id, selection = selectionVersion, view = pollVersion; const response = await getAIRun(id); if (selection !== selectionVersion || view !== pollVersion || id !== run.value?.run_id) return; run.value = response.data; startPolling(); } }
async function openRun(id) { stopPolling(); const selection = selectionVersion, view = pollVersion; const response = await getAIRun(id); if (selection !== selectionVersion || view !== pollVersion) return; run.value = response.data; startPolling(); }
async function cancel() { await cancelAIRun(run.value.run_id); await refreshRun(); }
async function loadHistory(activeNames) {
  if (activeNames !== undefined) historyOpen = activeNames.length > 0;
  if (!historyOpen || !featureKey.value || (selected.value?.scope === "patient" && !patientId.value)) return;
  const version = ++historyVersion;
  const response = await getAIRuns({ feature_key: featureKey.value, patient_id: selected.value?.scope === "patient" ? patientId.value : undefined, encounter_ref: selected.value?.scope === "patient" ? encounterRef.value || undefined : undefined });
  if (version === historyVersion) history.value = response.data || [];
}
watch([() => JSON.stringify(store.getters["user/permissions"]), () => store.state.user.accessToken], () => {
  if (!needsForecast.value && !needsRiskWindow.value) return;
  formVersion++; patientLoadVersion++; patients.value = []; encounters.value = []; prescriptions.value = []; patientLoading.value = false; patientId.value = null; encounterRef.value = ""; prescriptionId.value = null; question.value = ""; extraInput.value = ""; preview.value = false;
  selectionVersion++; historyVersion++; stopPolling(); run.value = null; contextData.value = null; contextDialog.value = false; evidenceDialog.value = false; feedbackDialog.value = false; history.value = []; forecastReady.value = false; forecastSelection.value = null; riskWindowReady.value = false; riskWindowSelection.value = null; news2Ready.value = false; news2Selection.value = null;
  if (needsRiskWindow.value && store.state.user.accessToken) searchPatients().catch(() => {});
});
const evidenceTitle = id => run.value?.evidence?.find(item => item.source_id === id)?.title || "来源";
function inspectEvidence(id) { evidence.value = run.value?.evidence?.find(item => item.source_id === id); evidenceDialog.value = !!evidence.value; }
function inspectPreviewEvidence(id) { evidence.value = contextData.value?.evidence?.find(item => item.source_id === id); evidenceDialog.value = !!evidence.value; }
async function copyDraft() {
  const transcript = run.value.result.transcription;
  const segments = transcript ? ["原录音转写草稿，待逐段听音与角色核对：", ...transcript.segments.map(item => `[${item.start_ms}–${item.end_ms}毫秒] ${item.speaker}（角色待核实）\n${item.text}${item.uncertain ? '\n不确定：' + item.uncertainty_note : ''}`)] : [];
  const ecg = run.value.result.ecg_analysis;
  const ecgFindings = ecg ? ["原始心电候选草稿，待结合原波形和临床资料人工复核：", `原记录 ${ecg.asset_id}；原采样哈希 ${ecg.signal_hash}；原导联 ${ecg.processing.input_leads.join('、')}；实际使用 ${ecg.processing.used_leads.join('、')}`, ...ecg.findings.map(item => `${item.label}\n${item.description}\n导联：${item.leads.join('、')}；位置：${item.location === 'recording' ? '整段候选，不提供精确定位' : '原样本[' + item.start_sample + ', ' + item.end_sample_exclusive + ')'}；${item.score == null ? '未提供模型分数' : '模型原始分数 ' + item.score + '（非患病概率）'}；依据：${item.source_id}`)] : [];
  const image = run.value.result.image_analysis;
  const imageFindings = image ? ["原始影像候选草稿，待医生在原像素上复核（单张影像，不代表整次检查）：", `原记录 ${image.asset_id}；像素哈希 ${image.pixel_hash}；实际分析区域 ${JSON.stringify(image.processing.analysis_region)}`, ...image.findings.map(item => `${item.label}\n${item.description}\n位置：${item.location === "image" ? "图像级，未提供病灶定位" : JSON.stringify(item.region)}；${item.score == null ? "未提供模型分数" : "模型原始分数 " + item.score + "（非患病概率）"}；依据：${item.source_id}`)] : [];
  const text = [run.value.result.summary, ...run.value.result.sections.map(item => `${item.title}\n${item.content}`), ...segments, ...ecgFindings, ...imageFindings].join("\n\n");
  try { await navigator.clipboard.writeText(text); ElMessage.success("草稿已复制，请核对后使用"); } catch { ElMessage.info("当前环境无法自动复制，请选中结果文本复制"); }
}
async function submitFeedback() { await reviewAIRun(run.value.run_id, feedback.value); feedbackDialog.value = false; feedback.value = { outcome: "accepted", comment: "" }; ElMessage.success("复核反馈已保存"); }
onMounted(async () => {
  loading.value = true;
  try { features.value = ((await getAIFeatures()).data || []).filter(item => !props.featureKeys.length || props.featureKeys.includes(item.key)); featureKey.value = features.value.some(item => item.key === props.initialFeature) ? props.initialFeature : features.value[0]?.key || ""; }
  finally { loading.value = false; }
});
onActivated(() => { if (busy.value) startPolling(); });
onDeactivated(() => { selectionVersion += 1; stopPolling(); });
onBeforeUnmount(() => { selectionVersion += 1; historyVersion += 1; formVersion += 1; pathwayOptionsVersion += 1; stopPolling(); });
</script>

<style scoped>
.feature-description { line-height: 1.8; color: #606266; margin-bottom: 16px; }
.spaced { margin-top: 14px; margin-bottom: 14px; }
.actions, .result-header { display: flex; flex-wrap: wrap; align-items: center; gap: 10px; margin-top: 14px; }
.result-header { margin-top: 0; }
.plain-text { white-space: pre-wrap; overflow-wrap: anywhere; font-family: inherit; line-height: 1.7; max-height: 60vh; overflow: auto; }
.result-section { border-top: 1px solid #ebeef5; padding-top: 10px; margin-top: 18px; }
.metadata { color: #909399; font-size: 12px; }
</style>
