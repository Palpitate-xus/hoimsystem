<template>
  <div v-if="allowed">
    <el-form inline @submit.prevent="load(true)">
      <el-form-item label="能力"><el-select v-model="filters.feature_key" clearable filterable placeholder="全部能力" style="width: 210px"><el-option v-for="item in features" :key="item.key" :value="item.key" :label="item.name" /></el-select></el-form-item>
      <el-form-item label="状态"><el-select v-model="filters.status" clearable placeholder="全部状态" style="width: 130px"><el-option v-for="(label, value) in states" :key="value" :value="value" :label="label" /></el-select></el-form-item>
      <el-form-item label="反馈"><el-select v-model="filters.outcome" clearable placeholder="全部反馈" style="width: 150px"><el-option v-for="(label, value) in outcomes" :key="value" :value="value" :label="'含' + label + '反馈'" /></el-select></el-form-item>
      <el-form-item label="发起用户ID"><el-input-number v-model="filters.requested_by" :min="1" :controls="false" style="width: 130px" /></el-form-item>
      <el-form-item v-if="filters.feature_key==='drg_evidence_review'" label="原编码证据"><el-input v-model="filters.coding_case_id" placeholder="原完整编码证据规范UUID" aria-label="审计编码证据" /></el-form-item>
      <el-form-item v-if="filters.feature_key==='charge_reconciliation'" label="完整账目原件"><el-input v-model="filters.charge_case_id" placeholder="完整住院账目规范UUID" aria-label="审计完整账目原件" /></el-form-item>
      <el-form-item v-if="filters.feature_key==='guideline_ingestion'" label="原文原件"><el-input v-model="filters.document_original_id" placeholder="原文原件规范UUID" aria-label="审计原文原件" /></el-form-item>
      <el-form-item v-if="filters.feature_key==='guideline_change_review'" label="双原文有限范围"><el-input v-model="filters.document_change_scope_id" placeholder="原比较范围规范UUID" aria-label="审计双原文范围" /></el-form-item>
      <el-form-item v-if="filters.feature_key==='drug_label_extraction'" label="完整说明书来源"><el-input v-model="filters.drug_label_source_binding_id" placeholder="完整说明书来源规范UUID" aria-label="审计说明书来源" /></el-form-item>
      <el-form-item v-if="filters.feature_key==='operations_support'" label="原受审运维材料集"><el-input v-model="filters.operations_case_id" placeholder="原材料集规范UUID，仅作技术目录筛选" aria-label="审计运维材料集" /></el-form-item>
      <el-form-item v-if="filters.feature_key==='feedback_analysis'" label="完整评价原件"><el-input v-model="filters.satisfaction_case_id" placeholder="完整评价原件规范UUID" aria-label="审计完整评价原件" /></el-form-item>
      <el-form-item v-if="!['guideline_ingestion','guideline_change_review','feedback_analysis','drug_label_extraction','research_cohort','deidentification','operations_support','clinical_training'].includes(filters.feature_key)" label="患者ID"><el-input-number v-model="filters.patient_id" :min="1" :controls="false" style="width: 130px" /></el-form-item>
      <template v-if="filters.feature_key==='surgery_scheduling'"><el-form-item label="原手术科室"><el-input-number v-model="filters.department_id" :min="1" :controls="false" /></el-form-item><el-form-item label="原手术资源池"><el-input v-model="filters.surgery_pool_id" placeholder="原资源池规范UUID" /></el-form-item><el-form-item label="原受审手术场景"><el-input v-model="filters.surgery_scenario_id" placeholder="原场景规范UUID" /></el-form-item></template>
      <template v-if="filters.feature_key==='supply_forecast'"><el-form-item label="原物资类型"><el-select v-model="filters.supply_item_kind" clearable aria-label="审计物资类型"><el-option value="pharmaceutical" label="药品" /><el-option value="consumable" label="耗材" /></el-select></el-form-item><el-form-item label="原物资标识"><el-input-number v-model="filters.supply_item_id" :min="1" :controls="false" :precision="0" aria-label="审计物资标识" /></el-form-item><el-form-item label="原物资序列"><el-input v-model="filters.supply_series_id" placeholder="原受审序列规范UUID" aria-label="审计物资序列" /></el-form-item></template>
      <template v-if="filters.feature_key==='inventory_optimization'"><el-form-item label="原库存品种类型"><el-select v-model="filters.inventory_item_kind" clearable aria-label="审计库存品种类型"><el-option value="pharmaceutical" label="药品" /><el-option value="consumable" label="耗材" /></el-select></el-form-item><el-form-item label="原库存品种标识"><el-input v-model="filters.inventory_item_id" placeholder="原正整数品种标识" aria-label="审计库存品种标识" /></el-form-item><el-form-item label="原库存候选场景"><el-input v-model="filters.inventory_scenario_id" placeholder="原受审场景规范UUID" aria-label="审计库存候选场景" /></el-form-item></template>
      <el-form-item><el-button type="primary" native-type="submit">查询任务</el-button><el-button @click="load()">刷新任务</el-button></el-form-item>
    </el-form>
    <el-table :data="rows" v-loading="loading" empty-text="暂无匹配任务">
      <el-table-column label="能力" min-width="160"><template #default="{row}">{{trainingRunHasMarkers(row)?(props.features.find(f=>f.key==='clinical_training')?.name||'原生教学任务'):row.feature_key==='operations_support'?'79 · 受审运维材料辅助':row.feature_name}}</template></el-table-column>
      <el-table-column prop="requested_by" label="用户ID" width="85" /><el-table-column prop="patient_id" label="患者ID" width="85" />
      <el-table-column label="状态" width="100"><template #default="{ row }">{{ states[row.status] }}</template></el-table-column>
      <el-table-column label="已报告Token" width="160"><template #default="{ row }">{{ reportedTokens(row) }}</template></el-table-column>
      <el-table-column prop="feedback_count" label="反馈数" width="85" /><el-table-column prop="create_time" label="发起时间" width="180" />
      <el-table-column label="操作" fixed="right" width="175"><template #default="{ row }"><el-button size="small" @click="inspect(row)">执行溯源</el-button><el-button v-if="['queued', 'running'].includes(row.status)" size="small" type="warning" @click="cancel(row)">取消接收</el-button></template></el-table-column>
    </el-table>
    <el-pagination v-model:current-page="page" :page-size="30" :total="total" layout="total, prev, pager, next" class="pagination-wrapper" @current-change="load()" />

    <el-dialog v-model="visible" title="AI 任务执行溯源" width="min(1150px, 96vw)" append-to-body destroy-on-close :before-close="closeTrace">
      <div v-loading="detailLoading" class="trace-body">
        <DeidentificationSharedTrace v-if="deidentificationMetadata" :metadata="deidentificationMetadata" :active="allowed&&visible" @invalidate="closeTrace" @close="closeTrace"/>
        <OperationsSupportFindings v-if="operationsRunId" :run-id="operationsRunId" :expected-case-id="operationsExpectedCase" :active="allowed&&visible" audit-only @invalidate="closeTrace"/>
        <ClinicalTrainingTrace v-if="trainingBundle" :bundle="trainingBundle" :active="allowed&&visible" @invalidate="closeTrace"/>
        <ResearchCohortTrace v-if="researchBundle" :bundle="researchBundle" :active="allowed&&visible" @invalidate="closeTrace"/>
        <template v-if="detail">
          <el-descriptions :column="2" border>
            <el-descriptions-item label="能力">{{ detail.feature_name }}</el-descriptions-item><el-descriptions-item label="任务状态">{{ states[detail.status] }}{{ detail.preview ? ' · 评估预览' : '' }}</el-descriptions-item>
            <el-descriptions-item label="发起用户ID">{{ detail.requested_by }}</el-descriptions-item><el-descriptions-item label="患者ID">{{ detail.patient_id || '未关联患者' }}</el-descriptions-item>
            <el-descriptions-item label="发起时间">{{ detail.create_time }}</el-descriptions-item><el-descriptions-item label="Prompt / 模型配置版本">v{{ detail.prompt_version }} / v{{ detail.provider_revision }}</el-descriptions-item>
          </el-descriptions>
          <el-alert v-if="detail.error_message" type="error" :closable="false" :title="detail.error_message" class="spaced" />
          <el-alert v-if="!detail.snapshot_complete" type="info" :closable="false" title="旧任务按实际留存内容展示，部分执行快照字段未保存。" class="spaced" />
          <el-tabs v-model="detailTab" class="spaced">
            <el-tab-pane label="结果与引用" name="result">
              <document-change-findings v-if="visible&&changeBundle" :bundle="changeBundle" :active="allowed&&visible" audit-only @cleared="closeTrace" />
              <template v-if="!changeBundle">
              <drug-label-findings v-if="visible&&drugLabelRun" :run="drugLabelRun" :trace="detail" :references="{drug_label_source_binding_id:drugLabelRun.drug_label_source_binding_id}" :expected-run-id="drugLabelRun.run_id" :active="allowed&&visible" audit-only @invalidate="closeTrace" @reload="closeTrace" />
              <charge-reconciliation-findings v-if="visible&&hasCharge(detail)&&chargeRun" :run="chargeRun" :trace="detail" :expected-run-id="detail.run_id" :active="allowed&&visible" audit-only @inspect="showEvidence" @invalidate="closeTrace" />
              <document-extraction-findings v-if="visible&&detail.feature_key==='guideline_ingestion'" :run="detail" :trace="detail" :expected-run-id="detail.run_id" :expected-original-id="detail.document_original_id" :active="allowed&&visible" audit-only @cleared="closeTrace" />
              <satisfaction-findings v-if="visible&&hasSatisfaction(detail)&&!legacySatisfaction(detail)" :packet="detail.satisfaction_findings" :result="detail.result" :active="allowed&&visible" audit-only @invalidate="closeTrace" />
              <el-alert v-if="legacySatisfaction(detail)" type="info" :closable="false" title="旧评价任务仅按原留存内容查看；新任务须选择完整受审原件。" class="spaced" />
              <coding-findings v-if="visible&&detail.feature_key==='drg_evidence_review'" :run="detail" :active="allowed&&visible" audit-only @inspect="showEvidence" />
              <ai-supply-findings v-if="visible&&detail.supply_findings" :run="detail" :active="allowed&&visible" audit-only @inspect="showEvidence" />
              <ai-inventory-findings v-if="visible&&detail.inventory_findings" :run="detail" :active="allowed&&visible" audit-only @inspect="showEvidence" />
              <ai-surgery-findings v-if="visible&&detail.surgery_findings" :run="detail" :active="allowed&&visible" @inspect="showEvidence" />
              <ai-speech-findings v-if="visible" :findings="detail.audio_findings" :transcription="detail.result?.transcription" @inspect="showEvidence" />
              <ai-image-findings v-if="visible" :findings="detail.image_findings" :analysis="detail.result?.image_analysis" @inspect="showEvidence" />
              <ai-ecg-findings v-if="visible" :findings="detail.ecg_findings" :analysis="detail.result?.ecg_analysis" @inspect="showEvidence" />
              <template v-if="!drugLabelRun&&!hasCharge(detail)&&(!hasSatisfaction(detail)||legacySatisfaction(detail))"><p class="plain-text">{{ detail.result?.summary || '此任务没有已接收的结果' }}</p>
              <el-alert v-for="(item, i) in detail.result?.warnings || []" :key="'warning-' + i" type="warning" :closable="false" :title="item" class="spaced" />
              <p v-for="(item, i) in detail.result?.missing_data || []" :key="'missing-' + i">待补资料：{{ item }}</p>
              <section v-for="(item, i) in detail.result?.sections || []" :key="i"><h4>{{ item.title }}</h4><p class="plain-text">{{ item.content }}</p><el-button v-for="id in item.source_ids" :key="id" link @click="showEvidence(id)">查看依据 {{ id }}</el-button></section></template>
              </template>
            </el-tab-pane>
            <el-tab-pane label="人工反馈" name="feedback">
              <p v-if="drugLabelRun">说明书任务的人工反馈可在管理台反馈记录中查看。</p>
              <el-table v-else :data="detail.feedback || []" empty-text="尚无人工反馈"><el-table-column prop="reviewer_id" label="复核用户ID" width="110" /><el-table-column label="反馈" width="110"><template #default="{ row }">{{ outcomes[row.outcome] }}</template></el-table-column><el-table-column prop="comment" label="说明" min-width="240" /><el-table-column prop="create_time" label="时间" width="180" /></el-table>
              <p v-if="detail.feedback_truncated">仅展示最近 100 条反馈。</p>
            </el-tab-pane>
            <el-tab-pane label="调用时 Prompt" name="prompt"><h4>固定系统 Prompt</h4><pre class="plain-text">{{ detail.frozen_request?.system_prompt || '未保存原文' }}</pre><h4>任务 Prompt</h4><pre class="plain-text">{{ detail.frozen_request?.task_prompt }}</pre></el-tab-pane>
            <el-tab-pane label="模型与验证快照" name="model"><el-descriptions :column="1" border><el-descriptions-item label="请求模型">{{ detail.frozen_request?.provider_snapshot?.model || '未保存' }}</el-descriptions-item><el-descriptions-item label="服务地址">{{ detail.frozen_request?.provider_snapshot?.api_base || '未保存' }}</el-descriptions-item><el-descriptions-item label="输出上限">{{ detail.frozen_request?.provider_snapshot?.effective_output_limit ?? '未保存' }}</el-descriptions-item><el-descriptions-item label="当时验证记录">{{ detail.frozen_request?.feature_validation?.note || '未保存' }}</el-descriptions-item><el-descriptions-item label="适配器验证记录">{{ detail.frozen_request?.provider_snapshot?.validation_report || '未登记' }}</el-descriptions-item></el-descriptions></el-tab-pane>
            <el-tab-pane label="调用时资料与工具" name="input"><pre class="plain-text">{{ JSON.stringify(detail.frozen_request?.payload || {}, null, 2) }}</pre></el-tab-pane>
            <el-tab-pane v-if="drugLabelRun" label="说明书原始任务 JSON" name="drug_label_raw"><section v-for="(raw,key) in detail.raw_frozen_json" :key="key"><h4>{{ key }}</h4><pre class="plain-text">{{ raw }}</pre></section></el-tab-pane>
          </el-tabs>
        </template>
      </div>
    </el-dialog>
    <el-dialog v-model="evidenceVisible" title="任务原始依据" width="min(800px, 96vw)" append-to-body><h4>{{ evidence?.title }}</h4><p>{{ evidence?.observed_at }}</p><pre class="plain-text">{{ evidence?.content }}</pre></el-dialog>
  </div>
