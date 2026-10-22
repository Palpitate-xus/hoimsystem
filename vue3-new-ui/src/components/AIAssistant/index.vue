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
        <p v-if="needsSupport">本次只整理明确原来源 {{ supportReferences.support_source_id }}（{{ supportReferences.support_source_kind }}）及其原关联；补充JSON不能替换原类型、原标识或原量，不代表完整交班。</p><p v-if="supportFailure" role="alert">{{ supportFailure }}</p>
        <p v-if="sofaWasBound&&!needsSofa" role="alert">本次绑定SOFA原评估，须由超级管理员配置SOFA专用模式后再读取和计算。</p><p v-if="needsSofa">本任务只使用一件明确的完整24小时SOFA日评估或独立变化复核，逐源医生判读、记录协议、未知与假设分别保存；不使用旧观测窗。</p>
        <p v-if="needsRiskWindow">本任务使用明确选择的原住院观测窗；NEWS2/AKI/qSOFA模式另需核对明确原来源与适用性评估，补充文字或JSON不能填补原数据缺项。</p>
        <p v-if="props.initialInput?.audio_asset_id">本次绑定原录音 {{ props.initialInput?.audio_asset_id }}；以原登记资料核对患者与就诊，不能通过补充JSON替换。</p>
        <p v-if="props.initialInput?.ecg_asset_id">本次绑定原始心电 {{ props.initialInput?.ecg_asset_id }}；以原登记资料核对患者与就诊，不能通过补充JSON替换。</p>
        <p v-if="props.initialInput?.imaging_order_id">本次绑定真实影像申请 {{ props.initialInput?.imaging_order_id }}；原像素与患者须一致，不能通过补充JSON替换申请。</p>
        <el-alert v-if="!selected.enabled" type="info" :closable="false" title="此功能尚未面向业务启用，由超级管理员配置模型和验证状态。" class="spaced" />
        <el-form-item v-if="selected.scope === 'patient'" label="患者">
          <el-select v-model="patientId" :disabled="!!props.patientId" filterable remote :remote-method="searchPatients" placeholder="搜索有访问权限的患者" style="width: 100%">
            <el-option v-for="item in patients" :key="item.patient_id" :label="item.label" :value="item.patient_id" />
          </el-select>
        </el-form-item>
        <el-form-item v-if="selected.scope === 'patient' && patientId && !needsIncident" label="本次就诊">
          <el-select v-model="encounterRef" clearable :disabled="!!props.encounterRef" :placeholder="(needsRiskWindow || needsSofa) ? '选择原住院，不能按日期归入门诊或其他住院' : '选择门诊或住院记录；治疗路径推荐需要本次就诊'" style="width: 100%">
            <el-option v-for="item in encounterOptions" :key="item.encounter_ref" :label="item.label" :value="item.encounter_ref" />
          </el-select>
        </el-form-item>
        <el-form-item v-if="needsIncident" label="不良事件标识"><el-input v-model="incidentId" :disabled="!!props.initialInput?.adverse_event_id" maxlength="10" placeholder="明确选择本患者事件的正整数标识" /><p>事件未记录就诊关联，不能按上报日期推定属于某次门诊或住院。</p></el-form-item>
        <ai-audio-input v-if="needsAudio && patientId" v-model="audioAssetId" :patient-id="patientId" :encounter-ref="encounterRef" :locked="!!props.initialInput?.audio_asset_id" @availability="audioReady = $event" />
        <ai-ecg-input v-if="needsEcg && patientId" v-model="ecgAssetId" :patient-id="patientId" :encounter-ref="encounterRef" :locked="!!props.initialInput?.ecg_asset_id" @availability="ecgReady = $event" />
        <ai-observation-window-input v-if="needsRiskWindow && patientId" :patient-id="patientId" :admission-id="encounterRef" :initial-window-id="String(props.initialInput?.observation_window_id || '')" :disabled="submitting" @selection="riskWindowSelection = $event" @availability="riskWindowReady = $event" />
        <ai-news2-input v-if="needsNews2 && patientId && riskWindowReady && riskWindowSelection" :patient-id="patientId" :admission-id="encounterRef" :window-id="riskWindowSelection.observation_window_id" @selection="news2Selection = $event" @availability="news2Ready = $event" />
        <ai-aki-input v-if="needsAki && patientId && riskWindowReady && riskWindowSelection" :patient-id="patientId" :admission-id="encounterRef" :window-id="riskWindowSelection.observation_window_id" @selection="akiSelection = $event" @availability="akiReady = $event" />
        <ai-qsofa-input v-if="needsQsofa && patientId && riskWindowReady && riskWindowSelection" :patient-id="patientId" :admission-id="encounterRef" :window-id="riskWindowSelection.observation_window_id" @selection="qsofaSelection = $event" @availability="qsofaReady = $event" />
        <ai-sofa-input v-if="needsSofa && patientId && encounterRef" :patient-id="patientId" :admission-id="encounterRef" :initial-assessment-id="String(sofaInitialReferences.sofa_assessment_id||'')" :initial-change-assessment-id="String(sofaInitialReferences.sofa_change_assessment_id||'')" :locked="sofaWasBound" :disabled="submitting" :active="viewActive" @selection="sofaSelection=$event" @availability="sofaReady=$event" />
        <ai-image-input v-if="needsImage && patientId" v-model="imageAssetId" :patient-id="patientId" :encounter-ref="encounterRef" :locked-order-id="String(props.initialInput?.imaging_order_id || '')" :disabled="submitting" @select="selectImage" @availability="imageReady = $event" />
        <el-form-item v-if="needsPathway && patientId && !props.initialInput?.pathway_enrollment_id" label="院内路径（可选）">
          <el-select v-model="pathwayId" :disabled="!!props.initialInput?.pathway_id || pathwayOptionsLoading" :clearable="!props.initialInput?.pathway_id" filterable placeholder="选择待比选的院内路径；也可仅使用审核指南" style="width: 100%" aria-label="待比选院内路径"><el-option v-for="item in pathwayOptions.items || []" :key="item.pathway_id" :value="String(item.pathway_id)" :disabled="!item.reviewed_for_current_scope" :label="`${item.name} · #${item.pathway_id}${item.reviewed_for_current_scope ? '' : ' · 当前范围未审核'}`" /></el-select>
          <p>{{ pathwayOptions.scope_note }}</p>
        </el-form-item>
        <el-form-item v-if="needsPrescription && patientId" label="待核查处方">
          <el-select v-model="prescriptionId" :clearable="!props.initialInput?.prescription_id" :disabled="!!props.initialInput?.prescription_id" placeholder="选择实际处方" style="width: 100%"><el-option v-for="item in prescriptions" :key="item.prescription_id" :label="item.label" :value="item.prescription_id" /></el-select>
        </el-form-item>
        <coding-evidence-input v-if="needsCodingEvidence" :key="codingInputKey" :patient-id="patientId" :admission-id="encounterRef||null" :home-id="props.initialInput?.home_id??null" :initial-references="codingInitialReferences" :active="viewActive&&codingAuthorized" @scope-change="selectCodingScope" @selection="codingSelection=$event" @availability="codingReady=$event" @invalidate="invalidateCoding" />
        <p v-if="codingWasBound&&!needsCodingEvidence" role="alert">此入口绑定原病案首页或完整编码证据，须配置编码证据复核模式后重新核对。</p>
        <el-form-item v-if="needsCoding" label="编码检索词"><el-input v-model="codingQuery" maxlength="500" placeholder="已记录诊断、手术名称或已有编码；多个词用逗号分隔" /></el-form-item>
        <ai-forecast-input v-if="needsForecast" :initial-series-id="String(props.initialInput?.forecast_series_id || '')" @selection="forecastSelection = $event" @availability="forecastReady = $event" />
        <ai-roster-input v-if="needsRoster" :key="rosterInputKey" :department-id="serviceDepartment" :initial-references="rosterInitialReferences" :active="viewActive" @department-change="serviceDepartment=$event" @selection="rosterSelection=$event" @availability="rosterReady=$event" @invalidate="invalidateRoster" />
        <p v-if="rosterWasBound&&!needsRoster" role="alert">此入口绑定受审排班原计划，须配置本地排班模式后再核对，不能混入旧外部优化输入。</p>
        <ai-bed-input v-if="needsBed" :key="bedInputKey" :department-id="serviceDepartment" :ward-id="serviceWard" :initial-references="bedInitialReferences" :active="viewActive" @department-change="serviceDepartment=$event" @ward-change="serviceWard=$event" @selection="bedSelection=$event" @availability="bedReady=$event" @invalidate="invalidateBed" />
        <p v-if="bedWasBound&&!needsBed" role="alert">此入口绑定受审床位序列及明确预测期，须配置本地床位模式后重新核对。</p>
        <ai-supply-input v-if="needsSupply" :key="supplyInputKey" :item-kind="props.initialInput?.item_kind??null" :item-id="props.initialInput?.item_id??null" :initial-references="supplyInitialReferences" :active="viewActive" @scope-change="selectSupplyScope" @selection="supplySelection=$event" @availability="supplyReady=$event" @invalidate="invalidateSupply" />
        <p v-if="supplyWasBound&&!needsSupply" role="alert">此入口绑定真实物资或完整受审原量序列，须配置本地物资预测模式后重新核对。</p>
        <ai-inventory-input v-if="needsNativeInventory" :key="nativeInventoryInputKey" :item-kind="props.initialInput?.item_kind??null" :item-id="props.initialInput?.item_id??null" :initial-references="nativeInventoryInitialReferences" :active="viewActive" @scope-change="selectNativeInventoryScope" @selection="nativeInventorySelection=$event" @availability="nativeInventoryReady=$event" @invalidate="invalidateNativeInventory" />
        <p v-if="nativeInventoryWasBound&&!needsNativeInventory" role="alert">此会话已进入独立库存候选比较，须恢复该模式后重新核对完整场景。</p>
        <ai-surgery-input v-if="needsSurgery" :key="surgeryInputKey" :department-id="serviceDepartment" :pool-id="serviceSurgeryPool" :application-ids="surgeryApplicationIds" :initial-references="surgeryInitialReferences" :active="viewActive" @department-change="serviceDepartment=$event" @pool-change="serviceSurgeryPool=$event" @selection="surgerySelection=$event" @availability="surgeryReady=$event" @invalidate="invalidateSurgery" />
        <p v-if="(surgeryWasBound||surgeryCaseCohortBound)&&!needsSurgery" role="alert">此入口绑定原病例队列或完整受审场景，须配置本地手术排程模式并重新核对。</p>
        <template v-if="needsOperations && !needsForecast && !needsRoster && !rosterWasBound && !needsBed && !bedWasBound && !needsSurgery && !surgeryWasBound && !surgeryCaseCohortBound && !needsSupply && !supplyWasBound && !needsNativeInventory && !nativeInventoryWasBound">
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
          <el-form-item label="预约科室"><el-select v-model="serviceDepartment" clearable filterable :disabled="!!props.initialInput?.schedule_id" placeholder="可选：限定科室"><el-option v-for="item in serviceOptions.departments || []" :key="item.department_id" :value="item.department_id" :label="item.name" /></el-select></el-form-item>
          <el-form-item label="预约医生"><el-select v-model="serviceDoctor" clearable filterable :disabled="!!props.initialInput?.schedule_id" placeholder="可选：限定医生"><el-option v-for="item in serviceDoctors" :key="item.doctor_id" :value="item.doctor_id" :label="item.name" /></el-select></el-form-item>
          <el-form-item label="预约日期"><el-date-picker v-model="serviceDate" type="date" value-format="YYYY-MM-DD" :disabled="!!props.initialInput?.schedule_id" placeholder="默认查询明日至第6日" /></el-form-item>
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
            <p v-if="needsSupply">补充JSON和问题不参与固定预测；不能替换原物资、完整业务日、计数单位、参数或预测期。原件自由文字、身份与问题留在院内。</p><p v-if="needsSurgery">此处JSON和问题不参与固定排程输入，不能覆盖原病例、原资源、有限开始时刻或目标；问题与身份映射只留院内。</p><p v-if="needsBed">此处JSON不参与固定床位计算，不能覆盖受审原件、原钟点、预测期或容量；补充问题只留本地。</p><p v-if="needsRoster">此处JSON和补充问题不参与固定排班输入，不能覆盖受审计划、人员、约束、目标或场景容量；问题只留本地。</p><p v-if="needsSofa">此处JSON不参与SOFA输入，不能替换明确原评估、原住院、全部原清单或原基线。补充问题留在本地。</p><p v-if="needsSupport">补充JSON不参与单条原资料输入；原资料自由文字依据和补充问题留在本地核对。</p><p v-if="needsForecast">统计预测只使用所选冻结来源和7/14天跨度；此处JSON不参与计算，也不能改写来源、口径、时区或日计数。</p>
            <p v-if="needsRiskWindow">此处JSON不参与风险观测输入，不能覆盖患者、原住院、窗口、截止时点或原数值。</p>
            <el-input v-model="extraInput" type="textarea" :rows="4" placeholder="可选：专用适配器的结构化输入 JSON，由服务契约规定" class="spaced" />
          </el-collapse-item>
        </el-collapse>
        <el-alert v-if="needsCodingEvidence" type="info" :closable="false" title="仅复核明确原病案、编码绑定、对应字典和本地规则证据；模型主张须逐字引文核查，不提供官方DRG/DIP分组或支付结论。" class="spaced" />
        <el-alert v-else-if="needsSurgery" type="info" :closable="false" title="固定程序核对原病例与阶段资源声明，保留实际搜索界与未知资料；候选不自动写入排台。" class="spaced" />
        <el-alert v-else-if="needsBed" type="info" :closable="false" title="五项实占与流转目标独立核对，未来容量为审核情景；预测不决定个体收治、调床或出院。" class="spaced" />
        <el-alert v-else-if="needsRoster" type="info" :closable="false" title="固定优化程序核对受审完整场景，区分数学界、可行候选与最优性证明；候选不自动发布或修改号源。" class="spaced" />
        <el-alert v-else-if="needsForecast" type="info" :closable="false" title="本功能使用固定统计计算；Prompt仅用于来源审计，不由文本模型推测数值。" class="spaced" />
        <el-alert v-else-if="needsSupply" type="info" :closable="false" title="物资原量预测逐项展示六种固定方法与28个滚动原点评价；不推断潜在需求、不自动选最优模型或生成采购量。" class="spaced" />
        <el-alert v-else-if="needsSofa" type="info" :closable="false" title="SOFA固定六轴计算保留原量、部分范围和完整协议总分的区别；变化数值不提供脓毒症确诊、排除、概率或自动治疗。" class="spaced" />
        <el-alert v-else-if="needsQsofa" type="info" :closable="false" title="qSOFA逐项核对原床旁数据及医生当前回顾声明；不作为单一脓毒症筛查，不提供确诊、排除、概率或自动治疗。" class="spaced" />
        <el-alert v-else-if="needsAki" type="info" :closable="false" title="KDIGO AKI由固定代码核对所选资料；至少分期不表示未来概率、完整病程或自动处置，未达所选标准不等于排除AKI。" class="spaced" />
        <el-alert v-else-if="needsNews2" type="info" :closable="false" title="NEWS2使用固定规则计算；Prompt不改变分数。规则分类及小计下界不表示风险概率或自动处置。" class="spaced" />
        <el-alert v-else-if="selected.engine !== 'llm'" type="info" :closable="false" title="此能力通过专用模型处理，需要对应原始资料和已登记的适配服务。" class="spaced" />
        <div class="actions">
          <el-button v-if="selected.scope === 'patient'" :disabled="((codingLifecycle||codingWasBound)&&!codingModeReady)||((needsNativeInventory||nativeInventoryWasBound)&&!nativeInventoryModeReady)||((needsSupply||supplyWasBound)&&!supplyModeReady)||((needsSurgery||surgeryWasBound||surgeryCaseCohortBound)&&!surgeryModeReady)||((needsBed||bedWasBound)&&!bedModeReady)||((needsRoster||rosterWasBound)&&!rosterModeReady)||((needsSofa||sofaWasBound) && !sofaModeReady) || (needsSupport && !supportModeReady) || !patientId || patientLoading || pathwayOptionsLoading || (needsRiskWindow && !riskWindowReady) || (needsNews2 && !news2Ready) || (needsAki && !akiReady) || (needsQsofa && !qsofaReady) || (needsAudio && (!audioAssetId || !audioReady)) || (needsEcg && (!ecgAssetId || !ecgReady)) || (needsImage && (!imageAssetId || !imageOrderId || !imageReady))" @click="inspectContext">查看本次资料</el-button>
          <el-button v-if="needsOperations" :disabled="((codingLifecycle||codingWasBound)&&!codingModeReady)||((needsNativeInventory||nativeInventoryWasBound)&&!nativeInventoryModeReady)||((needsSupply||supplyWasBound)&&!supplyModeReady)||((needsSurgery||surgeryWasBound||surgeryCaseCohortBound)&&!surgeryModeReady)||((needsBed||bedWasBound)&&!bedModeReady)||((needsRoster||rosterWasBound)&&!rosterModeReady)||serviceOptionsLoading || (needsForecast && !forecastReady)" @click="inspectOperationalContext">查看本次运营资料</el-button>
          <el-button type="primary" :loading="submitting" :disabled="((codingLifecycle||codingWasBound)&&!codingModeReady)||((needsNativeInventory||nativeInventoryWasBound)&&!nativeInventoryModeReady)||((needsSupply||supplyWasBound)&&!supplyModeReady)||((needsSurgery||surgeryWasBound||surgeryCaseCohortBound)&&!surgeryModeReady)||((needsBed||bedWasBound)&&!bedModeReady)||((needsRoster||rosterWasBound)&&!rosterModeReady)||((needsSofa||sofaWasBound) && !sofaModeReady) || (needsSupport && !supportModeReady) || (needsRiskWindow && !riskWindowReady) || (needsNews2 && !news2Ready) || (needsAki && !akiReady) || (needsQsofa && !qsofaReady) || (needsForecast && !forecastReady) || busy || patientLoading || serviceOptionsLoading || pathwayOptionsLoading || (needsAudio && (!audioAssetId || !audioReady)) || (needsEcg && (!ecgAssetId || !ecgReady)) || (needsImage && (!imageAssetId || !imageOrderId || !imageReady)) || (!selected.enabled && !preview) || (selected.scope === 'patient' && !patientId) || (needsInventory && (!inventoryDrugs.length && !inventoryConsumables.length || serviceOptions.inventory_scope_available === false))" @click="submit">生成辅助建议</el-button>
          <el-button v-if="busy" @click="cancel">取消接收结果</el-button>
        </div>
      </template>
      <el-empty v-else-if="!loading" description="当前角色暂无可用 AI 能力" />
    </el-form>
    <rca-evidence-assistant v-if="dedicatedPanel==='rca'" :feature="configuredFeature||null" :feature-key="featureKey" :initial-input="props.initialInput" :patient-id="props.patientId" :encounter-ref="props.encounterRef" :event-id="props.rcaEventId" :expected-patient-id="props.rcaExpectedPatientId" :active="viewActive" />
    <charge-reconciliation-assistant v-else-if="dedicatedPanel==='charge'" :feature="configuredFeature||null" :feature-key="featureKey" :initial-input="props.initialInput" :patient-id="props.patientId" :encounter-ref="props.encounterRef" :active="viewActive" />
    <document-extraction-assistant v-else-if="dedicatedPanel==='document'" :feature="configuredFeature||null" :feature-key="featureKey" :initial-input="props.initialInput" :patient-id="props.patientId" :encounter-ref="props.encounterRef" :active="viewActive" />
    <satisfaction-assistant v-else-if="dedicatedPanel==='satisfaction'" :feature="configuredFeature||null" :feature-key="featureKey" :initial-input="props.initialInput" :patient-id="props.patientId" :encounter-ref="props.encounterRef" :active="viewActive" />

    <drug-label-assistant v-else-if="dedicatedPanel==='drug_label'" :feature="configuredFeature||null" :feature-key="featureKey" :initial-input="props.initialInput" :patient-id="props.patientId" :encounter-ref="props.encounterRef" :pharmaceutical-id="props.pharmaceuticalId" :active="viewActive" />

    <template v-if="!dedicatedLifecycle">
    <el-card v-if="run" shadow="never" class="spaced" aria-label="AI任务结果">
      <template #header><div class="result-header"><strong>{{ run.feature_name }}</strong><el-tag>{{ statuses[run.status] || run.status }}</el-tag><el-tag v-if="run.patient_id" type="info">患者 #{{ run.patient_id }}</el-tag><el-tag v-if="run.preview" type="warning">评估预览</el-tag><el-button v-if="busy" link @click="refreshRun">刷新状态</el-button></div></template>
      <el-alert v-if="busy" type="info" :closable="false" title="任务已保存，正在等待处理或生成结果。" />
      <el-alert v-if="run.status === 'failed'" type="error" :closable="false" :title="run.error_message || '生成失败，请联系管理员检查服务状态'" />
      <coding-findings v-if="run.feature_key==='drg_evidence_review'" :run="run" :expected-patient-id="patientId" :expected-admission-id="encounterRef||null" :expected-home-id="codingHome" :references="codingInitialReferences||codingSelection" :active="viewActive&&codingAuthorized" @inspect="inspectEvidence" />
      <ai-service-findings :findings="run.tool_findings" @inspect="inspectEvidence" />
      <ai-operational-findings v-if="!run.inventory_findings" :findings="run.operational_findings" @inspect="inspectEvidence" />
      <ai-forecast-findings v-if="run.feature_key === 'visit_forecast'" :findings="run.forecast_findings" :analysis="run.result?.forecast_analysis" @inspect="inspectEvidence" />
      <ai-incident-findings :findings="run.incident_findings" @inspect="inspectEvidence" />
      <ai-consultation-findings :findings="run.consultation_findings" @inspect="inspectEvidence" />
      <ai-adr-findings :findings="run.adr_findings" @inspect="inspectEvidence" />
      <ai-pathway-findings :findings="run.pathway_findings" @inspect="inspectEvidence" />
      <ai-nursing-findings :findings="run.nursing_findings" @inspect="inspectEvidence" />
      <ai-observation-findings v-if="!run.aki_findings && !run.qsofa_findings && !run.sofa_findings && !run.sofa_change_findings" :findings="run.observation_findings" :expected-patient-id="run.patient_id" :expected-admission-id="run.encounter_ref || encounterRef" @inspect="inspectEvidence" />
      <ai-news2-findings v-if="run.news2_findings" :source="run.news2_findings.news2_source" :scope="run.news2_findings.news2_assessment" :analysis="run.result?.news2_analysis" :expected-patient-id="run.patient_id" :expected-admission-id="run.encounter_ref || encounterRef" @inspect="inspectEvidence" />
      <ai-aki-findings v-if="run.aki_findings" :source="run.aki_findings.aki_source" :scope="run.aki_findings.aki_assessment" :analysis="run.result?.aki_analysis" :expected-patient-id="run.patient_id" :expected-admission-id="run.encounter_ref || encounterRef" @inspect="inspectEvidence" />
      <ai-support-findings v-if="run.support_findings" :findings="run.support_findings" :expected-patient-id="patientId" :expected-admission-id="encounterRef" :references="needsSupport ? supportReferences : null" :active="viewActive" @inspect="inspectEvidence" />
      <ai-roster-findings v-if="run.roster_findings" :findings="run.roster_findings" :analysis="run.result?.roster_analysis" :expected-department-id="serviceDepartment" :references="rosterInitialReferences||rosterSelection" :active="viewActive" @inspect="inspectEvidence" />
      <ai-supply-findings v-if="run.supply_findings" :run="run" :expected-item-kind="supplyScope?.item_kind??null" :expected-item-id="supplyScope?.item_id??null" :references="supplyInitialReferences||supplySelection" :active="viewActive" @inspect="inspectEvidence" />
      <ai-inventory-findings v-if="run.inventory_findings" :run="run" :expected-item-kind="nativeInventoryScope?.item_kind??null" :expected-item-id="nativeInventoryScope?.item_id??null" :references="nativeInventoryInitialReferences||nativeInventorySelection" :active="viewActive" @inspect="inspectEvidence" />
      <ai-surgery-findings v-if="run.surgery_findings" :run="run" :expected-department-id="serviceDepartment" :expected-pool-id="serviceSurgeryPool" :references="surgeryInitialReferences||surgerySelection" :active="viewActive" @inspect="inspectEvidence" />
      <ai-bed-findings v-if="run.bed_findings" :findings="run.bed_findings" :analysis="run.result?.bed_analysis" :expected-department-id="serviceDepartment" :expected-ward-id="serviceWard" :references="bedInitialReferences||bedSelection" :active="viewActive" @inspect="inspectEvidence" />
      <ai-sofa-findings v-if="run.sofa_findings || run.sofa_change_findings" :source="run.sofa_findings?.sofa_source || run.sofa_change_findings?.sofa_change_source" :scope="run.sofa_findings?.sofa_assessment || run.sofa_change_findings?.sofa_change_assessment" :analysis="run.result?.sofa_analysis || run.result?.sofa_change_analysis" :expected-patient-id="patientId" :expected-admission-id="encounterRef" :active="viewActive" @inspect="inspectEvidence" />
      <ai-qsofa-findings v-if="run.qsofa_findings" :source="run.qsofa_findings.qsofa_source" :scope="run.qsofa_findings.qsofa_assessment" :analysis="run.result?.qsofa_analysis" :expected-patient-id="run.patient_id" :expected-admission-id="run.encounter_ref || encounterRef" @inspect="inspectEvidence" />
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
        <div class="actions"><el-button v-if="!run.result?.transcription&&!codingLifecycle" @click="copyDraft">复制草稿</el-button><el-button @click="feedbackDialog = true">记录复核反馈</el-button></div>
        <p class="metadata">Prompt v{{ run.prompt_version }} · 模型配置 v{{ run.provider_revision }} · 输入/输出 {{ run.input_tokens }}/{{ run.output_tokens }} Token</p>
      </template>
    </el-card>

    <el-collapse class="spaced" @change="loadHistory">
      <el-collapse-item title="最近任务"><el-table :data="history" :empty-text="selected?.scope === 'patient' && !patientId ? '先选择患者查看相应任务' : '当前范围暂无历史任务'"><el-table-column prop="feature_name" label="功能" /><el-table-column prop="patient_id" label="患者ID" width="85" /><el-table-column label="状态" width="90"><template #default="{ row }">{{ statuses[row.status] || row.status }}</template></el-table-column><el-table-column prop="create_time" label="时间" /><el-table-column label="操作" width="80"><template #default="{ row }"><el-button link @click="openRun(row.run_id)">查看</el-button></template></el-table-column></el-table></el-collapse-item>
    </el-collapse>
    <el-dialog v-model="contextDialog" :title="needsOperations ? '本次提供给 AI 的运营资料' : '本次提供给 AI 的患者资料'" width="min(1000px, 96vw)">
      <el-alert type="info" :closable="false" title="资料保留时间和状态，缺失信息会单独标记。" />
      <ai-operational-findings v-if="needsOperations && !needsForecast && !needsRoster && !needsBed && !needsSurgery && !needsSupply && !needsNativeInventory" :findings="contextData?.context" @inspect="inspectPreviewEvidence" />
      <ai-forecast-findings v-if="needsForecast && contextDialog" :findings="contextData?.context" @inspect="inspectPreviewEvidence" />
      <ai-incident-findings v-if="needsIncident" :findings="contextData?.context" @inspect="inspectPreviewEvidence" />
      <ai-consultation-findings :findings="contextData?.context?.consultation_sources" @inspect="inspectPreviewEvidence" />
      <ai-adr-findings :findings="contextData?.context?.adr_sources" @inspect="inspectPreviewEvidence" />
      <ai-pathway-findings :findings="contextData?.context?.pathway_sources" @inspect="inspectPreviewEvidence" />
      <ai-nursing-findings :findings="contextData?.context?.nursing_source_review" @inspect="inspectPreviewEvidence" />
      <ai-observation-findings v-if="!contextData?.context?.aki_source && !contextData?.context?.qsofa_source" :findings="contextData?.context?.observation_window" :expected-patient-id="patientId" :expected-admission-id="encounterRef" @inspect="inspectPreviewEvidence" />
      <ai-news2-findings v-if="contextData?.context?.news2_source" :source="contextData.context.news2_source" :scope="contextData.context.news2_assessment" :expected-patient-id="patientId" :expected-admission-id="encounterRef" @inspect="inspectPreviewEvidence" />
      <ai-aki-findings v-if="contextData?.context?.aki_source" :source="contextData.context.aki_source" :scope="contextData.context.aki_assessment" :expected-patient-id="patientId" :expected-admission-id="encounterRef" @inspect="inspectPreviewEvidence" />
      <ai-support-findings v-if="needsSupport && contextDialog" :findings="contextData?.context" :expected-patient-id="patientId" :expected-admission-id="encounterRef" :references="supportReferences" :active="contextDialog && viewActive" @inspect="inspectPreviewEvidence" />
      <ai-qsofa-findings v-if="contextData?.context?.qsofa_source" :source="contextData.context.qsofa_source" :scope="contextData.context.qsofa_assessment" :expected-patient-id="patientId" :expected-admission-id="encounterRef" @inspect="inspectPreviewEvidence" />
      <ai-speech-findings v-if="contextDialog" :findings="contextData?.context" @inspect="inspectPreviewEvidence" />
      <ai-image-findings v-if="contextDialog" :findings="contextData?.context" @inspect="inspectPreviewEvidence" />
      <ai-ecg-findings v-if="contextDialog" :findings="contextData?.context" @inspect="inspectPreviewEvidence" />
      <template v-if="needsCodingEvidence"><coding-findings :context="contextData?.context" :expected-patient-id="patientId" :expected-admission-id="encounterRef||null" :expected-home-id="codingHome" :references="codingInitialReferences||codingSelection" :active="contextDialog&&viewActive&&codingAuthorized" @inspect="inspectPreviewEvidence" /><p>模型仅接收以下最小化公开证据；完整首页原件、身份映射和审核正文留在院内。补充问题按相同已知标识规则处理。</p><pre class="plain-text" aria-label="编码复核公开输入">{{ JSON.stringify(codingOutboundPreview,null,2) }}</pre></template>
      <template v-if="needsSupply"><ai-supply-findings :context="contextData?.context" :expected-item-kind="supplyScope?.item_kind??null" :expected-item-id="supplyScope?.item_id??null" :references="supplyInitialReferences||supplySelection" :active="contextDialog&&viewActive" @inspect="inspectPreviewEvidence" /><p>独立服务只接收以下匿名公开原量和明确期限；物资身份、原件自由文字、审核依据和补充问题留在院内。</p><pre class="plain-text" aria-label="物资预测匿名公开输入">{{ JSON.stringify(supplyOutboundPreview,null,2) }}</pre></template>
      <template v-if="needsNativeInventory"><ai-inventory-findings :context="contextData?.context" :expected-item-kind="nativeInventoryScope?.item_kind??null" :expected-item-id="nativeInventoryScope?.item_id??null" :references="nativeInventoryInitialReferences||nativeInventorySelection" :active="contextDialog&&viewActive" @inspect="inspectPreviewEvidence" /><p>独立服务只接收以下匿名公开情景；真实品种身份、完整私有原件、审核依据和补充问题保留在院内。</p><pre class="plain-text" aria-label="库存比较匿名公开输入">{{ JSON.stringify(nativeInventoryOutboundPreview,null,2) }}</pre></template>
      <template v-else-if="needsSurgery"><ai-surgery-findings :context="contextData?.context" :expected-department-id="serviceDepartment" :expected-pool-id="serviceSurgeryPool" :references="surgeryInitialReferences||surgerySelection" :active="contextDialog&&viewActive" @inspect="inspectPreviewEvidence" /><p>独立计算服务仅接收以下匿名公开投影；患者与资源映射、原依据及问题留在院内。</p><pre class="plain-text" aria-label="手术排程匿名公开输入">{{ JSON.stringify(surgeryOutboundPreview,null,2) }}</pre></template>
      <template v-else-if="needsBed"><ai-bed-findings :findings="contextData?.context" :expected-department-id="serviceDepartment" :expected-ward-id="serviceWard" :references="bedInitialReferences||bedSelection" :active="contextDialog&&viewActive" @inspect="inspectPreviewEvidence" /><p>以下为专用预测服务接收的公开原量及明确预测期；病区身份、原件自由文字、审核依据和补充问题留在本地。</p><pre class="plain-text" aria-label="床位预测公开输入">{{ JSON.stringify(bedOutboundPreview,null,2) }}</pre></template>
      <template v-else-if="needsRoster"><ai-roster-findings :findings="contextData?.context" :expected-department-id="serviceDepartment" :references="rosterInitialReferences||rosterSelection" :active="contextDialog&&viewActive" @inspect="inspectPreviewEvidence" /><p>以下为专用优化服务接收的脱敏公开场景；原人员身份、证照/可用性原文、自由依据和补充问题留在本地。</p><pre class="plain-text" aria-label="排班优化公开输入">{{ JSON.stringify(rosterOutboundPreview,null,2) }}</pre></template>
      <template v-else-if="needsCodingEvidence"></template>
      <template v-else-if="sofaOutboundPreview"><p>以下只展示本次专用服务接收的严格公开原量投影；完整冻结原件、原患者与住院标识、医生自由文字依据和补充问题留在本地，核对依据时另行展开。</p><pre class="plain-text" aria-label="SOFA模型公开输入">{{ JSON.stringify(sofaOutboundPreview,null,2) }}</pre><el-button v-for="item in contextData?.evidence||[]" :key="item.source_id" @click="inspectPreviewEvidence(item.source_id)">核对{{ item.title }}</el-button></template>
      <template v-else-if="needsSupport"><p>以下为本次提供给模型的公开原量与已审核知识；完整冻结原件、人工自由文字依据、患者/住院标识和补充问题留在本地，仅在核对依据时查看。</p><pre class="plain-text" aria-label="单条原资料模型公开输入">{{ JSON.stringify(supportOutboundPreview, null, 2) }}</pre></template>
      <el-collapse v-else-if="needsOperations"><el-collapse-item title="查看原始资料字段"><pre class="plain-text">{{ JSON.stringify(contextData, null, 2) }}</pre></el-collapse-item></el-collapse>
      <pre v-else class="plain-text">{{ JSON.stringify(contextData, null, 2) }}</pre>
    </el-dialog>
    <el-dialog v-model="evidenceDialog" title="核查引用依据" width="760px"><template v-if="evidence"><p><strong>{{ evidence.title }}</strong> {{ evidence.version ? '· ' + evidence.version : '' }}</p><p v-if="evidence.source_uri" class="plain-text">来源：{{ evidence.source_uri }}</p><p v-if="evidence.observed_at">记录时间：{{ evidence.observed_at }}</p><pre class="plain-text">{{ evidence.content }}</pre></template></el-dialog>
    <el-dialog v-model="feedbackDialog" title="人工复核反馈" width="540px"><el-radio-group v-model="feedback.outcome"><el-radio value="accepted">采纳</el-radio><el-radio value="rejected">驳回</el-radio><el-radio value="modified">修改后采纳</el-radio></el-radio-group><el-input v-model="feedback.comment" type="textarea" :rows="4" maxlength="2000" placeholder="说明核查结果或修改内容；反馈不会自动写入病历、处方或医嘱" class="spaced" /><template #footer><el-button @click="feedbackDialog = false">取消</el-button><el-button type="primary" @click="submitFeedback">保存反馈</el-button></template></el-dialog>
    </template>
  </div>
