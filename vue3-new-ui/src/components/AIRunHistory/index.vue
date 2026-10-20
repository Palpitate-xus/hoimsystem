<template>
  <div v-if="allowed">
    <el-form inline @submit.prevent="load(true)">
      <el-form-item label="能力"><el-select v-model="filters.feature_key" clearable filterable placeholder="全部能力" style="width: 210px"><el-option v-for="item in features" :key="item.key" :value="item.key" :label="item.name" /></el-select></el-form-item>
      <el-form-item label="状态"><el-select v-model="filters.status" clearable placeholder="全部状态" style="width: 130px"><el-option v-for="(label, value) in states" :key="value" :value="value" :label="label" /></el-select></el-form-item>
      <el-form-item label="反馈"><el-select v-model="filters.outcome" clearable placeholder="全部反馈" style="width: 150px"><el-option v-for="(label, value) in outcomes" :key="value" :value="value" :label="'含' + label + '反馈'" /></el-select></el-form-item>
      <el-form-item label="发起用户ID"><el-input-number v-model="filters.requested_by" :min="1" :controls="false" style="width: 130px" /></el-form-item>
      <el-form-item label="患者ID"><el-input-number v-model="filters.patient_id" :min="1" :controls="false" style="width: 130px" /></el-form-item>
      <template v-if="filters.feature_key==='surgery_scheduling'"><el-form-item label="原手术科室"><el-input-number v-model="filters.department_id" :min="1" :controls="false" /></el-form-item><el-form-item label="原手术资源池"><el-input v-model="filters.surgery_pool_id" placeholder="原资源池规范UUID" /></el-form-item><el-form-item label="原受审手术场景"><el-input v-model="filters.surgery_scenario_id" placeholder="原场景规范UUID" /></el-form-item></template>
      <template v-if="filters.feature_key==='supply_forecast'"><el-form-item label="原物资类型"><el-select v-model="filters.supply_item_kind" clearable aria-label="审计物资类型"><el-option value="pharmaceutical" label="药品" /><el-option value="consumable" label="耗材" /></el-select></el-form-item><el-form-item label="原物资标识"><el-input-number v-model="filters.supply_item_id" :min="1" :controls="false" :precision="0" aria-label="审计物资标识" /></el-form-item><el-form-item label="原物资序列"><el-input v-model="filters.supply_series_id" placeholder="原受审序列规范UUID" aria-label="审计物资序列" /></el-form-item></template>
      <el-form-item><el-button type="primary" native-type="submit">查询任务</el-button><el-button @click="load()">刷新任务</el-button></el-form-item>
    </el-form>
    <el-table :data="rows" v-loading="loading" empty-text="暂无匹配任务">
      <el-table-column prop="feature_name" label="能力" min-width="160" />
      <el-table-column prop="requested_by" label="用户ID" width="85" /><el-table-column prop="patient_id" label="患者ID" width="85" />
      <el-table-column label="状态" width="100"><template #default="{ row }">{{ states[row.status] }}</template></el-table-column>
      <el-table-column label="已报告Token" width="130"><template #default="{ row }">{{ row.input_tokens || row.output_tokens ? (row.input_tokens || 0) + ' / ' + (row.output_tokens || 0) : '未报告' }}</template></el-table-column>
      <el-table-column prop="feedback_count" label="反馈数" width="85" /><el-table-column prop="create_time" label="发起时间" width="180" />
      <el-table-column label="操作" fixed="right" width="175"><template #default="{ row }"><el-button size="small" @click="inspect(row)">执行溯源</el-button><el-button v-if="['queued', 'running'].includes(row.status)" size="small" type="warning" @click="cancel(row)">取消接收</el-button></template></el-table-column>
    </el-table>
    <el-pagination v-model:current-page="page" :page-size="30" :total="total" layout="total, prev, pager, next" class="pagination-wrapper" @current-change="load()" />

    <el-dialog v-model="visible" title="AI 任务执行溯源" width="min(1150px, 96vw)" append-to-body destroy-on-close>
      <div v-loading="detailLoading" class="trace-body">
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
              <ai-supply-findings v-if="visible&&detail.supply_findings" :run="detail" :active="allowed&&visible" audit-only @inspect="showEvidence" />
              <ai-surgery-findings v-if="visible&&detail.surgery_findings" :run="detail" :active="allowed&&visible" @inspect="showEvidence" />
              <ai-speech-findings v-if="visible" :findings="detail.audio_findings" :transcription="detail.result?.transcription" @inspect="showEvidence" />
              <ai-image-findings v-if="visible" :findings="detail.image_findings" :analysis="detail.result?.image_analysis" @inspect="showEvidence" />
              <ai-ecg-findings v-if="visible" :findings="detail.ecg_findings" :analysis="detail.result?.ecg_analysis" @inspect="showEvidence" />
              <p class="plain-text">{{ detail.result?.summary || '此任务没有已接收的结果' }}</p>
              <el-alert v-for="(item, i) in detail.result?.warnings || []" :key="'warning-' + i" type="warning" :closable="false" :title="item" class="spaced" />
              <p v-for="(item, i) in detail.result?.missing_data || []" :key="'missing-' + i">待补资料：{{ item }}</p>
              <section v-for="(item, i) in detail.result?.sections || []" :key="i"><h4>{{ item.title }}</h4><p class="plain-text">{{ item.content }}</p><el-button v-for="id in item.source_ids" :key="id" link @click="showEvidence(id)">查看依据 {{ id }}</el-button></section>
            </el-tab-pane>
            <el-tab-pane label="人工反馈" name="feedback">
              <el-table :data="detail.feedback || []" empty-text="尚无人工反馈"><el-table-column prop="reviewer_id" label="复核用户ID" width="110" /><el-table-column label="反馈" width="110"><template #default="{ row }">{{ outcomes[row.outcome] }}</template></el-table-column><el-table-column prop="comment" label="说明" min-width="240" /><el-table-column prop="create_time" label="时间" width="180" /></el-table>
              <p v-if="detail.feedback_truncated">仅展示最近 100 条反馈。</p>
            </el-tab-pane>
            <el-tab-pane label="调用时 Prompt" name="prompt"><h4>固定系统 Prompt</h4><pre class="plain-text">{{ detail.frozen_request?.system_prompt || '未保存原文' }}</pre><h4>任务 Prompt</h4><pre class="plain-text">{{ detail.frozen_request?.task_prompt }}</pre></el-tab-pane>
            <el-tab-pane label="模型与验证快照" name="model"><el-descriptions :column="1" border><el-descriptions-item label="请求模型">{{ detail.frozen_request?.provider_snapshot?.model || '未保存' }}</el-descriptions-item><el-descriptions-item label="服务地址">{{ detail.frozen_request?.provider_snapshot?.api_base || '未保存' }}</el-descriptions-item><el-descriptions-item label="输出上限">{{ detail.frozen_request?.provider_snapshot?.effective_output_limit ?? '未保存' }}</el-descriptions-item><el-descriptions-item label="当时验证记录">{{ detail.frozen_request?.feature_validation?.note || '未保存' }}</el-descriptions-item><el-descriptions-item label="适配器验证记录">{{ detail.frozen_request?.provider_snapshot?.validation_report || '未登记' }}</el-descriptions-item></el-descriptions></el-tab-pane>
            <el-tab-pane label="调用时资料与工具" name="input"><pre class="plain-text">{{ JSON.stringify(detail.frozen_request?.payload || {}, null, 2) }}</pre></el-tab-pane>
          </el-tabs>
        </template>
      </div>
    </el-dialog>
    <el-dialog v-model="evidenceVisible" title="任务原始依据" width="min(800px, 96vw)" append-to-body><h4>{{ evidence?.title }}</h4><p>{{ evidence?.observed_at }}</p><pre class="plain-text">{{ evidence?.content }}</pre></el-dialog>
  </div>