</template>

<script setup>
import { computed, defineAsyncComponent, onActivated, onBeforeUnmount, onDeactivated, onMounted, ref, toRaw, watch } from "vue";
import { useStore } from "vuex";
import { ElMessage, ElMessageBox } from "element-plus";
import { cancelAIRun, getAIAdminRuns, getAIAdminRunTrace, getAIRun } from "@/api/ai";
import AiSpeechFindings from "@/components/AISpeechFindings/index.vue";
import AiImageFindings from "@/components/AIImageFindings/index.vue";
import AiEcgFindings from "@/components/AIEcgFindings/index.vue";
import { resolveSurgeryEvidence, verifySurgeryRun } from "@/api/ai/surgeryScenarios";
import {resolveSupplyEvidence,verifySupplyRun,supplyAnalysisVersionSupported} from "@/api/ai/supplyResults";
import {resolveInventoryEvidence,verifyInventoryRun,inventoryAnalysisVersionSupported,inventoryRunHasNativeMarkers} from "@/api/ai/inventoryResults";
import {codingRunHasMarkers,verifyCodingRun,resolveCodingEvidence} from "@/api/ai/codingResults";
import {verifyChargeTrace,chargeRunHasNativeMarkers} from "@/api/ai/chargeReconciliationResults";
import {verifyDrugLabelRun,verifyDrugLabelTrace} from '@/api/ai/drugLabelResults';
import {drugLabelRunHasNativeMarkers} from '@/api/ai/drugLabelHistory';
const DrugLabelFindings=defineAsyncComponent(()=>import('@/components/ai/DrugLabelFindings.vue'));
import {documentChangeRunHasMarkers,verifyDocumentChangeRun,getDocumentChangeRunPiece} from "@/api/ai/documentChangeResults";
import {documentChangeReceiptValid} from "@/api/ai/documentChangeTasks";
const DocumentChangeFindings=defineAsyncComponent(()=>import("@/components/ai/DocumentChangeFindings.vue"));
import { supportCanonical, supportId } from "@/api/inpatientSupport";
import{researchRunHasMarkers,verifyResearchSharedDirectoryRow,readResearchSplitTrace,readResearchCurrentAuditMetadata,researchIncompleteMetadataValid}from'@/api/ai/researchCohortShared';
import{deidentificationRunHasMarkers,verifyDeidentificationSharedMetadata,verifyDeidentificationSharedDirectoryRow,verifyDeidentificationIncompleteMetadata,getDeidentificationSharedTask}from'@/api/ai/deidentificationSharedTasks';
const DeidentificationSharedTrace=defineAsyncComponent(()=>import('@/components/ai/DeidentificationSharedTrace.vue'));
import{operationsRunHasMarkers,verifyOperationsSharedDirectoryRow,cancelOperationsTask,verifyOperationsCancelAck}from'@/api/ai/operationsSupportTasks';
const OperationsSupportFindings=defineAsyncComponent(()=>import('@/components/ai/OperationsSupportFindings.vue'));
import{trainingRunHasMarkers,verifyTrainingSharedDirectoryRow,verifyTrainingTaskMetadata,verifyTrainingSplitTrace,verifyTrainingTaskParts,getTrainingSharedTask,getTrainingTaskPart}from'@/api/ai/clinicalTrainingTasks';
const ClinicalTrainingTrace=defineAsyncComponent(()=>import('@/components/ai/ClinicalTrainingTrace.vue'));
const ResearchCohortTrace=defineAsyncComponent(()=>import('@/components/ai/ResearchCohortTrace.vue'));
const CodingFindings=defineAsyncComponent(()=>import("@/components/ai/CodingFindings.vue"));
const ChargeReconciliationFindings=defineAsyncComponent(()=>import("@/components/ai/ChargeReconciliationFindings.vue"));
import {documentExtractionRunHasMarkers,verifyDocumentExtractionRun} from "@/api/ai/documentExtractionResults";
const DocumentExtractionFindings=defineAsyncComponent(()=>import("@/components/ai/DocumentExtractionFindings.vue"));
import {satisfactionRunHasMarkers,verifySatisfactionTrace,resolveSatisfactionEvidence} from "@/api/ai/satisfactionResults";
const SatisfactionFindings=defineAsyncComponent(()=>import("@/components/ai/SatisfactionFindings.vue"));
const AiInventoryFindings=defineAsyncComponent(()=>import("@/components/ai/InventoryFindings.vue"));
const AiSupplyFindings=defineAsyncComponent(()=>import("@/components/SupplyFindings.vue"));
const AiSurgeryFindings=defineAsyncComponent(()=>import("@/components/AISurgeryFindings.vue"));
const props = defineProps({ features: { type: Array, default: () => [] }, active: { type: Boolean, default: true } });
const store=useStore(),roles=computed(()=>store.getters['user/permissions']||[]),allowed=computed(()=>props.active&&typeof store.state.user.accessToken==='string'&&store.state.user.accessToken.length>0&&Array.isArray(roles.value)&&roles.value.includes('super_admin'));
const auth=()=>supportCanonical([props.active,store.state.user.accessToken,store.state.user.username,roles.value]);
const states = { queued: "排队中", running: "生成中", succeeded: "待业务复核", failed: "失败", cancelled: "已取消" };
const outcomes = { accepted: "采纳", rejected: "驳回", modified: "修改后采纳" };
const rows = ref([]), loading = ref(false), page = ref(1), total = ref(0), filters = ref({ feature_key: "", status: "", outcome: "", requested_by: undefined, patient_id: undefined, department_id: undefined, surgery_pool_id:'',surgery_scenario_id:'',supply_item_kind:'',supply_item_id:undefined,supply_series_id:'',inventory_item_kind:'',inventory_item_id:undefined,inventory_scenario_id:'',coding_case_id:'',charge_case_id:'',document_original_id:'',satisfaction_case_id:'',drug_label_source_binding_id:'',document_change_scope_id:'',operations_case_id:'' });
const drugLabelRun=ref(null),listedDrugLabelScope=ref(null),changeBundle=ref(null),researchBundle=ref(null),trainingBundle=ref(null),deidentificationMetadata=ref(null);
const operationsRunId=ref(null),operationsExpectedCase=ref(null);
let listedOperationsCase=null,listedOperationsRows=new Map(),listedOperationsObjects=new WeakMap();
let listedTrainingRows=new Map(),listedTrainingObjects=new WeakMap();
let listedResearchScope=null,listedResearchRows=new Map(),listedResearchObjects=new WeakMap();
const visible = ref(false), detail = ref(null), chargeRun = ref(null), detailLoading = ref(false), detailTab = ref("result"), evidenceVisible = ref(false), evidence = ref(null);
let listVersion = 0, detailVersion = 0;
// The accepted directory query is an independent native-scope anchor. A
// damaged row/trace cannot erase the Case that selected this list.
let listedChargeCase = null;
let listedSatisfactionScope = null;
let listedDocumentScope = null, listedChangeScope = null;
let listedDeidentificationRows=new Map(),listedDeidentificationObjects=new WeakMap(),listedDeidentificationFilter=false;
let wasDeactivated = false;
let alive=true;
const current=key=>alive&&!wasDeactivated&&allowed.value&&key===auth();
const hasSurgery=value=>!!value?.surgery_findings||!!value?.result?.surgery_analysis||!!value?.frozen_request?.payload?.context?.surgery_binding||!!value?.frozen_request?.payload?.input?.surgery_scenario_id||String(value?.frozen_request?.provider_snapshot?.model||'').startsWith('surgery:');
const hasSupply=value=>!!value?.supply_findings||!!value?.result?.supply_analysis||['supply_binding','supply_source','supply_series'].some(name=>!!value?.frozen_request?.payload?.context?.[name])||!!value?.frozen_request?.payload?.input?.supply_series_id||String(value?.frozen_request?.provider_snapshot?.model||'').startsWith('supply:');
const hasInventory=inventoryRunHasNativeMarkers,hasCoding=codingRunHasMarkers,hasDocument=documentExtractionRunHasMarkers;
const hasCharge=chargeRunHasNativeMarkers;
const hasSatisfaction=satisfactionRunHasMarkers,hasDocumentChange=documentChangeRunHasMarkers;
const legacySatisfaction=value=>value?.feature_key==='feedback_analysis'&&value?.legacy_feedback_read_only===true&&!hasSatisfaction({...value,feature_key:''});
function reportedTokens(row){const known=value=>Number.isSafeInteger(value)&&value>=0;if(deidentificationRunHasMarkers(row))return [row.input_tokens,row.output_tokens].map(value=>known(value)?String(value):'未报告').join(' / ');if(trainingRunHasMarkers(row)||operationsRunHasMarkers(row)||researchRunHasMarkers(row))return [row.usage?.input_tokens,row.usage?.output_tokens].map(value=>known(value)?String(value):'未报告').join(' / ');if(hasSatisfaction(row)&&!legacySatisfaction(row))return [row.usage?.input_tokens,row.usage?.output_tokens].map(value=>known(value)?String(value):'未报告').join(' / ');return hasCharge(row)||hasDocument(row)||hasDocumentChange(row)||drugLabelRunHasNativeMarkers(row)?[row.input_tokens,row.output_tokens].map(value=>known(value)?String(value):'未报告').join(' / '):row.input_tokens||row.output_tokens?(row.input_tokens||0)+' / '+(row.output_tokens||0):'未报告';}
function closeTrace(done){++detailVersion;operationsRunId.value=operationsExpectedCase.value=null;detail.value=chargeRun.value=drugLabelRun.value=changeBundle.value=researchBundle.value=deidentificationMetadata.value=trainingBundle.value=null;evidence.value=null;detailLoading.value=false;visible.value=evidenceVisible.value=false;if(typeof done==='function')done();}
function clear(){++listVersion;++detailVersion;listedTrainingRows=new Map();listedTrainingObjects=new WeakMap();operationsRunId.value=operationsExpectedCase.value=null;listedOperationsCase=null;listedOperationsRows=new Map();listedOperationsObjects=new WeakMap();listedDeidentificationRows=new Map();listedDeidentificationObjects=new WeakMap();listedDeidentificationFilter=false;listedChargeCase=listedSatisfactionScope=listedDocumentScope=listedChangeScope=listedResearchScope=null;listedResearchRows=new Map();listedResearchObjects=new WeakMap();listedDrugLabelScope.value=null;rows.value=[];total.value=0;detail.value=chargeRun.value=drugLabelRun.value=changeBundle.value=researchBundle.value=deidentificationMetadata.value=trainingBundle.value=null;evidence.value=null;visible.value=evidenceVisible.value=false;loading.value=detailLoading.value=false;}
async function load(reset = false) {
  if(!allowed.value||!alive||wasDeactivated)return;
  if(deidentificationMetadata.value||listedDeidentificationRows.size||listedDeidentificationFilter)closeTrace();
  if(trainingBundle.value||listedTrainingRows.size||operationsRunId.value||listedOperationsRows.size||researchBundle.value||listedResearchScope!==null||listedResearchRows.size>0)closeTrace();
  if (reset) page.value = 1;
  const version = ++listVersion,key=auth(); loading.value = true;
  const params = Object.fromEntries(Object.entries(filters.value).filter(([, value]) => value !== "" && value != null));
  if(['operations_case_id','document_change_scope_id','drug_label_source_binding_id','satisfaction_case_id','document_original_id','charge_case_id','coding_case_id','inventory_scenario_id','supply_series_id','surgery_pool_id','surgery_scenario_id'].some(name=>params[name]&&!supportId(params[name]))){loading.value=false;ElMessage.warning('原序列、资源池与场景过滤须为明确规范UUID');return;}
  if(params.feature_key==='deidentification'&&Object.keys(params).some(k=>!['feature_key','status','outcome','requested_by'].includes(k))){loading.value=false;ElMessage.warning('病例去标识任务目录只接受原生域和通用技术过滤，不接受患者或其它来源范围');return;}
  if(params.operations_case_id&&params.feature_key!=='operations_support'||params.feature_key==='operations_support'&&Object.keys(params).some(k=>!['feature_key','status','outcome','requested_by','operations_case_id'].includes(k))){loading.value=false;ElMessage.warning('运维任务目录只接受明确材料集及通用技术过滤');return;}
  if(params.feature_key==='research_cohort'&&Object.keys(params).some(k=>!['feature_key','status','outcome','requested_by'].includes(k))){loading.value=false;ElMessage.warning('科研任务目录只接受原生任务与通用技术过滤，不接受患者、库存或其它来源范围');return;}
  if(['clinical_training'].includes(params.feature_key)&&Object.keys(params).some(k=>!['feature_key','status','outcome','requested_by'].includes(k))){loading.value=false;ElMessage.warning('科研任务目录只接受原生任务与通用技术过滤，不接受患者、库存或其它来源范围');return;}
  if(params.document_change_scope_id&&params.feature_key!=='guideline_change_review'||params.feature_key==='guideline_change_review'&&['charge_case_id','satisfaction_case_id','drug_label_source_binding_id','patient_id','department_id','document_original_id','coding_case_id','inventory_scenario_id','inventory_item_kind','inventory_item_id','supply_series_id','supply_item_kind','supply_item_id','surgery_pool_id','surgery_scenario_id'].some(name=>params[name]!==undefined)){loading.value=false;ElMessage.warning('双原文审计只接受明确有限范围及通用任务过滤');return;}
  if(params.charge_case_id&&params.feature_key!=='charge_reconciliation'){loading.value=false;ElMessage.warning('完整账目原件须在收费核对能力中查询');return;}
  if(params.document_original_id&&params.feature_key!=='guideline_ingestion'||params.feature_key==='guideline_ingestion'&&['document_change_scope_id','drug_label_source_binding_id','satisfaction_case_id','charge_case_id','patient_id','department_id','coding_case_id','inventory_scenario_id','inventory_item_kind','inventory_item_id','supply_series_id','supply_item_kind','supply_item_id','surgery_pool_id','surgery_scenario_id'].some(name=>params[name]!==undefined)){loading.value=false;ElMessage.warning('原文审计须明确选择原文提取能力及原件范围');return;}
  if(params.satisfaction_case_id&&params.feature_key!=='feedback_analysis'||params.feature_key==='feedback_analysis'&&['document_change_scope_id','drug_label_source_binding_id','document_original_id','charge_case_id','patient_id','department_id','coding_case_id','inventory_scenario_id','inventory_item_kind','inventory_item_id','supply_series_id','supply_item_kind','supply_item_id','surgery_pool_id','surgery_scenario_id'].some(name=>params[name]!==undefined)){loading.value=false;ElMessage.warning('评价审计只接受完整评价原件范围');return;}
  if(params.feature_key==='feedback_analysis')params.satisfaction_native_only=true;
  if(params.drug_label_source_binding_id&&params.feature_key!=='drug_label_extraction'||params.feature_key==='drug_label_extraction'&&['document_change_scope_id','charge_case_id','satisfaction_case_id','patient_id','department_id','document_original_id','coding_case_id','inventory_scenario_id','inventory_item_kind','inventory_item_id','supply_series_id','supply_item_kind','supply_item_id','surgery_pool_id','surgery_scenario_id'].some(name=>params[name]!==undefined)){loading.value=false;ElMessage.warning('说明书审计只接受明确完整来源范围');return;}
  if((!!params.supply_item_kind)!==(params.supply_item_id!==undefined)||params.supply_item_kind&&!['pharmaceutical','consumable'].includes(params.supply_item_kind)||params.supply_item_id!==undefined&&(!Number.isSafeInteger(params.supply_item_id)||params.supply_item_id<1)){loading.value=false;ElMessage.warning('物资审计须同时明确有效类型与整数标识');return;}
  if((!!params.inventory_item_kind)!==(params.inventory_item_id!==undefined)||params.inventory_item_kind&&!['pharmaceutical','consumable'].includes(params.inventory_item_kind)||params.inventory_item_id!==undefined&&(!/^[1-9][0-9]*$/.test(String(params.inventory_item_id))||!Number.isSafeInteger(Number(params.inventory_item_id))||Number(params.inventory_item_id)>2147483647)){loading.value=false;ElMessage.warning('库存审计须同时明确有效类型与规范正整数品种标识');return;}
  try { const response = await getAIAdminRuns({ ...params, page: page.value, page_size: 30 }); if (current(key)&&version === listVersion) { const actual=response.data;if(!Array.isArray(actual)||actual.length>30||actual.some(row=>(params.feature_key==='guideline_change_review'||hasDocumentChange(row))&&!documentChangeReceiptValid(row,{scopeId:params.document_change_scope_id||row.document_change_scope_id}))||new Set(actual.map(row=>row.run_id)).size!==actual.length)throw new Error('实际原生任务目录不闭合');const trainingRows=actual.filter(row=>params.feature_key==='clinical_training'||trainingRunHasMarkers(row));if(!trainingRows.every(row=>verifyTrainingSharedDirectoryRow(row)))throw new Error('教学任务技术目录闭集无法核对');listedTrainingRows=new Map(trainingRows.map(row=>[row.run_id,JSON.parse(JSON.stringify(row))]));listedTrainingObjects=new WeakMap(trainingRows.map(row=>[row,listedTrainingRows.get(row.run_id)]));const operationsRows=actual.filter(row=>params.feature_key==='operations_support'||operationsRunHasMarkers(row));if(!operationsRows.every(row=>verifyOperationsSharedDirectoryRow(row,{current:()=>current(key)&&version===listVersion})))throw new Error('运维目录域或技术闭集不完整');listedOperationsCase=params.feature_key==='operations_support'?params.operations_case_id||null:null;listedOperationsRows=new Map(operationsRows.map(row=>[row.run_id,supportCanonical(row)]));listedOperationsObjects=new WeakMap(operationsRows.map(row=>[row,listedOperationsRows.get(row.run_id)]));const deidentificationRows=actual.filter(row=>params.feature_key==='deidentification'||deidentificationRunHasMarkers(row));if(!(await Promise.all(deidentificationRows.map(row=>verifyDeidentificationSharedDirectoryRow(row,{auditOnly:true,current:()=>current(key)&&version===listVersion})))).every(Boolean))throw new Error('病例去标识目录原生域或完整技术锚不符');if(!current(key)||version!==listVersion)return;listedDeidentificationFilter=params.feature_key==='deidentification';listedDeidentificationRows=new Map(deidentificationRows.map(row=>[row.run_id,JSON.parse(JSON.stringify(row))]));listedDeidentificationObjects=new WeakMap(deidentificationRows.map(row=>[row,listedDeidentificationRows.get(row.run_id)]));const researchRows=actual.filter(row=>params.feature_key==='research_cohort'||researchRunHasMarkers(row));if(!(await Promise.all(researchRows.map(row=>verifyResearchSharedDirectoryRow(row,{current:()=>current(key)&&version===listVersion})))).every(Boolean))throw new Error('科研目录域或锚不完整');if(!current(key)||version!==listVersion)return;listedResearchScope=params.feature_key==='research_cohort'?{}:null;listedResearchRows=new Map(researchRows.map(row=>[row.run_id,JSON.parse(JSON.stringify(row))]));listedResearchObjects=new WeakMap(researchRows.map(row=>[row,listedResearchRows.get(row.run_id)]));listedDocumentScope=params.feature_key==='guideline_ingestion'?{originalId:params.document_original_id||null}:null;listedChangeScope=params.feature_key==='guideline_change_review'?{scopeId:params.document_change_scope_id||null}:null;listedChargeCase=params.feature_key==='charge_reconciliation'&&params.charge_case_id?params.charge_case_id:null;listedSatisfactionScope=params.feature_key==='feedback_analysis'?{caseId:params.satisfaction_case_id||null}:null;listedDrugLabelScope.value=params.feature_key==='drug_label_extraction'?{bindingId:params.drug_label_source_binding_id||null}:null;rows.value = response.data || []; total.value = response.total || 0; } }
  catch { if(current(key)&&version===listVersion){clear();ElMessage.warning('当前任务目录或审计权限无法重新核对，旧资料已清除');} }
  finally { if (current(key)&&version === listVersion) loading.value = false; }
}
async function inspect(row) {
  if(!allowed.value||!alive||wasDeactivated)return;
  const version=++detailVersion,key=auth(),expectedChargeCase=listedChargeCase,expectedSatisfaction=listedSatisfactionScope,expectedDrugScope=listedDrugLabelScope.value,expectedDocument=listedDocumentScope,expectedChange=listedChangeScope,expectedResearch=listedResearchScope,listedResearch=listedResearchObjects.get(toRaw(row))||listedResearchRows.get(row.run_id)||null,isCurrent=()=>current(key)&&version===detailVersion&&visible.value;
  operationsRunId.value=operationsExpectedCase.value=null;
  visible.value=true;detail.value=chargeRun.value=drugLabelRun.value=changeBundle.value=researchBundle.value=deidentificationMetadata.value=trainingBundle.value=null;evidence.value=null;evidenceVisible.value=false;detailTab.value="result";detailLoading.value=true;
  try {
    const listedDeidentification=listedDeidentificationObjects.get(toRaw(row))||null;
    if(listedDeidentificationFilter||listedDeidentification!==null||deidentificationRunHasMarkers(row)){
      if(!listedDeidentification||supportCanonical(row)!==supportCanonical(listedDeidentification)||!await verifyDeidentificationSharedDirectoryRow(row,{auditOnly:true,current:isCurrent}))throw new Error('病例去标识原目录身份已变化');
      if(listedDeidentification.incomplete_native_artifact===true){const metadata=Object.fromEntries(Object.entries(listedDeidentification).filter(([k])=>!['requested_by','provider_id','feedback_count'].includes(k)));if(!verifyDeidentificationIncompleteMetadata(metadata))throw new Error('不完整病例去标识技术目录无法核对');if(isCurrent())deidentificationMetadata.value=metadata;return;}
      const metadata=(await getDeidentificationSharedTask(listedDeidentification.run_id)).data;if(!isCurrent())return;if(!await verifyDeidentificationSharedMetadata(metadata,{runId:listedDeidentification.run_id,current:isCurrent})||supportCanonical(metadata.opaque_hashes)!==supportCanonical(listedDeidentification.opaque_hashes))throw new Error('当前病例去标识技术锚或用途无法核对');if(isCurrent())deidentificationMetadata.value=metadata;return;
    }
    const originalOperations=listedOperationsObjects.get(toRaw(row));
    if(originalOperations!==undefined||operationsRunHasMarkers(row)){if(originalOperations===undefined||originalOperations!==supportCanonical(row)||!verifyOperationsSharedDirectoryRow(row,{current:isCurrent}))throw new Error('原运维技术目录身份或闭集已变化');operationsExpectedCase.value=listedOperationsCase;operationsRunId.value=row.run_id;return;}
    const listedTraining=listedTrainingObjects.get(toRaw(row))||listedTrainingRows.get(row.run_id)||null;
    if(listedTraining||trainingRunHasMarkers(row)){
      if(!listedTraining||!verifyTrainingSharedDirectoryRow(row)||supportCanonical(row)!==supportCanonical(listedTraining))throw new Error('教学任务原目录身份已变化');
      const metadata=(await getTrainingSharedTask(row.run_id)).data;if(!isCurrent())return;
      if(!verifyTrainingTaskMetadata(metadata,{runId:row.run_id,requestedBy:row.requested_by}))throw new Error('当前教学技术状态无法核对');
      const trace=(await getAIAdminRunTrace(row.run_id)).data;if(!isCurrent())return;
      if(!verifyTrainingSplitTrace(trace,{runId:row.run_id})||supportCanonical(trace.run)!==supportCanonical(metadata))throw new Error('实际教学溯源与当前技术状态不同');
      let parts=null;
      if(metadata.parts_state==='available'){
        parts=Object.fromEntries(await Promise.all(['task','source','binding','result'].map(async name=>[name,await getTrainingTaskPart(row.run_id,name)])));if(!isCurrent())return;
        if(!await verifyTrainingTaskParts(metadata,parts,{runId:row.run_id,current:isCurrent}))throw new Error('本人当前教学完整分件无法核对');
        const latest=(await getTrainingSharedTask(row.run_id)).data;if(!isCurrent())return;if(supportCanonical(latest)!==supportCanonical(metadata))throw new Error('当前教学状态在读取期间变化');
      }
      if(isCurrent())trainingBundle.value={metadata,parts};return;
    }
    const listedChange=expectedChange!==null||hasDocumentChange(row),listedId=row.run_id,listedScope=expectedChange?.scopeId||row.document_change_scope_id;
    if(listedResearch&&(!await verifyResearchSharedDirectoryRow(row,{current:isCurrent})||supportCanonical(row)!==supportCanonical(listedResearch)))throw new Error('科研目录身份或锚已改变');
    if(listedResearch?.incomplete_native_artifact===true){const metadata=Object.fromEntries(Object.entries(listedResearch).filter(([k])=>!['requested_by','provider_id','feedback_count'].includes(k)));if(!researchIncompleteMetadataValid(metadata))throw new Error('原科研技术目录无法核对');if(isCurrent())researchBundle.value={metadata,parts:null,incomplete:true};return;}
    if(listedResearch){const metadata=await readResearchCurrentAuditMetadata(listedResearch,{current:isCurrent});if(!isCurrent())return;if(metadata.clinical_parts_available===false){researchBundle.value={metadata,parts:null};return;}}
    const response=await getAIAdminRunTrace(row.run_id);if(!isCurrent())return;const value=response.data;if(deidentificationRunHasMarkers(value))throw new Error('病例去标识原生Trace缺少已核对原目录，禁止通用降级');
    if(operationsRunHasMarkers(value))throw new Error('运维任务不能从其它能力目录降级进入通用审计');
    if(expectedResearch!==null||listedResearch!==null||researchRunHasMarkers(row)||researchRunHasMarkers(value)){if(!listedResearch||!await verifyResearchSharedDirectoryRow(listedResearch,{current:isCurrent}))throw new Error('原科研目录无法核对');const next=await readResearchSplitTrace(value,{listed:listedResearch,current:isCurrent});if(isCurrent())researchBundle.value=next;return;}
    let verified=typeof row.feature_key==='string'&&value?.run_id===row.run_id&&value?.feature_key===row.feature_key,full=null,fullDrugLabel=null,frozenChange=null;
    if(verified&&(listedChange||hasDocumentChange(value))){
      verified=documentChangeReceiptValid(row,{scopeId:listedScope,runId:listedId})&&value.feature_key==='guideline_change_review';
      if(verified){const parts=await Promise.all(['source','scope',...(value.status==='succeeded'?['result']:[])].map(kind=>getDocumentChangeRunPiece(listedId,kind,{auditOnly:true})));if(!isCurrent())return;const frozen={run:value,trace:value,source:parts[0].data,scope:parts[1].data,result:parts[2]?.data||null};verified=await verifyDocumentChangeRun(frozen,{runId:listedId,scopeId:listedScope,auditOnly:true,current:isCurrent});if(verified&&isCurrent())frozenChange=frozen;}
    }
    if(verified&&(expectedDrugScope!==null||drugLabelRunHasNativeMarkers(row)||drugLabelRunHasNativeMarkers(value))){
      const candidate=(await getAIRun(row.run_id)).data;if(!isCurrent())return;
      const expected={runId:row.run_id,references:expectedDrugScope?.bindingId?{drug_label_source_binding_id:expectedDrugScope.bindingId}:null},options={auditOnly:true,allowFrozenAudit:true,current:isCurrent};
      verified=await verifyDrugLabelRun(candidate,expected,options)&&await verifyDrugLabelTrace(value,candidate,expected,options);
      if(verified)fullDrugLabel=candidate;
    }
    if(verified&&(expectedChargeCase!==null||hasCharge(row)||hasCharge(value))){
      full=(await getAIRun(row.run_id)).data;if(!isCurrent())return;
      verified=(expectedChargeCase===null||value.charge_case_id===expectedChargeCase)&&(!filters.value.patient_id||value.patient_id===filters.value.patient_id)&&(!row.charge_case_id||row.charge_case_id===value.charge_case_id)&&await verifyChargeTrace(value,full,{runId:row.run_id},{auditOnly:true,allowFrozenAudit:true,current:isCurrent});
    }
    if(verified&&(expectedDocument!==null||row.feature_key==='guideline_ingestion'||hasDocument(row)||hasDocument(value)))verified=await verifyDocumentExtractionRun(value,value,{runId:row.run_id,originalId:expectedDocument?.originalId||null,auditOnly:true,current:isCurrent});
    if(verified&&(expectedSatisfaction!==null||hasSatisfaction(row)&&!legacySatisfaction(row)||hasSatisfaction(value)&&!legacySatisfaction(value)))verified=await verifySatisfactionTrace(value,{runId:row.run_id,references:expectedSatisfaction?.caseId?{satisfaction_case_id:expectedSatisfaction.caseId}:null});
    else if(verified&&(row.feature_key==='feedback_analysis'||value.feature_key==='feedback_analysis'))verified=legacySatisfaction(row)&&legacySatisfaction(value);
    if(verified&&(row.feature_key==='drg_evidence_review'||hasCoding(value)))verified=await verifyCodingRun(value,{}, {auditOnly:true,current:isCurrent});
    if(verified&&hasInventory(value))verified=await verifyInventoryRun(value,{}, {auditOnly:true,current:isCurrent});
    if(verified&&hasSupply(value))verified=await verifySupplyRun(value,{}, {auditOnly:true,current:isCurrent});
    if(verified&&hasSurgery(value))verified=await verifySurgeryRun(value);
    if(!verified){if(isCurrent())ElMessage.warning(hasInventory(value)&&value?.result?.inventory_analysis&&!inventoryAnalysisVersionSupported(value.result.inventory_analysis)?'原运行版本当前无法重算，暂不展示旧库存比较正文':hasSupply(value)&&value?.result?.supply_analysis&&!supplyAnalysisVersionSupported(value.result.supply_analysis)?'原运行版本当前无法重算，暂不展示旧预测正文':'原任务或完整冻结来源及固定结果无法核对，暂不展示');return;}
    if(isCurrent()){changeBundle.value=frozenChange;chargeRun.value=full;drugLabelRun.value=fullDrugLabel;detail.value=value;}
  }catch{if(isCurrent()){clear();ElMessage.warning('当前完整任务或审计权限无法重新核对，旧资料已清除');}}
  finally{if(current(key)&&version===detailVersion)detailLoading.value=false;}
}
async function showEvidence(id) { if(id&&typeof id==='object')id=id.source_id;const key=auth(),version=detailVersion,original=detail.value;evidence.value=null;evidenceVisible.value=false;if(!current(key)||!visible.value||!original)return;const item=original.evidence?.find(value=>value.source_id===id);if(hasDocumentChange(original)){const frozen=changeBundle.value,valid=()=>current(key)&&version===detailVersion&&visible.value&&original===detail.value&&frozen===changeBundle.value;if(!item||!frozen||!await verifyDocumentChangeRun(frozen,{runId:original.run_id,auditOnly:true,current:valid}))return;const b=frozen.source.document_change_source,side=['baseline','candidate'].find(side=>item.original_id===b[side].original.original_id);if(valid()){evidence.value=side?{title:side==='baseline'?'基准完整原文':'候选完整原文',content:b[side].text,observed_at:frozen.run.document_change_artifact.recorded_at}:{title:'完整有限范围冻结原件',content:JSON.stringify(frozen.scope.scope_snapshot,null,2),observed_at:frozen.run.document_change_artifact.recorded_at};evidenceVisible.value=true;}return;}if(hasCharge(original)){const full=chargeRun.value;if(!item||!full||!await verifyChargeTrace(original,full,{runId:original.run_id},{auditOnly:true,allowFrozenAudit:true,current:()=>current(key)&&version===detailVersion&&visible.value}))return;if(current(key)&&visible.value&&version===detailVersion&&original===detail.value&&full===chargeRun.value){evidence.value={title:item.title,observed_at:original.charge_findings.charge_binding.captured_at,content:JSON.stringify(original.charge_findings.charge_case.snapshot,null,2)};evidenceVisible.value=true;}return;}if(hasSatisfaction(original)&&!legacySatisfaction(original)){if(!item||!await verifySatisfactionTrace(original,{runId:original.run_id}))return;const resolved=await resolveSatisfactionEvidence(item,original.satisfaction_findings,{auditOnly:true});if(resolved&&current(key)&&visible.value&&version===detailVersion&&original===detail.value){evidence.value={title:resolved.title,observed_at:original.satisfaction_artifact.created_at,content:JSON.stringify(resolved.source,null,2)};evidenceVisible.value=true;}return;}if(hasDocument(original)){if(!item||!await verifyDocumentExtractionRun(original,original,{runId:original.run_id,auditOnly:true,current:()=>current(key)&&version===detailVersion&&visible.value}))return;const source=original.document_original;if(current(key)&&visible.value&&version===detailVersion&&original===detail.value){evidence.value={title:source.snapshot.metadata.title,observed_at:source.snapshot.recorded_at,content:source.snapshot.text};evidenceVisible.value=true;}return;}const value=hasCoding(original)?await resolveCodingEvidence(item,original.coding_findings||original.frozen_request?.payload?.context,{}, {auditOnly:true,current:()=>current(key)&&version===detailVersion&&visible.value}):hasInventory(original)?await resolveInventoryEvidence(item,original.inventory_findings||original.frozen_request?.payload?.context,{}, {auditOnly:true,current:()=>current(key)&&version===detailVersion&&visible.value}):hasSupply(original)?await resolveSupplyEvidence(item,original.supply_findings,{}, {auditOnly:true,current:()=>current(key)&&version===detailVersion}):hasSurgery(original)?await resolveSurgeryEvidence(item,original.surgery_findings):item;if(current(key)&&visible.value&&version===detailVersion&&original===detail.value){evidence.value=value;evidenceVisible.value=!!value;} }
async function cancel(row) {
  const key=auth();if(!current(key))return;
  try {
    await ElMessageBox.confirm("取消后将停止接收结果，已发出的模型请求仍可能计费。", "取消任务结果接收", { confirmButtonText: "取消接收", cancelButtonText: "保留任务", type: "warning" });
    if(!current(key))return;if(operationsRunHasMarkers(row)){if(listedOperationsObjects.get(toRaw(row))!==supportCanonical(row)||!verifyOperationsSharedDirectoryRow(row))throw new Error('原运维目录已变化');const ack=(await cancelOperationsTask(row.run_id)).data;if(!verifyOperationsCancelAck(ack,{runId:row.run_id}))throw new Error('运维取消回执无法核对');}else await cancelAIRun(row.run_id);if(!current(key))return;ElMessage.success("任务结果已取消接收"); await load();
  } catch (error) { if (error !== "cancel" && error !== "close"&&current(key)){clear();ElMessage.warning('当前任务或取消权限已经变化，请重新核对');} }
}
watch(visible,open=>{if(!open){++detailVersion;operationsRunId.value=operationsExpectedCase.value=null;detail.value=chargeRun.value=drugLabelRun.value=changeBundle.value=researchBundle.value=deidentificationMetadata.value=trainingBundle.value=null;evidence.value=null;evidenceVisible.value=false;detailLoading.value=false;}},{flush:'sync'});
watch(evidenceVisible,open=>{if(!open)evidence.value=null;},{flush:'sync'});
watch(()=>filters.value.feature_key,value=>{if(value!=='operations_support')filters.value.operations_case_id='';else for(const name of Object.keys(filters.value))if(!['feature_key','status','outcome','requested_by','operations_case_id'].includes(name))filters.value[name]=typeof filters.value[name]==='string'?'':undefined;if(['research_cohort','deidentification','clinical_training'].includes(value)){for(const name of Object.keys(filters.value))if(!['feature_key','status','outcome','requested_by'].includes(name))filters.value[name]=typeof filters.value[name]==='string'?'':undefined;}if(value!=='guideline_change_review')filters.value.document_change_scope_id='';else filters.value.patient_id=undefined;if(value!=='drug_label_extraction')filters.value.drug_label_source_binding_id='';else filters.value.patient_id=undefined;if(value!=='guideline_ingestion')filters.value.document_original_id='';else filters.value.patient_id=undefined;if(value!=='feedback_analysis')filters.value.satisfaction_case_id='';else filters.value.patient_id=undefined;if(value!=='charge_reconciliation')filters.value.charge_case_id='';if(value!=='drg_evidence_review')filters.value.coding_case_id='';if(value!=='surgery_scheduling'){filters.value.department_id=undefined;filters.value.surgery_pool_id=filters.value.surgery_scenario_id='';}if(value!=='supply_forecast'){filters.value.supply_item_kind='';filters.value.supply_item_id=undefined;filters.value.supply_series_id='';}if(value!=='inventory_optimization'){filters.value.inventory_item_kind='';filters.value.inventory_item_id=undefined;filters.value.inventory_scenario_id='';}else filters.value.patient_id=undefined;},{flush:'sync'});
watch(filters,clear,{deep:true,flush:'sync'});
watch(auth,()=>{clear();if(allowed.value&&!wasDeactivated)load();},{flush:'sync'});
onMounted(() => { if (allowed.value) load(); });
onDeactivated(() => { wasDeactivated = true;clear(); });
onActivated(() => { if (wasDeactivated) { wasDeactivated = false; if (allowed.value) load(); } });
onBeforeUnmount(() => { alive=false;clear(); });
</script>

<style scoped>
.spaced { margin-top: 14px; }
.plain-text { white-space: pre-wrap; overflow-wrap: anywhere; line-height: 1.7; max-height: 55vh; overflow: auto; }
.trace-body { min-height: 100px; }
</style>