</template>

<script setup>
import { computed, defineAsyncComponent, onActivated, onBeforeUnmount, onDeactivated, onMounted, ref, watch } from "vue";
import { useStore } from "vuex";
import { ElMessage } from "element-plus";
import { cancelAIRun, createAIRun, getAIClinicalContext, getAIOperationalContext, getAIEncounters, getAIFeatures, getAIPatients, getAIPrescriptions, getAIPathwayOptions, getAIServiceOptions, getAIRun, getAIRuns, reviewAIRun } from "@/api/ai";
import { resolveAkiEvidence } from "@/api/aiAki";
import { resolveSupportEvidence, supportReferencesValid, verifySupportContext } from "@/api/aiSupportContext";
import { resolveSofaEvidence, sofaReferencesValid, verifySofaAnalysis, verifySofaChangeAnalysis, verifySofaContext } from "@/api/aiSofa";
import { supportCanonical, supportHash, supportId } from "@/api/inpatientSupport";
import {resolveRosterEvidence,rosterReferencesValid,verifyRosterAnalysis,verifyRosterContext} from "@/api/rosterPlans";
import {bedReferencesValid,resolveBedEvidence,verifyBedAnalysis,verifyBedContext} from "@/api/bedForecast";
import {resolveSurgeryEvidence,surgeryReferencesValid,verifySurgeryContext,verifySurgeryRun} from "@/api/ai/surgeryScenarios";
import {resolveSupplyEvidence,verifySupplyContext,verifySupplyRun,verifySupplyReceipt} from "@/api/ai/supplyResults";
import {resolveInventoryEvidence,verifyInventoryContext,verifyInventoryRun,verifyInventoryReceipt,inventoryRunHasNativeMarkers} from "@/api/ai/inventoryResults";
import {verifyCodingContext,verifyCodingRun,verifyCodingReceipt,resolveCodingEvidence,codingRunHasMarkers} from "@/api/ai/codingResults";
import {codingCaseReferencesValid,codingScopeValid} from "@/api/ai/codingEvidence";
import { resolveQsofaEvidence } from "@/api/aiQsofa";
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