</template>

<script setup>
import { computed, defineAsyncComponent, onActivated, onBeforeUnmount, onDeactivated, onMounted, ref, watch } from "vue";
import { useStore } from "vuex";
import { ElMessage, ElMessageBox } from "element-plus";
import { cancelAIRun, getAIAdminRuns, getAIAdminRunTrace } from "@/api/ai";
import AiSpeechFindings from "@/components/AISpeechFindings/index.vue";
import AiImageFindings from "@/components/AIImageFindings/index.vue";
import AiEcgFindings from "@/components/AIEcgFindings/index.vue";
import { resolveSurgeryEvidence, verifySurgeryRun } from "@/api/ai/surgeryScenarios";
import {resolveSupplyEvidence,verifySupplyRun} from "@/api/ai/supplyResults";
import { supportCanonical, supportId } from "@/api/inpatientSupport";
const AiSupplyFindings=defineAsyncComponent(()=>import("@/components/SupplyFindings.vue"));
const AiSurgeryFindings=defineAsyncComponent(()=>import("@/components/AISurgeryFindings.vue"));
const props = defineProps({ features: { type: Array, default: () => [] }, active: { type: Boolean, default: true } });
const store=useStore(),roles=computed(()=>store.getters['user/permissions']||[]),allowed=computed(()=>props.active&&!!store.state.user.accessToken&&roles.value.includes('super_admin'));
const auth=()=>supportCanonical([props.active,store.state.user.accessToken,store.state.user.username,roles.value]);
const states = { queued: "排队中", running: "生成中", succeeded: "待业务复核", failed: "失败", cancelled: "已取消" };
const outcomes = { accepted: "采纳", rejected: "驳回", modified: "修改后采纳" };
const rows = ref([]), loading = ref(false), page = ref(1), total = ref(0), filters = ref({ feature_key: "", status: "", outcome: "", requested_by: undefined, patient_id: undefined, department_id: undefined, surgery_pool_id:'',surgery_scenario_id:'',supply_item_kind:'',supply_item_id:undefined,supply_series_id:'' });
const visible = ref(false), detail = ref(null), detailLoading = ref(false), detailTab = ref("result"), evidenceVisible = ref(false), evidence = ref(null);
let listVersion = 0, detailVersion = 0;
let wasDeactivated = false;
let alive=true;
const current=key=>alive&&!wasDeactivated&&allowed.value&&key===auth();
const hasSurgery=value=>!!value?.surgery_findings||!!value?.result?.surgery_analysis||!!value?.frozen_request?.payload?.context?.surgery_binding||!!value?.frozen_request?.payload?.input?.surgery_scenario_id||String(value?.frozen_request?.provider_snapshot?.model||'').startsWith('surgery:');
const hasSupply=value=>!!value?.supply_findings||!!value?.result?.supply_analysis||['supply_binding','supply_source','supply_series'].some(name=>!!value?.frozen_request?.payload?.context?.[name])||!!value?.frozen_request?.payload?.input?.supply_series_id||String(value?.frozen_request?.provider_snapshot?.model||'').startsWith('supply:');
function clear(){++listVersion;++detailVersion;rows.value=[];total.value=0;detail.value=null;evidence.value=null;visible.value=evidenceVisible.value=false;loading.value=detailLoading.value=false;}
async function load(reset = false) {
  if(!allowed.value||!alive||wasDeactivated)return;
  if (reset) page.value = 1;
  const version = ++listVersion,key=auth(); loading.value = true;
  const params = Object.fromEntries(Object.entries(filters.value).filter(([, value]) => value !== "" && value != null));
  if(['supply_series_id','surgery_pool_id','surgery_scenario_id'].some(name=>params[name]&&!supportId(params[name]))){loading.value=false;ElMessage.warning('原序列、资源池与场景过滤须为明确规范UUID');return;}
  if((!!params.supply_item_kind)!==(params.supply_item_id!==undefined)||params.supply_item_kind&&!['pharmaceutical','consumable'].includes(params.supply_item_kind)||params.supply_item_id!==undefined&&(!Number.isSafeInteger(params.supply_item_id)||params.supply_item_id<1)){loading.value=false;ElMessage.warning('物资审计须同时明确有效类型与整数标识');return;}
  try { const response = await getAIAdminRuns({ ...params, page: page.value, page_size: 30 }); if (current(key)&&version === listVersion) { rows.value = response.data || []; total.value = response.total || 0; } }
  catch { if(current(key)&&version===listVersion){clear();ElMessage.warning('当前任务目录或审计权限无法重新核对，旧资料已清除');} }
  finally { if (current(key)&&version === listVersion) loading.value = false; }
}
async function inspect(row) {
  if(!allowed.value||!alive||wasDeactivated)return;
  const version = ++detailVersion,key=auth(); visible.value = true; detail.value = null; evidence.value=null;evidenceVisible.value=false;detailTab.value = "result"; detailLoading.value = true;
  try { const response = await getAIAdminRunTrace(row.run_id);if(!current(key)||version!==detailVersion)return;const value=response.data;if(value?.run_id!==row.run_id||hasSupply(value)&&!await verifySupplyRun(value,{}, {auditOnly:true,current:()=>current(key)&&version===detailVersion})||hasSurgery(value)&&!await verifySurgeryRun(value)){if(current(key)&&version===detailVersion)ElMessage.warning('原任务或完整冻结来源及固定结果无法核对，暂不展示');return;}if(current(key)&&version===detailVersion)detail.value=value; }
  catch { if(current(key)&&version===detailVersion){clear();ElMessage.warning('当前完整任务或审计权限无法重新核对，旧资料已清除');} }
  finally { if (current(key)&&version === detailVersion) detailLoading.value = false; }
}
async function showEvidence(id) { const key=auth(),version=detailVersion,original=detail.value;evidence.value=null;evidenceVisible.value=false;if(!current(key)||!original)return;const item=original.evidence?.find(value=>value.source_id===id),value=hasSupply(original)?await resolveSupplyEvidence(item,original.supply_findings,{}, {auditOnly:true,current:()=>current(key)&&version===detailVersion}):hasSurgery(original)?await resolveSurgeryEvidence(item,original.surgery_findings):item;if(current(key)&&version===detailVersion&&original===detail.value){evidence.value=value;evidenceVisible.value=!!value;} }
async function cancel(row) {
  const key=auth();if(!current(key))return;
  try {
    await ElMessageBox.confirm("取消后将停止接收结果，已发出的模型请求仍可能计费。", "取消任务结果接收", { confirmButtonText: "取消接收", cancelButtonText: "保留任务", type: "warning" });
    if(!current(key))return;await cancelAIRun(row.run_id);if(!current(key))return;ElMessage.success("任务结果已取消接收"); await load();
  } catch (error) { if (error !== "cancel" && error !== "close"&&current(key)){clear();ElMessage.warning('当前任务或取消权限已经变化，请重新核对');} }
}
watch(()=>filters.value.feature_key,value=>{if(value!=='surgery_scheduling'){filters.value.department_id=undefined;filters.value.surgery_pool_id=filters.value.surgery_scenario_id='';}if(value!=='supply_forecast'){filters.value.supply_item_kind='';filters.value.supply_item_id=undefined;filters.value.supply_series_id='';}},{flush:'sync'});
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