const ChargeReconciliationAssistant=defineAsyncComponent(()=>import("@/components/ai/ChargeReconciliationAssistant.vue"));
const DocumentExtractionAssistant=defineAsyncComponent(()=>import("@/components/ai/DocumentExtractionAssistant.vue"));
const SatisfactionAssistant=defineAsyncComponent(()=>import("@/components/ai/SatisfactionAssistant.vue"));
const RcaEvidenceAssistant=defineAsyncComponent(()=>import('@/components/ai/RcaEvidenceAssistant.vue'));
const DrugLabelAssistant=defineAsyncComponent(()=>import("@/components/ai/DrugLabelAssistant.vue"));
const CodingEvidenceInput=defineAsyncComponent(()=>import("@/components/CodingEvidenceInput.vue"));
const CodingFindings=defineAsyncComponent(()=>import("@/components/ai/CodingFindings.vue"));
const AiRosterInput=defineAsyncComponent(()=>import("@/components/AIRosterInput/index.vue"));
const AiRosterFindings=defineAsyncComponent(()=>import("@/components/AIRosterFindings/index.vue"));
const AiBedInput=defineAsyncComponent(()=>import("@/components/AIBedInput/index.vue"));
const AiBedFindings=defineAsyncComponent(()=>import("@/components/AIBedFindings/index.vue"));
const AiInventoryInput=defineAsyncComponent(()=>import("@/components/InventoryInput.vue"));
const AiInventoryFindings=defineAsyncComponent(()=>import("@/components/ai/InventoryFindings.vue"));
const AiSupplyInput=defineAsyncComponent(()=>import("@/components/SupplyInput.vue"));
const AiSupplyFindings=defineAsyncComponent(()=>import("@/components/SupplyFindings.vue"));
const AiSurgeryInput=defineAsyncComponent(()=>import("@/components/AISurgeryInput.vue"));
const AiSurgeryFindings=defineAsyncComponent(()=>import("@/components/AISurgeryFindings.vue"));
const AiForecastInput = defineAsyncComponent(() => import("@/components/AIForecastInput/index.vue"));
const AiForecastFindings = defineAsyncComponent(() => import("@/components/AIForecastFindings/index.vue"));
const AiObservationWindowInput = defineAsyncComponent(() => import("@/components/AIObservationWindowInput/index.vue"));
const AiObservationFindings = defineAsyncComponent(() => import("@/components/AIObservationFindings/index.vue"));
const AiNews2Input = defineAsyncComponent(() => import("@/components/AINews2Input/index.vue"));
const AiNews2Findings = defineAsyncComponent(() => import("@/components/AINews2Findings/index.vue"));
const AiAkiInput = defineAsyncComponent(() => import("@/components/AIAkiInput/index.vue"));
const AiAkiFindings = defineAsyncComponent(() => import("@/components/AIAkiFindings/index.vue"));
const AiQsofaInput = defineAsyncComponent(() => import("@/components/AIQsofaInput/index.vue"));
const AiSupportFindings = defineAsyncComponent(() => import("@/components/AISupportFindings/index.vue"));
const AiSofaInput = defineAsyncComponent(() => import("@/components/AISofaInput/index.vue"));
const AiSofaFindings = defineAsyncComponent(() => import("@/components/AISofaFindings/index.vue"));
const AiQsofaFindings = defineAsyncComponent(() => import("@/components/AIQsofaFindings/index.vue"));

const props = defineProps({ featureKeys: { type: Array, default: () => [] }, initialFeature: { type: String, default: "" }, patientId: { type: Number, default: null }, encounterRef: { type: String, default: "" }, pharmaceuticalId: { type: Number, default: null }, rcaEventId:{default:null}, rcaExpectedPatientId:{default:undefined}, initialInput: { type: Object, default: () => ({}) } });
const store = useStore();
const hasInitial=key=>props.initialInput!==null&&typeof props.initialInput==='object'&&Object.prototype.hasOwnProperty.call(props.initialInput,key);
const canPreview = computed(() => Array.isArray(store.getters["user/permissions"])&&store.getters["user/permissions"].includes("super_admin"));
const statuses = { queued: "已排队", running: "生成中", succeeded: "待复核", failed: "失败", cancelled: "已取消" };
const loading = ref(false), submitting = ref(false), patientLoading = ref(false), features = ref([]), featureKey = ref("");
const patientId = ref(null), encounterRef = ref(""), prescriptionId = ref(null), patients = ref([]), encounters = ref([]), prescriptions = ref([]);
const question = ref(""), codingQuery = ref(""), extraInput = ref(""), preview = ref(false), run = ref(null), history = ref([]);
const contextDialog = ref(false), contextData = ref(null), evidenceDialog = ref(false), evidence = ref(null), feedbackDialog = ref(false), feedback = ref({ outcome: "accepted", comment: "" });
const configuredFeature = computed(() => features.value.find(item => item.key === featureKey.value));
const chargeWasBound=ref(false),chargeLifecycle=computed(()=>chargeWasBound.value||featureKey.value==='charge_reconciliation'||hasInitial('charge_case_id'));
watch([featureKey,()=>hasInitial('charge_case_id')],([key,bound])=>{if(key==='charge_reconciliation'||bound)chargeWasBound.value=true;},{immediate:true,flush:'sync'});
const documentWasBound=ref(false),documentLifecycle=computed(()=>documentWasBound.value||featureKey.value==='guideline_ingestion'||hasInitial('document_original_id'));
watch([featureKey,()=>hasInitial('document_original_id')],([key,bound])=>{if(key==='guideline_ingestion'||bound)documentWasBound.value=true;},{immediate:true,flush:'sync'});
const satisfactionWasBound=ref(false),satisfactionLifecycle=computed(()=>satisfactionWasBound.value||featureKey.value==='feedback_analysis'||hasInitial('satisfaction_case_id'));
watch([featureKey,()=>hasInitial('satisfaction_case_id')],([key,bound])=>{if(key==='feedback_analysis'||bound)satisfactionWasBound.value=true;},{immediate:true,flush:'sync'});
const drugLabelWasBound=ref(false),drugLabelLifecycle=computed(()=>drugLabelWasBound.value||featureKey.value==='drug_label_extraction'||hasInitial('drug_label_source_binding_id'));
watch([featureKey,()=>hasInitial('drug_label_source_binding_id')],([key,bound])=>{if(key==='drug_label_extraction'||bound)drugLabelWasBound.value=true;},{immediate:true,flush:'sync'});
const rcaWasBound=ref(false),rcaLifecycle=computed(()=>rcaWasBound.value||featureKey.value==='incident_rca'||hasInitial('rca_evidence_case_id'));
watch([featureKey,()=>hasInitial('rca_evidence_case_id')],([key,bound])=>{if(key==='incident_rca'||bound)rcaWasBound.value=true;},{immediate:true,flush:'sync'});
const dedicatedLifecycle=computed(()=>rcaLifecycle.value||chargeLifecycle.value||documentLifecycle.value||satisfactionLifecycle.value||drugLabelLifecycle.value);
const dedicatedPanel=ref(null);
watch([featureKey,()=>hasInitial('charge_case_id'),()=>hasInitial('document_original_id'),()=>hasInitial('satisfaction_case_id'),()=>hasInitial('drug_label_source_binding_id'),()=>hasInitial('rca_evidence_case_id')],([key,charge,document,satisfaction,drugLabel,rca])=>{const explicit={incident_rca:'rca',charge_reconciliation:'charge',guideline_ingestion:'document',feedback_analysis:'satisfaction',drug_label_extraction:'drug_label'}[key];if(explicit){dedicatedPanel.value=explicit;return;}const bound=[rca?'rca':null,charge?'charge':null,document?'document':null,satisfaction?'satisfaction':null,drugLabel?'drug_label':null].filter(Boolean);if(bound.length===1||!dedicatedPanel.value&&bound.length)dedicatedPanel.value=bound[0];},{immediate:true,flush:'sync'});
const selected = computed(() => dedicatedLifecycle.value?null:configuredFeature.value);
const needsRoster=computed(()=>featureKey.value==='roster_optimization'&&selected.value?.input_mode==='roster'),rosterSelection=ref(null),rosterReady=ref(false),rosterWasBound=ref(false),rosterInputKey=ref(0);
const rosterInitialReferences=computed(()=>props.initialInput?.roster_plan_id==null?null:{roster_plan_id:props.initialInput?.roster_plan_id});
watch(rosterInitialReferences,value=>{if(value)rosterWasBound.value=true;},{immediate:true,flush:'sync'});
const rosterOutboundPreview=computed(()=>({context:{roster_source:contextData.value?.context?.roster_source}}));
const rosterLifecycle=computed(()=>featureKey.value==='roster_optimization'||!!run.value?.roster_findings||!!contextData.value?.context?.roster_source);
const rosterAuthorized=computed(()=>viewActive.value&&!!store.state.user.accessToken&&(canPreview.value||(store.getters['user/permissions']||[]).some(role=>selected.value?.allowed_roles?.includes(role))));
const rosterModeReady=computed(()=>needsRoster.value&&rosterReady.value&&rosterReferencesValid(rosterSelection.value)&&(!rosterWasBound.value||rosterReferencesValid(rosterInitialReferences.value)&&supportCanonical(rosterInitialReferences.value)===supportCanonical(rosterSelection.value))&&viewActive.value&&!!store.state.user.accessToken&&(canPreview.value||(store.getters['user/permissions']||[]).some(role=>selected.value?.allowed_roles?.includes(role))&&selected.value?.validation_status==='validated'));
function invalidateRoster(){if(!rosterLifecycle.value)return;rosterSelection.value=null;rosterReady.value=false;selectionVersion++;historyVersion++;stopPolling();run.value=null;history.value=[];contextData.value=null;contextDialog.value=false;evidence.value=null;evidenceDialog.value=false;feedbackDialog.value=false;}
const needsBed=computed(()=>featureKey.value==='bed_forecast'&&selected.value?.input_mode==='bed'),bedSelection=ref(null),bedReady=ref(false),bedWasBound=ref(false),bedInputKey=ref(0);
const bedInitialReferences=computed(()=>props.initialInput?.bed_series_id==null?null:{bed_series_id:props.initialInput?.bed_series_id,horizon_days:props.initialInput?.horizon_days});
watch(bedInitialReferences,value=>{if(value)bedWasBound.value=true;},{immediate:true,flush:'sync'});
const bedOutboundPreview=computed(()=>({context:{bed_source:contextData.value?.context?.bed_source},horizon_days:contextData.value?.context?.bed_binding?.horizon_days}));
const bedLifecycle=computed(()=>featureKey.value==='bed_forecast'||!!run.value?.bed_findings||!!contextData.value?.context?.bed_source);
const bedAuthorized=computed(()=>viewActive.value&&!!store.state.user.accessToken&&(canPreview.value||(store.getters['user/permissions']||[]).some(role=>selected.value?.allowed_roles?.includes(role))));
const bedModeReady=computed(()=>needsBed.value&&bedReady.value&&bedReferencesValid(bedSelection.value)&&(!bedWasBound.value||bedReferencesValid(bedInitialReferences.value)&&supportCanonical(bedInitialReferences.value)===supportCanonical(bedSelection.value))&&bedAuthorized.value&&(canPreview.value||selected.value?.validation_status==='validated'));
function invalidateBed(){if(!bedLifecycle.value)return;bedSelection.value=null;bedReady.value=false;selectionVersion++;historyVersion++;stopPolling();run.value=null;history.value=[];contextData.value=null;contextDialog.value=false;evidence.value=null;evidenceDialog.value=false;feedbackDialog.value=false;}
const needsSurgery=computed(()=>featureKey.value==='surgery_scheduling'&&selected.value?.input_mode==='surgery'),surgerySelection=ref(null),surgeryReady=ref(false),surgeryWasBound=ref(false),surgeryInputKey=ref(0);
const surgeryInitialReferences=computed(()=>props.initialInput?.surgery_scenario_id==null?null:{surgery_scenario_id:props.initialInput?.surgery_scenario_id});
const surgeryApplicationIds=computed(()=>{const plural=props.initialInput?.surgery_application_ids,single=props.initialInput?.surgery_application_id,ids=plural??(single?[single]:null);return Array.isArray(ids)&&ids.length>0&&ids.length<=256&&ids.every(supportId)&&new Set(ids).size===ids.length&&(single==null||ids.length===1&&ids[0]===single)?[...ids].sort():null;});
const surgeryCaseCohortBound=computed(()=>featureKey.value==='surgery_scheduling'&&(props.initialInput?.surgery_application_ids!=null||props.initialInput?.surgery_application_id!=null));
const surgeryCohortValid=computed(()=>!surgeryCaseCohortBound.value||surgeryApplicationIds.value!==null);
const surgeryCohortMatches=(scope,ids=surgeryApplicationIds.value,valid=surgeryCohortValid.value)=>valid&&(ids===null||Array.isArray(scope?.snapshot?.request?.cases)&&supportCanonical(scope.snapshot.request.cases.map(item=>item.application_id).sort())===supportCanonical(ids));
watch(surgeryInitialReferences,value=>{if(value)surgeryWasBound.value=true;},{immediate:true,flush:'sync'});
const surgeryOutboundPreview=computed(()=>({context:{surgery_source:contextData.value?.context?.surgery_source}}));
const surgeryLifecycle=computed(()=>featureKey.value==='surgery_scheduling'||!!run.value?.surgery_findings||!!contextData.value?.context?.surgery_source);
const surgeryAuthorized=computed(()=>viewActive.value&&!!store.state.user.accessToken&&(canPreview.value||(store.getters['user/permissions']||[]).some(role=>selected.value?.allowed_roles?.includes(role))));
const surgeryModeReady=computed(()=>needsSurgery.value&&surgeryCohortValid.value&&surgeryReady.value&&surgeryReferencesValid(surgerySelection.value)&&(!surgeryWasBound.value||surgeryReferencesValid(surgeryInitialReferences.value)&&supportCanonical(surgeryInitialReferences.value)===supportCanonical(surgerySelection.value))&&surgeryAuthorized.value&&(canPreview.value||selected.value?.validation_status==='validated'));
function invalidateSurgery(){if(!surgeryLifecycle.value)return;surgerySelection.value=null;surgeryReady.value=false;selectionVersion++;historyVersion++;stopPolling();run.value=null;history.value=[];contextData.value=null;contextDialog.value=false;evidence.value=null;evidenceDialog.value=false;feedbackDialog.value=false;}
const needsCodingEvidence=computed(()=>featureKey.value==='drg_evidence_review'&&selected.value?.input_mode==='coding_evidence');
const codingSelection=ref(null),codingReady=ref(false),codingInputKey=ref(0),codingHome=ref(null);
const codingInitialReferences=computed(()=>hasInitial('coding_case_id')?{coding_case_id:props.initialInput?.coding_case_id}:null);
const codingWasBound=computed(()=>hasInitial('coding_case_id')||featureKey.value==='drg_evidence_review'&&hasInitial('home_id'));
const codingLifecycle=computed(()=>featureKey.value==='drg_evidence_review'||codingRunHasMarkers(run.value)||!!contextData.value?.context?.coding_binding);
const codingAuthorized=computed(()=>needsCodingEvidence.value&&viewActive.value&&!!store.state.user.accessToken&&(canPreview.value||(store.getters['user/permissions']||[]).some(role=>selected.value?.allowed_roles?.includes(role))));
const codingModeReady=computed(()=>codingAuthorized.value&&codingReady.value&&codingScopeValid({patient_id:patientId.value,admission_id:encounterRef.value,home_id:codingHome.value})&&codingCaseReferencesValid(codingSelection.value)&&(codingInitialReferences.value===null||codingCaseReferencesValid(codingInitialReferences.value)&&supportCanonical(codingInitialReferences.value)===supportCanonical(codingSelection.value))&&(selected.value?.enabled&&selected.value?.validation_status==='validated'||canPreview.value&&preview.value));
const codingOutboundPreview=computed(()=>({context:{coding_source:contextData.value?.context?.coding_source}}));
const codingHistoryScopeReady=computed(()=>codingScopeValid({patient_id:patientId.value,admission_id:encounterRef.value,home_id:props.initialInput?.home_id??codingHome.value})&&(codingInitialReferences.value===null||codingCaseReferencesValid(codingInitialReferences.value)));
const codingExpected=ticket=>({patientId:ticket.patient,admissionId:ticket.admission,homeId:ticket.codingHome,references:ticket.codingReferences});
function invalidateCoding(){if(!codingLifecycle.value&&!codingWasBound.value)return;codingSelection.value=null;codingReady.value=false;selectionVersion++;historyVersion++;stopPolling();run.value=null;history.value=[];contextData.value=null;contextDialog.value=false;evidence.value=null;evidenceDialog.value=false;feedbackDialog.value=false;}
function selectCodingScope(value){const home=value&&value.patient_id===patientId.value&&value.admission_id===encounterRef.value&&codingScopeValid(value)&&(props.initialInput?.home_id==null||value.home_id===props.initialInput?.home_id)?value.home_id:null;if(codingHome.value!==home){codingHome.value=home;invalidateCoding();}}
const needsNativeInventory=computed(()=>featureKey.value==='inventory_optimization'&&selected.value?.input_mode==='inventory');
const nativeInventorySelection=ref(null),nativeInventoryReady=ref(false),nativeInventoryInputKey=ref(0),nativeInventoryScope=ref(null);
const nativeInventoryReferencesValid=value=>value!==null&&typeof value==='object'&&!Array.isArray(value)&&supportCanonical(Object.keys(value))===supportCanonical(['inventory_scenario_id'])&&supportId(value.inventory_scenario_id);
const nativeInventoryScopeValid=value=>value!==null&&['pharmaceutical','consumable'].includes(value.item_kind)&&Number.isSafeInteger(value.item_id)&&value.item_id>0&&value.item_id<=2147483647&&value.scope==='hospital_inventory';
const nativeInventoryInitialReferences=computed(()=>props.initialInput?.inventory_scenario_id==null?null:{inventory_scenario_id:props.initialInput?.inventory_scenario_id});
const nativeInventoryProtocolBound=ref(false);
watch(()=>[needsNativeInventory.value,featureKey.value,props.initialInput?.inventory_scenario_id,nativeInventorySelection.value],()=>{if(featureKey.value==='inventory_optimization'&&(needsNativeInventory.value||hasInitial('inventory_scenario_id')||nativeInventorySelection.value!==null))nativeInventoryProtocolBound.value=true;},{immediate:true,flush:'sync'});
const nativeInventoryWasBound=computed(()=>featureKey.value==='inventory_optimization'&&nativeInventoryProtocolBound.value);
const nativeInventoryLifecycle=computed(()=>featureKey.value==='inventory_optimization'||!!run.value?.inventory_findings||!!contextData.value?.context?.inventory_source);
const nativeInventoryAuthorized=computed(()=>viewActive.value&&!!store.state.user.accessToken&&(canPreview.value||(store.getters['user/permissions']||[]).some(role=>selected.value?.allowed_roles?.includes(role))));
const nativeInventoryModeReady=computed(()=>needsNativeInventory.value&&nativeInventoryReady.value&&nativeInventoryScopeValid(nativeInventoryScope.value)&&nativeInventoryReferencesValid(nativeInventorySelection.value)&&(!nativeInventoryInitialReferences.value||nativeInventoryReferencesValid(nativeInventoryInitialReferences.value)&&supportCanonical(nativeInventoryInitialReferences.value)===supportCanonical(nativeInventorySelection.value))&&nativeInventoryAuthorized.value&&(canPreview.value&&preview.value||selected.value?.validation_status==='validated'));
const nativeInventoryOutboundPreview=computed(()=>({context:{inventory_source:contextData.value?.context?.inventory_source}}));
const nativeInventoryExpected=ticket=>({itemKind:ticket.inventoryScope?.item_kind,itemId:ticket.inventoryScope?.item_id,references:ticket.inventoryReferences});
function invalidateNativeInventory(){if(!nativeInventoryLifecycle.value)return;nativeInventorySelection.value=null;nativeInventoryReady.value=false;selectionVersion++;historyVersion++;stopPolling();run.value=null;history.value=[];contextData.value=null;contextDialog.value=false;evidence.value=null;evidenceDialog.value=false;feedbackDialog.value=false;}
function selectNativeInventoryScope(value){const next=nativeInventoryScopeValid(value)?{item_kind:value.item_kind,item_id:value.item_id,scope:'hospital_inventory'}:null;if(supportCanonical(next)!==supportCanonical(nativeInventoryScope.value)){nativeInventoryScope.value=next;invalidateNativeInventory();}}
const needsSupply=computed(()=>featureKey.value==='supply_forecast'&&selected.value?.input_mode==='supply');
const supplySelection=ref(null),supplyReady=ref(false),supplyWasBound=ref(false),supplyInputKey=ref(0),supplyScope=ref(null);
const supplyReferencesValid=value=>value!==null&&typeof value==='object'&&!Array.isArray(value)&&supportCanonical(Object.keys(value).sort())===supportCanonical(['horizon_days','supply_series_id'])&&supportId(value.supply_series_id)&&Number.isInteger(value.horizon_days)&&[7,14].includes(value.horizon_days);
const supplyScopeValid=value=>value!==null&&['pharmaceutical','consumable'].includes(value.item_kind)&&Number.isSafeInteger(value.item_id)&&value.item_id>0&&value.scope==='hospital_inventory';
const supplyInitialReferences=computed(()=>props.initialInput?.supply_series_id==null?null:{supply_series_id:props.initialInput?.supply_series_id,horizon_days:props.initialInput?.horizon_days});
watch(()=>[supplyInitialReferences.value,featureKey.value,props.initialInput?.item_kind,props.initialInput?.item_id],()=>{if(supplyInitialReferences.value||featureKey.value==='supply_forecast'&&(props.initialInput?.item_kind!=null||props.initialInput?.item_id!=null))supplyWasBound.value=true;},{immediate:true,flush:'sync'});
const supplyLifecycle=computed(()=>featureKey.value==='supply_forecast'||!!run.value?.supply_findings||!!contextData.value?.context?.supply_source);
const supplyAuthorized=computed(()=>viewActive.value&&!!store.state.user.accessToken&&(canPreview.value||(store.getters['user/permissions']||[]).some(role=>selected.value?.allowed_roles?.includes(role))));
const supplyModeReady=computed(()=>needsSupply.value&&supplyReady.value&&supplyScopeValid(supplyScope.value)&&supplyReferencesValid(supplySelection.value)&&(!supplyInitialReferences.value||supplyReferencesValid(supplyInitialReferences.value)&&supportCanonical(supplyInitialReferences.value)===supportCanonical(supplySelection.value))&&supplyAuthorized.value&&(canPreview.value||selected.value?.validation_status==='validated'));
const supplyOutboundPreview=computed(()=>({context:{supply_source:contextData.value?.context?.supply_source},horizon_days:contextData.value?.context?.supply_binding?.horizon_days}));
const supplyExpected=ticket=>({itemKind:ticket.supplyScope?.item_kind,itemId:ticket.supplyScope?.item_id,references:ticket.supplyReferences});
function invalidateSupply(){if(!supplyLifecycle.value&&!nativeInventoryLifecycle.value)return;supplySelection.value=null;supplyReady.value=false;selectionVersion++;historyVersion++;stopPolling();run.value=null;history.value=[];contextData.value=null;contextDialog.value=false;evidence.value=null;evidenceDialog.value=false;feedbackDialog.value=false;}
function selectSupplyScope(value){const next=supplyScopeValid(value)?{item_kind:value.item_kind,item_id:value.item_id,scope:'hospital_inventory'}:null;if(supportCanonical(next)!==supportCanonical(supplyScope.value)){supplyScope.value=next;invalidateSupply();}}
const needsSofa = computed(() => featureKey.value === "sepsis_risk" && selected.value?.input_mode === "sofa1"), sofaSelection=ref(null), sofaReady=ref(false), sofaWasBound=ref(false);
const sofaInitialReferences=computed(()=>Object.fromEntries(["sofa_assessment_id","sofa_change_assessment_id"].filter(key=>props.initialInput?.[key]!=null).map(key=>[key,props.initialInput?.[key]])));
watch(()=>supportCanonical(sofaInitialReferences.value),()=>{if(Object.keys(sofaInitialReferences.value).length)sofaWasBound.value=true;},{immediate:true,flush:"sync"});
const sofaLifecycle=computed(()=>featureKey.value==="sepsis_risk"||!!run.value?.sofa_findings||!!run.value?.sofa_change_findings||!!contextData.value?.context?.sofa_source||!!contextData.value?.context?.sofa_change_source);
const sofaModeReady=computed(()=>needsSofa.value&&sofaReady.value&&sofaReferencesValid(sofaSelection.value)&&(!sofaWasBound.value||sofaReferencesValid(sofaInitialReferences.value)&&supportCanonical(sofaInitialReferences.value)===supportCanonical(sofaSelection.value))&&!!patientId.value&&!!encounterRef.value&&!!store.state.user.accessToken&&viewActive.value&&(store.getters["user/permissions"]||[]).some(role=>selected.value?.allowed_roles?.includes(role)));
const sofaOutboundPreview=computed(()=>{const c=contextData.value?.context;return c?.sofa_source?{context:{sofa_source:c.sofa_source}}:c?.sofa_change_source?{context:{sofa_change_source:c.sofa_change_source}}:null;});
const needsRiskWindow = computed(() => !needsSofa.value && !sofaWasBound.value && ["deterioration_risk", "sepsis_risk", "aki_risk"].includes(featureKey.value)), riskWindowSelection = ref(null), riskWindowReady = ref(false);
const needsNews2 = computed(() => featureKey.value === "deterioration_risk" && selected.value?.input_mode === "news2"), news2Selection = ref(null), news2Ready = ref(false);
const needsAki = computed(() => featureKey.value === "aki_risk" && selected.value?.input_mode === "aki"), akiSelection = ref(null), akiReady = ref(false);
const needsQsofa = computed(() => featureKey.value === "sepsis_risk" && selected.value?.input_mode === "qsofa"), qsofaSelection = ref(null), qsofaReady = ref(false);
const supportWasBound = ref(false), supportFailure = ref(""), viewActive = ref(true);
const supportReferences = computed(() => ({ support_source_id: props.initialInput?.support_source_id, support_source_kind: props.initialInput?.support_source_kind }));
watch(() => [props.initialInput?.support_source_id, props.initialInput?.support_source_kind], values => { if (values.some(value => value != null)) supportWasBound.value = true; }, { immediate: true, flush: "sync" });
const needsSupport = computed(() => featureKey.value === "handover_summary" && supportWasBound.value);
// Every handover view can open a source-backed history row, including views
// without initial source references. Protect pending history reads as well.
const supportLifecycle = computed(() => featureKey.value === "handover_summary" || !!run.value?.support_findings || !!contextData.value?.context?.support_source);
const supportModeReady = computed(() => !needsSupport.value || supportReferencesValid(supportReferences.value) && !!patientId.value && !!encounterRef.value && !!store.state.user.accessToken && viewActive.value && (store.getters["user/permissions"] || []).some(role => selected.value?.allowed_roles?.includes(role)));
const supportOutboundPreview = computed(() => contextData.value?.context?.support_source ? { context: { scope: "inpatient_support_original", support_source: contextData.value.context.support_source, missing_data: contextData.value.context.missing_data }, evidence: contextData.value.evidence } : null);
const encounterOptions = computed(() => needsRiskWindow.value || needsSupport.value || needsSofa.value || sofaWasBound.value || codingLifecycle.value ? encounters.value.filter(item => item.kind === "inpatient") : encounters.value);
const needsPrescription = computed(() => ["interaction_review", "allergy_review", "dose_review", "antimicrobial_review"].includes(featureKey.value));
const needsCoding = computed(() => ["icd_candidates"].includes(featureKey.value));
const needsAppointment = computed(() => featureKey.value === "appointment_assistant"), needsNavigation = computed(() => featureKey.value === "hospital_navigation");
const needsOperations = computed(() => selected.value?.scope === "hospital"), needsInventory = computed(() => !needsNativeInventory.value&&!nativeInventoryWasBound.value&&!needsSupply.value&&!supplyWasBound.value&&["supply_forecast", "inventory_optimization"].includes(featureKey.value));
const needsForecast = computed(() => featureKey.value === "visit_forecast"), forecastSelection = ref(null), forecastReady = ref(false);
const needsPlanning = computed(() => ["roster_optimization", "surgery_scheduling"].includes(featureKey.value));
const needsIncident = computed(() => featureKey.value === "incident_rca"), incidentId = ref("");
const needsAudio = computed(() => featureKey.value === "medical_transcription"), audioAssetId = ref(""), audioReady = ref(false);
const needsImage = computed(() => featureKey.value === "imaging_detection"), imageAssetId = ref(""), imageOrderId = ref(""), imageReady = ref(false);
function selectImage(id, asset) { imageOrderId.value = asset?.imaging_order_id || props.initialInput?.imaging_order_id || ""; }
const needsEcg = computed(() => featureKey.value === "ecg_analysis"), ecgAssetId = ref(""), ecgReady = ref(false);
const needsPathway = computed(() => ["treatment_pathway", "response_review"].includes(featureKey.value)), pathwayId = ref(null), pathwayOptions = ref({}), pathwayOptionsLoading = ref(false);
const boundPathwayLabels = { pathway_id: "院内路径", pathway_enrollment_id: "原入径记录" };
const boundPathwayReferences = computed(() => Object.entries(boundPathwayLabels).filter(([key]) => props.initialInput?.[key] != null).map(([key, label]) => `${label} #${props.initialInput?.[key]}`));
const boundReferenceLabels = { referral_id: "转诊", mdt_id: "MDT", reaction_id: "ADR上报" };
const boundClinicalReferences = computed(() => Object.entries(boundReferenceLabels).filter(([key]) => props.initialInput?.[key] != null).map(([key, label]) => `${label} #${props.initialInput?.[key]}`));
const boundNursingLabels = { nursing_assessment_id: "原护理评估", nursing_plan_id: "原护理计划", critical_care_record_id: "原危重护理记录", icu_score_id: "原人工评分" };
const boundNursingReferences = computed(() => Object.entries(boundNursingLabels).filter(([key]) => props.initialInput?.[key] != null).map(([key, label]) => `${label} #${props.initialInput?.[key]}`));
const operationsRange = ref([]), operationsPlanRange = ref([]), inventoryDrugs = ref([]), inventoryConsumables = ref([]), serviceOptionsLoading = ref(false);
const serviceOptions = ref({}), serviceDepartment = ref(null), serviceSurgeryPool=ref(null), serviceWard = ref(null), serviceDoctor = ref(null), serviceDate = ref(""), navigationStart = ref(null), navigationEnd = ref(null);
const serviceDoctors = computed(() => (serviceOptions.value.doctors || []).filter(item => !serviceDepartment.value || item.department_id === serviceDepartment.value));
const busy = computed(() => ["queued", "running"].includes(run.value?.status));
let timer = null, pollVersion = 0, formVersion = 0, patientLoadVersion = 0, historyVersion = 0, selectionVersion = 0, historyOpen = false, pathwayOptionsVersion = 0;

function supportIdentity() { return JSON.stringify([codingSelection.value,codingInitialReferences.value,codingHome.value,props.initialInput?.home_id,nativeInventorySelection.value,nativeInventoryInitialReferences.value,nativeInventoryScope.value,supplySelection.value,supplyInitialReferences.value,supplyScope.value,featureKey.value, patientId.value, encounterRef.value, supportReferences.value, selected.value?.input_mode, sofaSelection.value, sofaInitialReferences.value, rosterSelection.value,rosterInitialReferences.value,bedSelection.value,bedInitialReferences.value,surgerySelection.value,surgeryInitialReferences.value,surgeryApplicationIds.value,surgeryCaseCohortBound.value,surgeryCohortValid.value,serviceDepartment.value,serviceSurgeryPool.value,serviceWard.value,(codingLifecycle.value||rosterLifecycle.value||bedLifecycle.value||surgeryLifecycle.value||supplyLifecycle.value||nativeInventoryLifecycle.value)?selected.value:null,store.state.user.username,store.state.user.accessToken, store.getters["user/permissions"]]); }
function captureSupport(requireSofaSelection=false) { return {codingMode:needsCodingEvidence.value,codingBound:codingWasBound.value,codingHome:codingHome.value,codingReferences:codingInitialReferences.value||codingSelection.value?{...(codingInitialReferences.value||codingSelection.value)}:null,inventoryMode:needsNativeInventory.value,inventoryBound:nativeInventoryWasBound.value,inventoryScope:nativeInventoryScope.value?{...nativeInventoryScope.value}:null,inventoryReferences:nativeInventoryInitialReferences.value||nativeInventorySelection.value?{...(nativeInventoryInitialReferences.value||nativeInventorySelection.value)}:null,supplyMode:needsSupply.value,supplyBound:supplyWasBound.value,supplyScope:supplyScope.value?{...supplyScope.value}:null,supplyReferences:supplyInitialReferences.value||supplySelection.value?{...(supplyInitialReferences.value||supplySelection.value)}:null,surgeryMode:needsSurgery.value,surgeryBound:surgeryWasBound.value||surgeryCaseCohortBound.value,surgeryCohortValid:surgeryCohortValid.value,surgeryApplications:surgeryApplicationIds.value?[...surgeryApplicationIds.value]:null,pool:serviceSurgeryPool.value,surgeryReferences:surgeryInitialReferences.value||surgerySelection.value?{...(surgeryInitialReferences.value||surgerySelection.value)}:null,bedMode:needsBed.value,bedBound:bedWasBound.value,ward:serviceWard.value,bedReferences:bedInitialReferences.value||bedSelection.value?{...(bedInitialReferences.value||bedSelection.value)}:null,rosterMode:needsRoster.value,rosterBound:rosterWasBound.value,department:serviceDepartment.value,rosterReferences:rosterInitialReferences.value||rosterSelection.value?{...(rosterInitialReferences.value||rosterSelection.value)}:null, sofaMode:needsSofa.value, sofaBound:sofaWasBound.value, sofaReferences:sofaWasBound.value?{...sofaInitialReferences.value}:requireSofaSelection&&sofaSelection.value?{...sofaSelection.value}:null, key: supportIdentity(), version: selectionVersion, mode: needsSupport.value, patient: patientId.value, admission: encounterRef.value, references: needsSupport.value ? { ...supportReferences.value } : null }; }
const supportCurrent = ticket => !dedicatedLifecycle.value && viewActive.value && ticket.version === selectionVersion && ticket.key === supportIdentity();
watch(dedicatedLifecycle,value=>{if(!value)return;selectionVersion++;historyVersion++;patientLoadVersion++;formVersion++;stopPolling();run.value=null;history.value=[];contextData.value=null;contextDialog.value=false;evidence.value=null;evidenceDialog.value=false;feedbackDialog.value=false;patients.value=[];encounters.value=[];prescriptions.value=[];patientId.value=null;encounterRef.value='';prescriptionId.value=null;question.value='';extraInput.value='';preview.value=false;},{flush:'sync'});

async function acceptSupportRun(value, ticket) {
  if(ticket.codingMode||ticket.codingBound||codingRunHasMarkers(value)){
    if(!supportCurrent(ticket))return false;
    const valid=codingAuthorized.value&&ticket.codingMode&&codingScopeValid({patient_id:ticket.patient,admission_id:ticket.admission,home_id:ticket.codingHome})&&await verifyCodingRun(value,codingExpected(ticket),{current:()=>supportCurrent(ticket),auditOnly:false});
    if(!supportCurrent(ticket))return false;
    if(!valid){clearUnavailableSupport(ticket,'编码任务、原患者住院首页、完整证据或逐字引文无法核对，已拒绝展示。');return false;}
  }
  const hasInventory=inventoryRunHasNativeMarkers(value);
  if(ticket.inventoryMode||ticket.inventoryBound||hasInventory){
    if(!supportCurrent(ticket))return false;
    const valid=nativeInventoryAuthorized.value&&ticket.inventoryMode&&await verifyInventoryRun(value,nativeInventoryExpected(ticket),{current:()=>supportCurrent(ticket),auditOnly:false});
    if(!supportCurrent(ticket))return false;
    if(!valid){clearUnavailableSupport(ticket,'库存任务、原品种、完整候选、共同约束或固定计算结果无法核对，已拒绝展示。');return false;}
  }
  const hasSupply=!!value?.supply_findings||!!value?.result?.supply_analysis||!!value?.frozen_request?.payload?.context?.supply_binding;
  if(ticket.supplyMode||ticket.supplyBound||hasSupply){
    if(!supportCurrent(ticket))return false;
    const valid=supplyAuthorized.value&&ticket.supplyMode&&await verifySupplyRun(value,supplyExpected(ticket),{current:()=>supportCurrent(ticket),auditOnly:false});
    if(!supportCurrent(ticket))return false;
    if(!valid){clearUnavailableSupport(ticket,'物资任务、真实品种、完整原量、明确期限或固定结果无法核对，已拒绝展示。');return false;}
  }
  const hasSurgery=!!value?.surgery_findings||!!value?.result?.surgery_analysis;
  if(ticket.surgeryMode||ticket.surgeryBound||hasSurgery){
    if(!supportCurrent(ticket))return false;
    const valid=surgeryAuthorized.value&&ticket.surgeryMode&&surgeryCohortMatches(value?.surgery_findings?.surgery_scenario,ticket.surgeryApplications,ticket.surgeryCohortValid)&&await verifySurgeryRun(value,{departmentId:ticket.department,poolId:ticket.pool,references:ticket.surgeryReferences});
    if(!supportCurrent(ticket))return false;
    if(!valid){clearUnavailableSupport(ticket,'手术任务、完整来源、原资源池或固定计算绑定不一致，已拒绝展示。');return false;}
  }
  const hasBed=!!value?.bed_findings||!!value?.result?.bed_analysis;
  if(ticket.bedMode||ticket.bedBound||hasBed){
    if(!supportCurrent(ticket))return false;
    let valid=bedAuthorized.value&&ticket.bedMode&&Object.hasOwn(statuses,value?.status)&&value?.feature_key==='bed_forecast'&&value.patient_id===null&&value.encounter_ref===null&&!!value.bed_findings?.bed_binding&&!['roster_findings','sofa_findings','sofa_change_findings','qsofa_findings','support_findings','aki_findings','news2_findings','observation_findings','audio_findings','image_findings','ecg_findings'].some(key=>value[key])&&!['roster_analysis','sofa_analysis','sofa_change_analysis','qsofa_analysis','aki_analysis','news2_analysis','image_analysis','ecg_analysis','transcription'].some(key=>value.result?.[key])&&await verifyBedContext(value.bed_findings,ticket.department,ticket.ward,ticket.bedReferences);
    if(valid&&value.status==='succeeded')valid=!!value.result?.bed_analysis&&value.result.bed_analysis.horizon_days===value.bed_findings.bed_binding.horizon_days&&await verifyBedAnalysis(value.bed_findings.bed_source,value.result.bed_analysis,value.bed_findings.bed_series.projection_hash,value.bed_findings.bed_binding.horizon_days);
    if(!supportCurrent(ticket))return false;
    if(!valid){clearUnavailableSupport(ticket,'床位任务与当前病区、原序列、明确预测期或完整固定结果不一致，已拒绝展示。');return false;}
  }
  const hasRoster=!!value?.roster_findings||!!value?.result?.roster_analysis;
  if(ticket.rosterMode||ticket.rosterBound||hasRoster){
    if(!supportCurrent(ticket))return false;
    let valid=rosterAuthorized.value&&ticket.rosterMode&&Object.hasOwn(statuses,value?.status)&&value?.feature_key==='roster_optimization'&&value.patient_id===null&&value.encounter_ref===null&&!['sofa_findings','sofa_change_findings','qsofa_findings','support_findings','aki_findings','news2_findings','observation_findings','audio_findings','image_findings','ecg_findings'].some(key=>value[key])&&!['sofa_analysis','sofa_change_analysis','qsofa_analysis','aki_analysis','news2_analysis','image_analysis','ecg_analysis','transcription'].some(key=>value.result?.[key])&&await verifyRosterContext(value.roster_findings,ticket.department,ticket.rosterReferences);
    if(valid&&value.status==='succeeded')valid=!!value.result?.roster_analysis&&await verifyRosterAnalysis(value.roster_findings.roster_source,value.result.roster_analysis,value.roster_findings.roster_plan.projection_hash);
    if(!supportCurrent(ticket))return false;if(!valid){clearUnavailableSupport(ticket,'排班任务与当前科室、受审原计划、完整投影或固定结果绑定不一致，已拒绝展示。');return false;}
  }
  const hasSofa=!!value?.sofa_findings||!!value?.sofa_change_findings||!!value?.result?.sofa_analysis||!!value?.result?.sofa_change_analysis;
  if(ticket.sofaMode||ticket.sofaBound||hasSofa){
    if(!supportCurrent(ticket))return false;
    const daily=value?.sofa_findings,change=value?.sofa_change_findings,packet=daily||change,source=daily?.sofa_source||change?.sofa_change_source,scope=daily?.sofa_assessment||change?.sofa_change_assessment;
    let valid=ticket.sofaMode&&value?.feature_key==="sepsis_risk"&&value.patient_id===ticket.patient&&value.encounter_ref===ticket.admission&&!!daily!==!!change&&!value.qsofa_findings&&!value.aki_findings&&!value.news2_findings&&!value.observation_findings&&await verifySofaContext(packet,ticket.patient,ticket.admission,ticket.sofaReferences);
    if(valid&&value.status==="succeeded")valid=!!daily?!!value.result?.sofa_analysis&&!value.result?.sofa_change_analysis&&await verifySofaAnalysis(source,value.result.sofa_analysis,scope.projection_hash):!!value.result?.sofa_change_analysis&&!value.result?.sofa_analysis&&await verifySofaChangeAnalysis(source,value.result.sofa_change_analysis,scope.projection_hash);
    if(!supportCurrent(ticket))return false;
    if(!valid){clearUnavailableSupport(ticket,"SOFA任务与当前原住院、完整原件、固定模式或数值绑定不一致，已拒绝展示。");return false;}
  }
  if (!ticket.mode && !value?.support_findings) return true;
  if (!supportCurrent(ticket)) return false;
  const valid = value?.feature_key === "handover_summary" && value.patient_id === ticket.patient && value.encounter_ref === ticket.admission && await verifySupportContext(value.support_findings, ticket.patient, ticket.admission, ticket.references);
  if (!supportCurrent(ticket)) return false;
  if (!valid) { clearUnavailableSupport(ticket,"任务回执与明确原资料、原患者、原住院或公开原量不一致，已拒绝展示。"); return false; }
  return true;
}
function clearUnavailableSupport(ticket,message="当前无法重新核对原资料或访问，暂不展示旧任务。") { if(!supportCurrent(ticket))return; historyVersion++;history.value=[];run.value=null;contextData.value=null;contextDialog.value=false;evidence.value=null;evidenceDialog.value=false;feedbackDialog.value=false;supportFailure.value=message; }
function requestedRunMatches(value,id,ticket){if(value?.run_id===id)return true;if(supportCurrent(ticket)){clearUnavailableSupport(ticket,'完整任务与本次读取的原任务标识不同，已清除旧原件。');stopPolling();}return false;}
function stopPolling() { pollVersion += 1; clearTimeout(timer); timer = null; }
function startPolling() {
  stopPolling();
  if (!busy.value) return;
  const version = pollVersion, id = run.value.run_id;
  const poll = async () => {
    const supportTicket = captureSupport();
    try {
      const response = await getAIRun(id);
      if (version !== pollVersion || !requestedRunMatches(response.data,id,supportTicket) || !await acceptSupportRun(response.data, supportTicket) || version !== pollVersion) return;
      run.value = response.data;
      if (busy.value) timer = setTimeout(poll, 2000);
    } catch { if (version === pollVersion) { if(codingLifecycle.value||supportLifecycle.value||sofaLifecycle.value||rosterLifecycle.value||bedLifecycle.value||surgeryLifecycle.value||supplyLifecycle.value||nativeInventoryLifecycle.value)clearUnavailableSupport(supportTicket); stopPolling(); } }
  };
  timer = setTimeout(poll, 1200);
}
async function searchPatients(keyword = "") {
  if(dedicatedLifecycle.value)return;
  if (selected.value?.scope !== "patient" || needsSupport.value && !supportModeReady.value && !(store.getters["user/permissions"] || []).some(role => selected.value?.allowed_roles?.includes(role))) return;
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
  if(dedicatedLifecycle.value){question.value="";codingQuery.value="";extraInput.value="";return;}
  question.value = props.initialInput?.question || ""; codingQuery.value = props.initialInput?.icd_query || ""; extraInput.value = "";
  incidentId.value = props.initialInput?.adverse_event_id == null ? "" : String(props.initialInput?.adverse_event_id);
  pathwayId.value = props.initialInput?.pathway_id == null ? null : String(props.initialInput?.pathway_id);
  audioAssetId.value = props.initialInput?.audio_asset_id == null ? "" : String(props.initialInput?.audio_asset_id); audioReady.value = false;
  ecgAssetId.value = props.initialInput?.ecg_asset_id == null ? "" : String(props.initialInput?.ecg_asset_id); ecgReady.value = false;
  imageAssetId.value = props.initialInput?.image_asset_id == null ? "" : String(props.initialInput?.image_asset_id); imageOrderId.value = props.initialInput?.imaging_order_id || ""; imageReady.value = false;
  codingSelection.value=null;codingReady.value=false;codingHome.value=null;
  nativeInventorySelection.value=null;nativeInventoryReady.value=false;nativeInventoryScope.value=null;
  supplySelection.value=null;supplyReady.value=false;supplyScope.value=null;
  forecastSelection.value = null; forecastReady.value = false;
  riskWindowSelection.value = null; riskWindowReady.value = false;
  serviceOptions.value = {}; serviceDepartment.value = featureKey.value==='surgery_scheduling'?props.initialInput?.department_id??null:props.initialInput?.department_id||null;serviceSurgeryPool.value=featureKey.value==='surgery_scheduling'?props.initialInput?.surgery_pool_id??null:null; serviceWard.value=props.initialInput?.ward_id||null; serviceDoctor.value = props.initialInput?.doctor_id || null; serviceDate.value = props.initialInput?.appointment_date || "";
  navigationStart.value = props.initialInput?.start_node_id || null; navigationEnd.value = props.initialInput?.end_node_id || null;
  operationsRange.value = props.initialInput?.date_from && props.initialInput?.date_to ? [props.initialInput?.date_from, props.initialInput?.date_to] : []; inventoryDrugs.value = [...(props.initialInput?.drug_ids || [])]; inventoryConsumables.value = [...(props.initialInput?.consumable_ids || [])]; serviceOptionsLoading.value = false;
  operationsPlanRange.value = props.initialInput?.planning_date_from && props.initialInput?.planning_date_to ? [props.initialInput?.planning_date_from, props.initialInput?.planning_date_to] : [];
  if (selected.value?.scope === "patient") { await searchPatients(); if (featureVersion !== formVersion) return; patientId.value = props.patientId || (patients.value.length === 1 ? patients.value[0].patient_id : null); }
  if (needsNavigation.value || needsAppointment.value || (needsOperations.value && !needsForecast.value && !needsRoster.value && !rosterWasBound.value && !needsBed.value && !bedWasBound.value && !needsSurgery.value && !surgeryWasBound.value && !surgeryCaseCohortBound.value && !needsSupply.value && !supplyWasBound.value && !needsNativeInventory.value && !nativeInventoryWasBound.value)) {
    const version = formVersion; serviceOptionsLoading.value = true;
    try { const response = await getAIServiceOptions({ feature_key: featureKey.value }); if (version === formVersion) { serviceOptions.value = response.data || {}; if (needsOperations.value && !operationsRange.value?.length) operationsRange.value = serviceOptions.value.default_window || []; if (needsPlanning.value && !operationsPlanRange.value?.length) operationsPlanRange.value = serviceOptions.value.default_planning_window || []; } }
    finally { if (version === formVersion) serviceOptionsLoading.value = false; }
  }
});
watch(patientId, async id => {
  if(dedicatedLifecycle.value){patientLoading.value=false;return;}
  const patientVersion = ++patientLoadVersion;
  patientLoading.value = !!id;
  riskWindowSelection.value = null; riskWindowReady.value = false;
  stopPolling(); run.value = null;
  encounterRef.value = id && !needsIncident.value ? props.encounterRef || "" : ""; prescriptionId.value = id ? props.initialInput?.prescription_id || null : null; contextData.value = null; encounters.value = []; prescriptions.value = [];
  pathwayId.value = props.initialInput?.pathway_id == null ? null : String(props.initialInput?.pathway_id);
  audioAssetId.value = props.initialInput?.audio_asset_id == null ? "" : String(props.initialInput?.audio_asset_id); audioReady.value = false;
  ecgAssetId.value = props.initialInput?.ecg_asset_id == null ? "" : String(props.initialInput?.ecg_asset_id); ecgReady.value = false;
  imageAssetId.value = props.initialInput?.image_asset_id == null ? "" : String(props.initialInput?.image_asset_id); imageOrderId.value = props.initialInput?.imaging_order_id || ""; imageReady.value = false;
  if (needsIncident.value) { incidentId.value = props.initialInput?.adverse_event_id == null ? "" : String(props.initialInput?.adverse_event_id); patientLoading.value = false; return; }
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
watch(encounterRef, () => { if(codingLifecycle.value){codingHome.value=null;invalidateCoding();} sofaSelection.value=null;sofaReady.value=false;stopPolling(); run.value = null; contextData.value = null; riskWindowSelection.value = null; riskWindowReady.value = false; });
watch(()=>[selected.value?.input_mode,selected.value?.revision,selected.value?.provider_id,selected.value?.provider_revision,selected.value?.validation_status,selected.value?.enabled,supportCanonical(selected.value?.allowed_roles||[]),supportCanonical(codingInitialReferences.value),props.initialInput?.home_id],()=>{if(codingLifecycle.value||codingWasBound.value){codingInputKey.value++;codingHome.value=null;invalidateCoding();}},{flush:'sync'});
watch(()=>selected.value?.input_mode,()=>{sofaSelection.value=null;sofaReady.value=false;},{flush:"sync"});
watch(()=>selected.value?.input_mode,async(mode,previous)=>{if(dedicatedLifecycle.value)return;if(previous!=='roster'||mode==='roster'||featureKey.value!=='roster_optimization'||rosterWasBound.value)return;const version=++formVersion;serviceOptionsLoading.value=true;try{const response=await getAIServiceOptions({feature_key:featureKey.value});if(version!==formVersion||needsRoster.value||!viewActive.value)return;serviceOptions.value=response.data||{};if(!operationsRange.value.length)operationsRange.value=serviceOptions.value.default_window||[];if(!operationsPlanRange.value.length)operationsPlanRange.value=serviceOptions.value.default_planning_window||[];}finally{if(version===formVersion)serviceOptionsLoading.value=false;}},{flush:'post'});
watch(()=>[selected.value?.input_mode,selected.value?.revision,selected.value?.provider_id,selected.value?.provider_revision,selected.value?.validation_status,selected.value?.enabled,JSON.stringify(selected.value?.allowed_roles),serviceDepartment.value,supportCanonical(rosterInitialReferences.value)],()=>{if(rosterLifecycle.value){rosterInputKey.value++;invalidateRoster();}},{flush:'sync'});
watch(()=>selected.value?.input_mode,async(mode,previous)=>{if(dedicatedLifecycle.value)return;if(previous!=='bed'||mode==='bed'||featureKey.value!=='bed_forecast'||bedWasBound.value)return;const version=++formVersion;serviceOptionsLoading.value=true;try{const response=await getAIServiceOptions({feature_key:featureKey.value});if(version!==formVersion||needsBed.value||!viewActive.value)return;serviceOptions.value=response.data||{};if(!operationsRange.value.length)operationsRange.value=serviceOptions.value.default_window||[];}finally{if(version===formVersion)serviceOptionsLoading.value=false;}},{flush:'post'});
watch(()=>[selected.value?.input_mode,selected.value?.revision,selected.value?.provider_id,selected.value?.provider_revision,selected.value?.validation_status,selected.value?.enabled,JSON.stringify(selected.value?.allowed_roles),supportCanonical(bedInitialReferences.value)],()=>{if(bedLifecycle.value){bedInputKey.value++;invalidateBed();}},{flush:'sync'});
watch([serviceDepartment,serviceWard],()=>{if(bedLifecycle.value)invalidateBed();},{flush:'sync'});
watch(()=>props.initialInput?.department_id,value=>{if(surgeryLifecycle.value)serviceDepartment.value=value??null;else if(bedLifecycle.value)serviceDepartment.value=value||null;},{flush:'sync'});
watch(()=>props.initialInput?.surgery_pool_id,value=>{if(surgeryLifecycle.value)serviceSurgeryPool.value=value??null;},{flush:'sync'});
watch(()=>props.initialInput?.ward_id,value=>{if(bedLifecycle.value)serviceWard.value=value||null;},{flush:'sync'});
watch(()=>[selected.value?.input_mode,selected.value?.revision,selected.value?.provider_id,selected.value?.provider_revision,selected.value?.validation_status,selected.value?.enabled,supportCanonical(selected.value?.allowed_roles||[]),supportCanonical(surgeryInitialReferences.value)],()=>{if(surgeryLifecycle.value){surgeryInputKey.value++;invalidateSurgery();}},{flush:'sync'});
watch([serviceDepartment,serviceSurgeryPool],()=>{if(surgeryLifecycle.value)invalidateSurgery();},{flush:'sync'});
watch(()=>[supportCanonical(props.initialInput?.surgery_application_ids??null),props.initialInput?.surgery_application_id],()=>{if(surgeryLifecycle.value){surgeryInputKey.value++;invalidateSurgery();}},{flush:'sync'});
watch(()=>selected.value?.input_mode,async(mode,previous)=>{if(dedicatedLifecycle.value)return;if(previous!=='surgery'||mode==='surgery'||featureKey.value!=='surgery_scheduling'||surgeryWasBound.value)return;const version=++formVersion;serviceOptionsLoading.value=true;try{const response=await getAIServiceOptions({feature_key:featureKey.value});if(version!==formVersion||needsSurgery.value||!viewActive.value)return;serviceOptions.value=response.data||{};if(!operationsRange.value.length)operationsRange.value=serviceOptions.value.default_window||[];if(!operationsPlanRange.value.length)operationsPlanRange.value=serviceOptions.value.default_planning_window||[];}finally{if(version===formVersion)serviceOptionsLoading.value=false;}},{flush:'post'});
watch(()=>[selected.value?.input_mode,selected.value?.revision,selected.value?.provider_id,selected.value?.provider_revision,selected.value?.validation_status,selected.value?.enabled,supportCanonical(selected.value?.allowed_roles||[]),supportCanonical(nativeInventoryInitialReferences.value),props.initialInput?.item_kind,props.initialInput?.item_id],()=>{if(nativeInventoryLifecycle.value){nativeInventoryInputKey.value++;nativeInventoryScope.value=null;invalidateNativeInventory();}},{flush:'sync'});
watch(()=>selected.value?.input_mode,async(mode,previous)=>{if(dedicatedLifecycle.value)return;if(previous!=='inventory'||mode==='inventory'||featureKey.value!=='inventory_optimization'||nativeInventoryWasBound.value)return;const version=++formVersion;serviceOptionsLoading.value=true;try{const response=await getAIServiceOptions({feature_key:featureKey.value});if(version!==formVersion||needsNativeInventory.value||!viewActive.value)return;serviceOptions.value=response.data||{};if(!operationsRange.value.length)operationsRange.value=serviceOptions.value.default_window||[];}finally{if(version===formVersion)serviceOptionsLoading.value=false;}},{flush:'post'});
watch(()=>[selected.value?.input_mode,selected.value?.revision,selected.value?.provider_id,selected.value?.provider_revision,selected.value?.validation_status,selected.value?.enabled,supportCanonical(selected.value?.allowed_roles||[]),supportCanonical(supplyInitialReferences.value),props.initialInput?.item_kind,props.initialInput?.item_id],()=>{if(supplyLifecycle.value){supplyInputKey.value++;supplyScope.value=null;invalidateSupply();}},{flush:'sync'});
watch(()=>selected.value?.input_mode,async(mode,previous)=>{if(dedicatedLifecycle.value)return;if(previous!=='supply'||mode==='supply'||featureKey.value!=='supply_forecast'||supplyWasBound.value)return;const version=++formVersion;serviceOptionsLoading.value=true;try{const response=await getAIServiceOptions({feature_key:featureKey.value});if(version!==formVersion||needsSupply.value||!viewActive.value)return;serviceOptions.value=response.data||{};if(!operationsRange.value.length)operationsRange.value=serviceOptions.value.default_window||[];}finally{if(version===formVersion)serviceOptionsLoading.value=false;}},{flush:'post'});
watch([needsNews2, () => riskWindowSelection.value?.observation_window_id, () => riskWindowSelection.value?.content_hash, riskWindowReady], () => { news2Selection.value = null; news2Ready.value = false; });
watch([needsAki, () => riskWindowSelection.value?.observation_window_id, () => riskWindowSelection.value?.content_hash, riskWindowReady], () => { akiSelection.value = null; akiReady.value = false; });
watch([needsQsofa, () => riskWindowSelection.value?.observation_window_id, () => riskWindowSelection.value?.content_hash, riskWindowReady], () => { qsofaSelection.value = null; qsofaReady.value = false; });
watch([needsCodingEvidence,()=>supportCanonical(codingSelection.value),codingReady,codingHome,()=>supportCanonical(codingInitialReferences.value),needsNativeInventory,()=>supportCanonical(nativeInventorySelection.value),nativeInventoryReady,()=>supportCanonical(nativeInventoryInitialReferences.value),()=>supportCanonical(nativeInventoryScope.value),needsSupply,()=>supportCanonical(supplySelection.value),supplyReady,()=>supportCanonical(supplyInitialReferences.value),()=>supportCanonical(supplyScope.value),needsSurgery,()=>supportCanonical(surgerySelection.value),surgeryReady,()=>supportCanonical(surgeryInitialReferences.value),serviceSurgeryPool,needsBed,()=>JSON.stringify(bedSelection.value),bedReady,()=>JSON.stringify(bedInitialReferences.value),serviceWard,needsRoster,()=>JSON.stringify(rosterSelection.value),rosterReady,()=>JSON.stringify(rosterInitialReferences.value),needsSofa, () => JSON.stringify(sofaSelection.value), sofaReady, () => selected.value?.input_mode, needsQsofa, () => JSON.stringify(qsofaSelection.value), qsofaReady, needsAki, () => JSON.stringify(akiSelection.value), akiReady, needsNews2, () => JSON.stringify(news2Selection.value), news2Ready, () => JSON.stringify(riskWindowSelection.value), riskWindowReady, () => JSON.stringify(forecastSelection.value), forecastReady, featureKey, patientId, encounterRef, prescriptionId, incidentId, pathwayId, audioAssetId, ecgAssetId, imageAssetId, imageOrderId, serviceDepartment, serviceDoctor, serviceDate, navigationStart, navigationEnd, operationsRange, operationsPlanRange, () => inventoryDrugs.value.join(','), () => inventoryConsumables.value.join(','), () => JSON.stringify(props.initialInput)], () => {
  selectionVersion += 1; supportFailure.value = ""; stopPolling(); run.value = null; contextData.value = null; contextDialog.value = false; evidence.value = null; evidenceDialog.value = false; feedbackDialog.value = false;
});
let previewEvidenceVersion=0;
watch(contextDialog,visible=>{if(!visible){previewEvidenceVersion++;contextData.value=null;evidence.value=null;evidenceDialog.value=false;}},{flush:'sync'});
watch(evidenceDialog,visible=>{if(!visible)evidence.value=null;},{flush:'sync'});
watch(() => run.value?.run_id, () => { evidence.value=null; evidenceDialog.value = false; feedbackDialog.value = false; feedback.value = { outcome: "accepted", comment: "" }; });
watch(serviceDepartment, id => { const doctor = serviceOptions.value.doctors?.find(item => item.doctor_id === serviceDoctor.value); if (id && doctor && doctor.department_id !== id) serviceDoctor.value = null; });
watch([()=>codingLifecycle.value?supportCanonical(codingSelection.value):null,()=>codingLifecycle.value?codingHome.value:null,()=>nativeInventoryLifecycle.value?supportCanonical(nativeInventoryScope.value):null,()=>nativeInventoryLifecycle.value?supportCanonical(nativeInventorySelection.value):null,()=>supplyLifecycle.value?supportCanonical(supplyScope.value):null,()=>supplyLifecycle.value?supportCanonical(supplySelection.value):null,featureKey, patientId, encounterRef,()=>(rosterLifecycle.value||bedLifecycle.value||surgeryLifecycle.value||supplyLifecycle.value||nativeInventoryLifecycle.value)?serviceDepartment.value:null,()=>surgeryLifecycle.value?serviceSurgeryPool.value:null,()=>surgeryLifecycle.value?supportCanonical(surgerySelection.value):'',()=>bedLifecycle.value?serviceWard.value:null,()=>bedLifecycle.value?JSON.stringify(bedSelection.value):'',()=>rosterLifecycle.value?JSON.stringify(rosterSelection.value):'',()=>(rosterLifecycle.value||bedLifecycle.value||surgeryLifecycle.value||supplyLifecycle.value||nativeInventoryLifecycle.value)?JSON.stringify(selected.value):''], () => { historyVersion += 1; history.value = []; if (historyOpen) loadHistory(); });
watch(() => props.initialFeature, key => { if (features.value.some(item => item.key === key)) featureKey.value = key; });
watch(() => props.patientId, id => { formVersion += 1; patientId.value = dedicatedLifecycle.value?null:id; });
watch(() => props.encounterRef, value => { encounterRef.value = dedicatedLifecycle.value||needsIncident.value ? "" : value; });
watch(() => props.initialInput?.adverse_event_id, value => { incidentId.value = value == null ? "" : String(value); });
watch(() => props.initialInput?.pathway_id, value => { pathwayId.value = value == null ? null : String(value); });
watch(() => props.initialInput?.audio_asset_id, value => { audioAssetId.value = value == null ? "" : String(value); });
watch(audioReady, ready => { if (needsAudio.value && !ready) { stopPolling(); run.value = null; contextData.value = null; } });
watch(() => props.initialInput?.ecg_asset_id, value => { ecgAssetId.value = value == null ? "" : String(value); });
watch(() => props.initialInput?.image_asset_id, value => { imageAssetId.value = value == null ? "" : String(value); });
watch(imageReady, ready => { if (needsImage.value && !ready) { stopPolling(); run.value = null; contextData.value = null; } });
watch(ecgReady, ready => { if (needsEcg.value && !ready) { stopPolling(); run.value = null; contextData.value = null; } });
watch([featureKey, patientId, encounterRef], async () => {
  const version = ++pathwayOptionsVersion;
  pathwayOptions.value = {}; pathwayOptionsLoading.value = false;
  if (!needsPathway.value || !patientId.value || props.initialInput?.pathway_enrollment_id) return;
  pathwayOptionsLoading.value = true;
  try { const response = await getAIPathwayOptions({ feature_key: featureKey.value, patient_id: patientId.value, encounter_ref: encounterRef.value || undefined }); if (version === pathwayOptionsVersion) pathwayOptions.value = response.data || {}; }
  finally { if (version === pathwayOptionsVersion) pathwayOptionsLoading.value = false; }
}, { flush: "post" });
async function inspectContext() {
  if(dedicatedLifecycle.value)return;
  const input = buildTaskInput(); if (!input) return;
  const version = selectionVersion, supportTicket = captureSupport();
  const sourceKeys = needsSofa.value ? ["sofa_assessment_id","sofa_change_assessment_id"] : needsSupport.value ? ["support_source_id", "support_source_kind"] : needsRiskWindow.value ? ["observation_window_id", "news2_assessment_id", "aki_assessment_id", "qsofa_assessment_id"] : selected.value?.source_reference_keys || ["record_id", "structured_record_id", "prescription_id", "lab_result_id", "imaging_report_id"];
  const references = Object.fromEntries(sourceKeys.filter(key => input[key]).map(key => [key, input[key]]));
  let response; try { response = await getAIClinicalContext({ ...references, feature_key: featureKey.value, patient_id: patientId.value, encounter_ref: encounterRef.value || undefined }); } catch(failure) { if(codingLifecycle.value||supportLifecycle.value||sofaLifecycle.value||rosterLifecycle.value||bedLifecycle.value||surgeryLifecycle.value||supplyLifecycle.value||nativeInventoryLifecycle.value){clearUnavailableSupport(supportTicket);return;} throw failure; }
  if (version !== selectionVersion || !supportCurrent(supportTicket)) return;
  if(supportTicket.codingMode||response.data?.context&&['coding_binding','coding_source','coding_case'].some(k=>Object.hasOwn(response.data.context,k))){if(!supportTicket.codingMode||!await verifyCodingContext(response.data?.context,codingExpected(supportTicket),{current:()=>supportCurrent(supportTicket),auditOnly:false})){if(supportCurrent(supportTicket))clearUnavailableSupport(supportTicket,'编码完整证据、原患者住院首页或公开投影无法核对，不能预览。');return;}if(!supportCurrent(supportTicket))return;}
  if(supportTicket.sofaMode||response.data?.context?.sofa_source||response.data?.context?.sofa_change_source){if(!supportTicket.sofaMode||!await verifySofaContext(response.data?.context,supportTicket.patient,supportTicket.admission,sofaSelection.value)){if(supportCurrent(supportTicket))clearUnavailableSupport(supportTicket,"SOFA完整原件、公开投影或明确引用不一致，不能预览。");return;}if(!supportCurrent(supportTicket))return;}
  if (supportTicket.mode || response.data?.context?.support_source) { if (!supportTicket.mode || !await verifySupportContext(response.data?.context, supportTicket.patient, supportTicket.admission, supportTicket.references)) { if (supportCurrent(supportTicket)) { contextData.value = null; contextDialog.value = false; supportFailure.value = "本次原资料、公开原量或完整摘要绑定不一致，不能预览。"; } return; } if (!supportCurrent(supportTicket)) return; }
  contextData.value = response.data; contextDialog.value = true;
}
async function inspectOperationalContext() {
  if(dedicatedLifecycle.value)return;
  const input = buildTaskInput(); if (!input) return;
  const version = selectionVersion,ticket=captureSupport();
  let response;try{response=await getAIOperationalContext({feature_key:featureKey.value,input});}catch(failure){if(rosterLifecycle.value||bedLifecycle.value||surgeryLifecycle.value||supplyLifecycle.value||nativeInventoryLifecycle.value){clearUnavailableSupport(ticket);return;}throw failure;}
  if (version !== selectionVersion||!supportCurrent(ticket)) return;
  if(ticket.inventoryMode||response.data?.context?.inventory_source){if(!ticket.inventoryMode||!await verifyInventoryContext(response.data?.context,nativeInventoryExpected(ticket),{current:()=>supportCurrent(ticket),auditOnly:false})){if(supportCurrent(ticket))clearUnavailableSupport(ticket,'完整库存场景、原品种、共同约束或全部候选无法核对，不能预览。');return;}if(!supportCurrent(ticket))return;}
  if(ticket.supplyMode||response.data?.context?.supply_source){if(!ticket.supplyMode||!await verifySupplyContext(response.data?.context,supplyExpected(ticket),{current:()=>supportCurrent(ticket),auditOnly:false})){if(supportCurrent(ticket))clearUnavailableSupport(ticket,'物资完整原量、单位、参数、品种或明确期限无法核对，不能预览。');return;}if(!supportCurrent(ticket))return;}
  if(ticket.surgeryMode||response.data?.context?.surgery_source){if(!ticket.surgeryMode||!surgeryCohortMatches(response.data?.context?.surgery_scenario,ticket.surgeryApplications,ticket.surgeryCohortValid)||!await verifySurgeryContext(response.data?.context,{departmentId:ticket.department,poolId:ticket.pool,references:ticket.surgeryReferences})){if(supportCurrent(ticket))clearUnavailableSupport(ticket,'手术完整原件、资源池、公开投影或明确引用不一致，不能预览。');return;}if(!supportCurrent(ticket))return;}
  if(ticket.bedMode||response.data?.context?.bed_source){if(!ticket.bedMode||!response.data?.context?.bed_binding||!await verifyBedContext(response.data?.context,ticket.department,ticket.ward,ticket.bedReferences)){if(supportCurrent(ticket))clearUnavailableSupport(ticket,'床位完整原件、原病区、公开投影或明确预测期不一致，不能预览。');return;}if(!supportCurrent(ticket))return;}
  if(ticket.rosterMode||response.data?.context?.roster_source){if(!ticket.rosterMode||!await verifyRosterContext(response.data?.context,ticket.department,ticket.rosterReferences)){if(supportCurrent(ticket))clearUnavailableSupport(ticket,'排班完整原件、公开投影或明确引用不一致，不能预览。');return;}if(!supportCurrent(ticket))return;}
  contextData.value = response.data; contextDialog.value = true;
}
function buildTaskInput() {
  if(chargeLifecycle.value)throw new Error("收费核对须在独立完整账目面板提交");
  if(documentLifecycle.value)throw new Error("原文提取须在独立原件面板提交");
  if(satisfactionLifecycle.value)throw new Error("评价主题分析须在独立完整原件面板提交");
  if(needsCodingEvidence.value||codingWasBound.value||codingLifecycle.value){if(!codingModeReady.value){ElMessage.warning('请在编码证据复核模式下核对原患者、住院与首页，并明确选择一件当前完整受审证据');return;}return{...codingSelection.value,question:question.value};}
  if(needsNativeInventory.value||nativeInventoryWasBound.value){if(!nativeInventoryModeReady.value){ElMessage.warning('请在本地库存比较模式下明确选择真实品种与当前完整受审候选场景');return;}return{...nativeInventorySelection.value,question:question.value};}
  if(needsSupply.value||supplyWasBound.value){if(!supplyModeReady.value){ElMessage.warning('请在本地物资预测模式下明确选择真实品种、当前完整受审序列及7或14天期限');return;}return{...supplySelection.value,question:question.value};}
  if(needsSurgery.value||surgeryWasBound.value||surgeryCaseCohortBound.value){if(!surgeryModeReady.value){ElMessage.warning('请在本地手术排程模式下明确选择并重核一件当前完整受审场景');return;}return{...surgerySelection.value,question:question.value};}
  if(needsBed.value||bedWasBound.value){if(!bedModeReady.value){ElMessage.warning('请在本地床位模式下选择并重核当前受审序列，明确7或14日预测期');return;}return{...bedSelection.value,question:question.value};}
  if(needsRoster.value||rosterWasBound.value){if(!rosterModeReady.value){ElMessage.warning('请在本地排班模式下明确选择并重核一件当前受审排班计划');return;}return{...rosterSelection.value,question:question.value};}
  if(needsSofa.value||sofaWasBound.value){if(!sofaModeReady.value){ElMessage.warning("请在已配置的SOFA模式下明确选择并重核一件原日评估或变化评估及本次住院");return;}return{...sofaSelection.value,question:question.value};}
  if (needsSupport.value) { if (!supportModeReady.value) { ElMessage.warning("请从原资料入口明确选择合法的原类型、原标识及本次住院，并核对当前权限"); return; } return { ...supportReferences.value, question: question.value }; }
  if (needsRiskWindow.value) {
    if (!riskWindowReady.value || !riskWindowSelection.value || !encounterRef.value) { ElMessage.warning("请先选择并核对原住院观测窗"); return; }
    if (needsQsofa.value) {
      if (!qsofaReady.value || !qsofaSelection.value) { ElMessage.warning("请明确选择并核对qSOFA原点测、GCS与医生当前回顾性评估"); return; }
      return { observation_window_id: riskWindowSelection.value.observation_window_id, qsofa_assessment_id: qsofaSelection.value.qsofa_assessment_id, question: question.value };
    }
    if (needsAki.value) {
      if (!akiReady.value || !akiSelection.value) { ElMessage.warning("请明确选择并核对AKI原来源、适用性与判据策略"); return; }
      return { observation_window_id: riskWindowSelection.value.observation_window_id, aki_assessment_id: akiSelection.value.aki_assessment_id, question: question.value };
    }
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
  if(Object.hasOwn(input,'coding_case_id')){ElMessage.warning('编码证据须在专用模式下明确选择，不能混入其他功能或自由JSON输入');return;}
  if(Object.hasOwn(input,'inventory_scenario_id')){ElMessage.warning('受审库存场景须由本地库存比较模式明确选择，不能混入外部适配器输入');return;}
  if(Object.hasOwn(input,'supply_series_id')){ElMessage.warning('受审物资原量须由本地专用模式明确选择，不能混入外部适配器输入');return;}
  if(Object.hasOwn(input,'surgery_scenario_id')){ElMessage.warning('受审手术场景须由本地专用入口明确选择，不能混入外部适配器输入');return;}
  if(Object.hasOwn(input,'bed_series_id')){ElMessage.warning('受审床位序列及预测期须由本地床位专用模式明确选择，不能混入外部适配器输入');return;}
  if(Object.hasOwn(input,'roster_plan_id')){ElMessage.warning('受审排班计划引用须由本地排班专用模式明确选择，不能混入旧外部适配器输入');return;}
  for (const key of [...Object.keys(boundReferenceLabels), ...Object.keys(boundPathwayLabels), ...Object.keys(boundNursingLabels), "audio_asset_id", "ecg_asset_id", "image_asset_id", "imaging_order_id"]) if (props.initialInput?.[key] != null) input[key] = String(props.initialInput?.[key]);
  if (needsAudio.value && !props.initialInput?.audio_asset_id) { if (audioAssetId.value) input.audio_asset_id = audioAssetId.value; else delete input.audio_asset_id; }
  if (needsEcg.value && !props.initialInput?.ecg_asset_id) { if (ecgAssetId.value) input.ecg_asset_id = ecgAssetId.value; else delete input.ecg_asset_id; }
  if (needsImage.value) { if (imageAssetId.value) input.image_asset_id = imageAssetId.value; else delete input.image_asset_id; if (imageOrderId.value) input.imaging_order_id = String(props.initialInput?.imaging_order_id || imageOrderId.value); else delete input.imaging_order_id; }
  if (needsPathway.value && !props.initialInput?.pathway_id && !props.initialInput?.pathway_enrollment_id) { if (pathwayId.value) input.pathway_id = String(pathwayId.value); else delete input.pathway_id; }
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
async function expandQueuedReply(value,request,ticket){
  const protectedMode=ticket.codingMode||ticket.inventoryMode||ticket.supplyMode||ticket.surgeryMode||ticket.bedMode||ticket.rosterMode||ticket.sofaMode||ticket.mode;
  if(!protectedMode||value?.coding_findings||value?.inventory_findings||value?.supply_findings||value?.surgery_findings||value?.bed_findings||value?.roster_findings||value?.sofa_findings||value?.sofa_change_findings||value?.support_findings)return value;
  if(!supportCurrent(ticket))return null;
  if(!supportId(value?.run_id)||value.feature_key!==request.feature_key||!Object.hasOwn(statuses,value.status)||value.patient_id!==(request.patient_id??null)||value.encounter_ref!==(request.encounter_ref??null)||value.requires_human_review!==true||!supportHash(value.context_digest)){
    clearUnavailableSupport(ticket,'排队回执的任务、范围或状态不一致，暂不展示。');return null;
  }
  const id=value.run_id,response=await getAIRun(id);
  if(!supportCurrent(ticket))return null;
  if(response.data?.run_id!==id||response.data?.context_digest!==value.context_digest||response.data?.feature_key!==value.feature_key||response.data?.patient_id!==value.patient_id||response.data?.encounter_ref!==value.encounter_ref){clearUnavailableSupport(ticket,'完整任务与原排队标识或资料摘要不同，已拒绝展示。');return null;}
  if(ticket.codingMode&&!verifyCodingReceipt(value,response.data)){clearUnavailableSupport(ticket,'编码完整任务与原排队回执不一致，已拒绝展示。');return null;}
  if(ticket.inventoryMode&&!verifyInventoryReceipt(value,response.data)){clearUnavailableSupport(ticket,'库存完整任务与原排队回执不一致，已拒绝展示。');return null;}
  if(ticket.supplyMode&&!verifySupplyReceipt(value,response.data)){clearUnavailableSupport(ticket,'物资完整任务与原排队回执不一致，已拒绝展示。');return null;}
  return response.data;
}
async function submit() {
  if(dedicatedLifecycle.value)return;
  const input = buildTaskInput(); if (!input) return;
  submitting.value = true;
  stopPolling(); const selection = selectionVersion, view = pollVersion, supportTicket = captureSupport(true);
  try {
    const request={ feature_key: featureKey.value, patient_id: selected.value.scope === "patient" ? patientId.value : null, encounter_ref: selected.value.scope === "patient" ? encounterRef.value || null : null, input, preview: canPreview.value && preview.value };
    const response = await createAIRun(request);
    if(selection!==selectionVersion||view!==pollVersion||!supportCurrent(supportTicket))return;
    const value=await expandQueuedReply(response.data,request,supportTicket);
    if (!value||selection !== selectionVersion || view !== pollVersion || !await acceptSupportRun(value, supportTicket) || selection !== selectionVersion || view !== pollVersion) return;
    run.value = value; startPolling();
  } catch(failure){
    if(codingLifecycle.value||supportLifecycle.value||sofaLifecycle.value||rosterLifecycle.value||bedLifecycle.value||surgeryLifecycle.value||supplyLifecycle.value||nativeInventoryLifecycle.value){if(selection===selectionVersion&&view===pollVersion){historyVersion++;history.value=[];clearUnavailableSupport(supportTicket);}return;}
    throw failure;
  } finally { submitting.value = false; }
}
async function refreshRun() {
  if(dedicatedLifecycle.value)return;
  if(!run.value)return;stopPolling();const id=run.value.run_id,selection=selectionVersion,view=pollVersion,supportTicket=captureSupport();
  try{const response=await getAIRun(id);if(selection!==selectionVersion||view!==pollVersion||id!==run.value?.run_id||!requestedRunMatches(response.data,id,supportTicket)||!await acceptSupportRun(response.data,supportTicket)||selection!==selectionVersion||view!==pollVersion)return;run.value=response.data;startPolling();}
  catch(failure){if(codingLifecycle.value||supportLifecycle.value||sofaLifecycle.value||rosterLifecycle.value||bedLifecycle.value||surgeryLifecycle.value||supplyLifecycle.value||nativeInventoryLifecycle.value){clearUnavailableSupport(supportTicket);return;}throw failure;}
}
async function openRun(id) {
  if(dedicatedLifecycle.value)return;
  if((codingLifecycle.value&&(!codingAuthorized.value||!codingHistoryScopeReady.value))||(nativeInventoryLifecycle.value&&!nativeInventoryAuthorized.value)||(supplyLifecycle.value&&!supplyAuthorized.value)||(surgeryLifecycle.value&&(!surgeryAuthorized.value||!surgeryCohortValid.value))||(rosterLifecycle.value&&!rosterAuthorized.value)||(bedLifecycle.value&&!bedAuthorized.value))return;
  stopPolling();const selection=selectionVersion,view=pollVersion,supportTicket=captureSupport();
  try{const response=await getAIRun(id);if(selection!==selectionVersion||view!==pollVersion||!requestedRunMatches(response.data,id,supportTicket)||!await acceptSupportRun(response.data,supportTicket)||selection!==selectionVersion||view!==pollVersion)return;run.value=response.data;startPolling();}
  catch(failure){if(codingLifecycle.value||supportLifecycle.value||sofaLifecycle.value||rosterLifecycle.value||bedLifecycle.value||surgeryLifecycle.value||supplyLifecycle.value||nativeInventoryLifecycle.value){clearUnavailableSupport(supportTicket);return;}throw failure;}
}
async function cancel() { const ticket=captureSupport(),id=run.value?.run_id;if(!id)return;try{await cancelAIRun(id);if(!supportCurrent(ticket)||run.value?.run_id!==id)return;await refreshRun();}catch(failure){if(codingLifecycle.value||supplyLifecycle.value||nativeInventoryLifecycle.value){clearUnavailableSupport(ticket);return;}throw failure;} }
async function loadHistory(activeNames) {
  if(dedicatedLifecycle.value)return;
  if (activeNames !== undefined) historyOpen = activeNames.length > 0;
  if((codingLifecycle.value&&(!codingAuthorized.value||!codingHistoryScopeReady.value))||(nativeInventoryLifecycle.value&&!nativeInventoryAuthorized.value)||(supplyLifecycle.value&&!supplyAuthorized.value)||(surgeryLifecycle.value&&(!surgeryAuthorized.value||!surgeryCohortValid.value))||(rosterLifecycle.value&&!rosterAuthorized.value)||(bedLifecycle.value&&!bedAuthorized.value))return;
  if((needsSurgery.value||surgeryWasBound.value||surgeryCaseCohortBound.value)&&(!needsSurgery.value||!serviceSurgeryPool.value&&!(surgeryInitialReferences.value||surgerySelection.value)?.surgery_scenario_id)){history.value=[];return;}
  if(codingLifecycle.value&&(!needsCodingEvidence.value||codingInitialReferences.value!==null&&!codingCaseReferencesValid(codingInitialReferences.value)||!codingScopeValid({patient_id:patientId.value,admission_id:encounterRef.value,home_id:props.initialInput?.home_id??codingHome.value}))){history.value=[];return;}
  if((needsNativeInventory.value||nativeInventoryWasBound.value)&&(!needsNativeInventory.value||!nativeInventoryScopeValid(nativeInventoryScope.value))){history.value=[];return;}
  if((needsSupply.value||supplyWasBound.value)&&(!needsSupply.value||!supplyScopeValid(supplyScope.value))){history.value=[];return;}
  if (!historyOpen || !featureKey.value || (selected.value?.scope === "patient" && !patientId.value)) return;
  const version = ++historyVersion,ticket=captureSupport();
  try {
    const response = await getAIRuns({...(needsCodingEvidence.value?{coding_case_id:(codingInitialReferences.value||codingSelection.value)?.coding_case_id}:{}),...(needsNativeInventory.value?{inventory_item_kind:nativeInventoryScope.value?.item_kind,inventory_item_id:nativeInventoryScope.value?.item_id,inventory_scenario_id:(nativeInventoryInitialReferences.value||nativeInventorySelection.value)?.inventory_scenario_id}:{}),...(needsSupply.value?{supply_item_kind:supplyScope.value?.item_kind,supply_item_id:supplyScope.value?.item_id,supply_series_id:(supplyInitialReferences.value||supplySelection.value)?.supply_series_id}:{}),...(needsSurgery.value||surgeryWasBound.value||surgeryCaseCohortBound.value?{department_id:serviceDepartment.value||undefined,surgery_pool_id:serviceSurgeryPool.value||undefined,surgery_scenario_id:(surgeryInitialReferences.value||surgerySelection.value)?.surgery_scenario_id}:{}),...(bedLifecycle.value?{department_id:serviceDepartment.value||undefined,ward_id:serviceWard.value||undefined,bed_series_id:(bedInitialReferences.value||bedSelection.value)?.bed_series_id}:{}),...(rosterLifecycle.value?{department_id:serviceDepartment.value||undefined,roster_plan_id:(rosterInitialReferences.value||rosterSelection.value)?.roster_plan_id}:{}),feature_key: featureKey.value, patient_id: selected.value?.scope === "patient" ? patientId.value : undefined, encounter_ref: selected.value?.scope === "patient" ? encounterRef.value || undefined : undefined });
    if (version === historyVersion&&supportCurrent(ticket)) history.value = codingLifecycle.value?(response.data||[]).filter(row=>row.feature_key==='drg_evidence_review'&&row.patient_id===ticket.patient&&row.encounter_ref===ticket.admission):(response.data || []);
  } catch(failure) {
    if(codingLifecycle.value||supportLifecycle.value||sofaLifecycle.value||rosterLifecycle.value||bedLifecycle.value||surgeryLifecycle.value||supplyLifecycle.value||nativeInventoryLifecycle.value){if(version===historyVersion&&supportCurrent(ticket)){history.value=[];stopPolling();clearUnavailableSupport(ticket);}return;}
    throw failure;
  }
}
watch([() => JSON.stringify(store.getters["user/permissions"]), () => store.state.user.accessToken,()=>store.state.user.username], () => {
  if (!needsForecast.value && !needsRiskWindow.value && !codingLifecycle.value && !supportLifecycle.value && !sofaLifecycle.value&&!rosterLifecycle.value&&!bedLifecycle.value&&!surgeryLifecycle.value&&!supplyLifecycle.value&&!nativeInventoryLifecycle.value) return;
  codingSelection.value=null;codingReady.value=false;codingHome.value=null;codingInputKey.value++;
  nativeInventorySelection.value=null;nativeInventoryReady.value=false;nativeInventoryScope.value=null;nativeInventoryInputKey.value++;
  supplySelection.value=null;supplyReady.value=false;supplyScope.value=null;supplyInputKey.value++;surgerySelection.value=null;surgeryReady.value=false;surgeryInputKey.value++;serviceSurgeryPool.value=null;rosterSelection.value=null;rosterReady.value=false;rosterInputKey.value++;bedSelection.value=null;bedReady.value=false;bedInputKey.value++;if(rosterLifecycle.value||bedLifecycle.value||surgeryLifecycle.value||supplyLifecycle.value||nativeInventoryLifecycle.value){serviceDepartment.value=null;serviceWard.value=null;}
  sofaSelection.value=null;sofaReady.value=false;formVersion++; patientLoadVersion++; patients.value = []; encounters.value = []; prescriptions.value = []; patientLoading.value = false; patientId.value = null; encounterRef.value = ""; prescriptionId.value = null; question.value = ""; extraInput.value = ""; preview.value = false;
  selectionVersion++; historyVersion++; supportFailure.value = ""; stopPolling(); run.value = null; contextData.value = null; contextDialog.value = false; evidence.value=null; evidenceDialog.value = false; feedbackDialog.value = false; history.value = []; forecastReady.value = false; forecastSelection.value = null; riskWindowReady.value = false; riskWindowSelection.value = null; news2Ready.value = false; news2Selection.value = null; akiReady.value = false; akiSelection.value = null; qsofaReady.value = false; qsofaSelection.value = null;
  if (needsRiskWindow.value && store.state.user.accessToken) searchPatients().catch(() => {});
});
const evidenceTitle = id => run.value?.evidence?.find(item => item.source_id === id)?.title || "来源";
async function inspectEvidence(id) { if(id&&typeof id==='object')id=id.source_id;const ticket=captureSupport(),currentRun=run.value;evidence.value=null;evidenceDialog.value=false;const packet=currentRun?.sofa_findings||currentRun?.sofa_change_findings;const value=codingRunHasMarkers(currentRun)?await resolveCodingEvidence(currentRun.evidence?.find(item=>item.source_id===id),currentRun.coding_findings,codingExpected(ticket),{current:()=>supportCurrent(ticket),auditOnly:false}):currentRun?.inventory_findings?await resolveInventoryEvidence(currentRun.evidence?.find(item=>item.source_id===id),currentRun.inventory_findings,nativeInventoryExpected(ticket),{current:()=>supportCurrent(ticket),auditOnly:false}):currentRun?.supply_findings?await resolveSupplyEvidence(currentRun.evidence?.find(item=>item.source_id===id),currentRun.supply_findings,supplyExpected(ticket),{current:()=>supportCurrent(ticket),auditOnly:false}):currentRun?.surgery_findings?await resolveSurgeryEvidence(currentRun.evidence?.find(item=>item.source_id===id),currentRun.surgery_findings,{departmentId:ticket.department,poolId:ticket.pool,references:ticket.surgeryReferences}):currentRun?.bed_findings?await resolveBedEvidence(currentRun.evidence?.find(item=>item.source_id===id),currentRun.bed_findings,ticket.department,ticket.ward,ticket.bedReferences):currentRun?.roster_findings?await resolveRosterEvidence(currentRun.evidence?.find(item=>item.source_id===id),currentRun.roster_findings,ticket.department,ticket.rosterReferences):packet?await resolveSofaEvidence(currentRun.evidence?.find(item=>item.source_id===id),packet,patientId.value,encounterRef.value,ticket.sofaReferences):currentRun?.support_findings?await resolveSupportEvidence(currentRun.evidence?.find(item=>item.source_id===id),currentRun.support_findings,patientId.value,encounterRef.value,needsSupport.value?supportReferences.value:null):(currentRun?.qsofa_findings?resolveQsofaEvidence:resolveAkiEvidence)(currentRun?.evidence?.find(item=>item.source_id===id),currentRun?.qsofa_findings||currentRun?.aki_findings,currentRun?.patient_id,currentRun?.encounter_ref||encounterRef.value);if(currentRun!==run.value||(codingRunHasMarkers(currentRun)||packet||currentRun?.support_findings||currentRun?.roster_findings||currentRun?.bed_findings||currentRun?.surgery_findings||currentRun?.supply_findings||currentRun?.inventory_findings)&&!supportCurrent(ticket))return;evidence.value=value;evidenceDialog.value=!!value; }
async function inspectPreviewEvidence(id) {if(id&&typeof id==='object')id=id.source_id;const ticket=captureSupport(),packet=contextData.value;if(!contextDialog.value||!packet)return;const evidenceVersion=++previewEvidenceVersion;evidence.value=null;evidenceDialog.value=false;const c=packet?.context,sofa=c?.sofa_source||c?.sofa_change_source;const value=c&&['coding_binding','coding_source','coding_case'].some(k=>Object.hasOwn(c,k))?await resolveCodingEvidence(packet.evidence?.find(item=>item.source_id===id),c,codingExpected(ticket),{current:()=>supportCurrent(ticket),auditOnly:false}):c?.inventory_source?await resolveInventoryEvidence(packet.evidence?.find(item=>item.source_id===id),c,nativeInventoryExpected(ticket),{current:()=>supportCurrent(ticket),auditOnly:false}):c?.supply_source?await resolveSupplyEvidence(packet.evidence?.find(item=>item.source_id===id),c,supplyExpected(ticket),{current:()=>supportCurrent(ticket),auditOnly:false}):c?.surgery_source?await resolveSurgeryEvidence(packet.evidence?.find(item=>item.source_id===id),c,{departmentId:ticket.department,poolId:ticket.pool,references:ticket.surgeryReferences}):c?.bed_source?await resolveBedEvidence(packet.evidence?.find(item=>item.source_id===id),c,ticket.department,ticket.ward,ticket.bedReferences):c?.roster_source?await resolveRosterEvidence(packet.evidence?.find(item=>item.source_id===id),c,ticket.department,ticket.rosterReferences):sofa?await resolveSofaEvidence(packet.evidence?.find(item=>item.source_id===id),c,patientId.value,encounterRef.value,sofaSelection.value):c?.support_source?await resolveSupportEvidence(packet.evidence?.find(item=>item.source_id===id),c,patientId.value,encounterRef.value,supportReferences.value):(c?.qsofa_source?resolveQsofaEvidence:resolveAkiEvidence)(packet?.evidence?.find(item=>item.source_id===id),c,patientId.value,encounterRef.value);if(!contextDialog.value||evidenceVersion!==previewEvidenceVersion||packet!==contextData.value||(c?.coding_binding||sofa||c?.support_source||c?.roster_source||c?.bed_source||c?.surgery_source||c?.supply_source||c?.inventory_source)&&!supportCurrent(ticket))return;evidence.value=value;evidenceDialog.value=!!value;}
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
async function submitFeedback() {
  if(!run.value)return;const id=run.value.run_id,ticket=captureSupport();
  try{await reviewAIRun(id,feedback.value);if(!supportCurrent(ticket)||run.value?.run_id!==id)return;feedbackDialog.value=false;feedback.value={outcome:"accepted",comment:""};ElMessage.success("复核反馈已保存");}
  catch(failure){if(codingLifecycle.value||supportLifecycle.value||sofaLifecycle.value||rosterLifecycle.value||bedLifecycle.value||surgeryLifecycle.value||supplyLifecycle.value||nativeInventoryLifecycle.value){if(supportCurrent(ticket)&&run.value?.run_id===id){historyVersion++;history.value=[];stopPolling();clearUnavailableSupport(ticket);}return;}throw failure;}
}
onMounted(async () => {
  loading.value = true;
  const initialSelection=selectionVersion,initialCredentials = JSON.stringify([store.state.user.accessToken,store.getters["user/permissions"]]);
  try { const response = await getAIFeatures(); if (!viewActive.value||initialSelection!==selectionVersion||initialCredentials !== JSON.stringify([store.state.user.accessToken,store.getters["user/permissions"]])) return; features.value = (response.data || []).filter(item => !props.featureKeys.length || props.featureKeys.includes(item.key)); featureKey.value = features.value.some(item => item.key === props.initialFeature) ? props.initialFeature : features.value[0]?.key || ""; }
  finally { loading.value = false; }
});
onActivated(() => { viewActive.value = true; if (busy.value) startPolling(); });
onDeactivated(() => { viewActive.value = false;codingSelection.value=null;codingReady.value=false;codingHome.value=null;codingInputKey.value++;nativeInventorySelection.value=null;nativeInventoryReady.value=false;nativeInventoryScope.value=null;nativeInventoryInputKey.value++;supplySelection.value=null;supplyReady.value=false;supplyScope.value=null;supplyInputKey.value++;surgerySelection.value=null;surgeryReady.value=false;surgeryInputKey.value++;bedSelection.value=null;bedReady.value=false;bedInputKey.value++;rosterSelection.value=null;rosterReady.value=false;rosterInputKey.value++;sofaSelection.value=null;sofaReady.value=false; selectionVersion += 1; stopPolling(); if(codingLifecycle.value||supportLifecycle.value||sofaLifecycle.value||rosterLifecycle.value||bedLifecycle.value||surgeryLifecycle.value||supplyLifecycle.value||nativeInventoryLifecycle.value){historyVersion++;run.value=null;contextData.value=null;contextDialog.value=false;evidence.value=null;evidenceDialog.value=false;feedbackDialog.value=false;history.value=[];} });
onBeforeUnmount(() => { viewActive.value = false;codingSelection.value=null;codingReady.value=false;codingHome.value=null;codingInputKey.value++;nativeInventorySelection.value=null;nativeInventoryReady.value=false;nativeInventoryScope.value=null;nativeInventoryInputKey.value++;supplySelection.value=null;supplyReady.value=false;supplyScope.value=null;supplyInputKey.value++;surgerySelection.value=null;surgeryReady.value=false;surgeryInputKey.value++;bedSelection.value=null;bedReady.value=false;bedInputKey.value++;rosterSelection.value=null;rosterReady.value=false;rosterInputKey.value++;sofaSelection.value=null;sofaReady.value=false; selectionVersion += 1; historyVersion += 1; formVersion += 1; pathwayOptionsVersion += 1; stopPolling(); });
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
