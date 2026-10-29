<template>
  <el-dialog :model-value="!!target && allowed" :title="`本地${label}${mode==='roster'?'优化':'规则'}服务核对`" width="min(820px, 95vw)" @update:model-value="visible => { if (!visible) close(); }">
    <div v-loading="loading">
      <p>核对已保存服务：{{ target?.name }}。{{ mode==='roster'?'只读取优化器运行与固定政策声明，不发送人员或需求，不创建优化任务。':'只读取规则与运行声明，不发送患者原测量、临床判读、基线或创建计分任务。' }}</p>
      <template v-if="result">
        <el-alert :type="result.compatible ? 'success' : 'warning'" :closable="false" :title="result.compatible ? mode==='roster'?'服务声明与登记配置匹配；运营适用性和效果仍须本地验证':'服务声明与登记配置匹配；临床适用性及效果仍待验证' : '登记配置与服务声明存在差异'" />
        <p v-for="issue in result.issues || []" :key="issue">{{ issue }}</p>
        <el-descriptions :column="1" border class="qsofa-description">
          <el-descriptions-item v-for="row in descriptions" :key="row[0]" :label="row[0]"><span class="digest">{{ row[1] }}</span></el-descriptions-item>
        </el-descriptions>
        <p v-if="noticeText(result.scope_note)">{{ noticeText(result.scope_note) }}</p>
      </template>
    </div>
    <template #footer>
      <el-button @click="close">关闭</el-button>
      <el-button v-if="result && target?.model !== result.capabilities.model_version" @click="useModel">填写实际模型，待保存</el-button>
    </template>
  </el-dialog>
</template>

<script setup>
import { noticeText, noticeList } from "@/utils/noticeText.cjs";
import { computed, onBeforeUnmount, onDeactivated, ref, watch } from "vue";
import { useStore } from "vuex";
import { ElMessage } from "element-plus";
import {checkRosterProvider,verifyRosterCapabilities} from "@/api/rosterPlans";
import { checkSofaProvider } from "@/api/aiSofa";
import { checkQsofaProvider } from "@/api/aiQsofa";

const props = defineProps({ mode: {type:String,default:"qsofa"}, target: { type: Object, default: null }, providers: { type: Array, default: () => [] } });
const label=computed(()=>props.mode==="roster"?"排班":props.mode==="sofa1"?"SOFA":"qSOFA"),feature=computed(()=>props.mode==="roster"?"roster_optimization":"sepsis_risk");
const emit = defineEmits(["close", "edit-model"]);
const store = useStore();
const allowed = computed(() => ["qsofa","sofa1","roster"].includes(props.mode)&&!!store.state.user.accessToken && store.state.user.permissions.includes("super_admin"));
const result = ref(null), loading = ref(false);
const descriptions = computed(() => {
  const cap = result.value?.capabilities;
  if(cap&&props.mode==="roster")return[
    ['实际模型',cap.model_version],['固定优化目标','满足硬需求后最小化惩罚；或先最大化计划净服务量，再最小化惩罚，不混成任意权重。'],['完整原资料','完整本科人员、每人每会话配对、受审资格/可用性与全地点工时上下文；未知项保留。'],['最优性证明','分别记录可行解、搜索边界、差距和终止原因。'],['候选用途','按审核后的容量情景生成排班候选。'],['实际运行环境',`Python ${cap.python_version}；${Object.entries(cap.engine_versions).map(([key,v])=>`${key} ${v}`).join(' ')}`],['时区库摘要',cap.timezone_database_digest],['请求限制',`最大${cap.max_request_bytes}字节；服务时限${cap.timeout_seconds}秒。`],['运营验证',`${cap.operational_validation}：来源审核、数值测试和能力声明均不代替实际运营效果验证。`],['Prompt','记录本次排班版本。'],['规则摘要',cap.recipe_digest],['输入政策摘要',cap.input_policy_digest],['运行摘要',cap.runtime_digest],['四核心摘要',JSON.stringify(cap.core_sha256)]
  ];
  if(cap&&props.mode==="sofa1")return[
    ["实际模型",cap.model_version],
    ["固定规则","SOFA-1六轴、24小时评估，按原单位评分。"],
    ["来源与协议","保留全部原成员、日前必要给药前缀、逐源医生用途判读、冲突和记录协议；不自动选择最近来源或补正常。"],
    ["部分与完整","明确观测小计、上下界、数值收敛与完整协议总分分别保留；基线未知与条件性零假设分开，变化保留负数。"],
    ["实际运行环境",`Python ${cap.python_version}；${Object.entries(cap.engine_versions||{}).map(([name,version])=>`${name} ${version}`).join(' ')}`],
    ["请求限制",`最大 ${cap.max_request_bytes} 字节；服务时限 ${cap.timeout_seconds} 秒。`],
    ["Prompt","记录本次计算版本。"],
    ["临床验证",`${cap.clinical_validation}：能力声明和数值测试不代替实际临床验证。`],
    ["规则摘要",cap.recipe_digest],["输入政策摘要",cap.policy_digest],["运行摘要",cap.runtime_digest]
  ];
  return cap ? [
    ["实际模型", cap.model_version],
    ["固定规则", "采用Sepsis-3 2016 qSOFA三项固定计数。"],
    ["选择策略", "明确原呼吸频率、收缩压和完整原GCS分项；同次检查须明确关联，不自动拼接最近记录。"],
    ["适用性", "采用医生本次回顾的年龄、病区和感染记录。"],
    ["缺项与下界", "缺项或NT不补1分或总GCS；保留已知小计下界，未达两项不能排除脓毒症。"],
    ["实际运行环境", `Python ${cap.python_version}；${Object.entries(cap.engine_versions || {}).map(([name, version]) => `${name} ${version}`).join(' ')}`],
    ["请求限制", `最大 ${cap.max_request_bytes} 字节；服务时限 ${cap.timeout_seconds} 秒，模型请求另留传输时间。`],
    ["Prompt", "记录本次计算版本。"],
    ["筛查用途", "SSC 2026不推荐将qSOFA作为单一脓毒症筛查工具。"],
    ["临床验证", `${cap.clinical_validation}：能力检查和数值测试不代替实际临床验证。`],
    ["规则摘要", cap.recipe_digest], ["运行摘要", cap.runtime_digest],
  ] : [];
});
let epoch = 0, session = null;
function current() {
  const row = props.providers.find(item => item.provider_id === props.target?.provider_id);
  return allowed.value && session === store.state.user.accessToken && props.target?.session === session && row && row.revision === props.target.revision && row.model === props.target.model && row.kind === "specialist" && row.supported_features?.includes(feature.value) ? row : null;
}
function close() { epoch++; result.value = null; loading.value = false; session = null; emit("close"); }
watch(() => [props.target,props.mode], async ([target]) => {
  const requestEpoch = ++epoch;
  result.value = null; loading.value = false; session = target?.session;
  if (!target || !current()) return;
  loading.value = true;
  try {
    const response = await (props.mode==="roster"?checkRosterProvider:props.mode==="sofa1"?checkSofaProvider:checkQsofaProvider)(target.provider_id, target.revision);
    if (requestEpoch !== epoch || !current()) return;
    const data = response.data;
    if (data?.provider_id !== target.provider_id || data.provider_revision !== target.revision || data.configured_model !== target.model || !(props.mode==="roster"?/^roster:[a-f0-9]{64}$/:props.mode==="sofa1"?/^sofa1:[a-f0-9]{64}$/:/^qsofa:[a-f0-9]{64}$/).test(data.capabilities?.model_version || "") || data.capabilities.schema_version !== (props.mode==="roster"?"10":props.mode==="sofa1"?"9":"8") || data.capabilities.feature_key !== feature.value) {
      ElMessage.warning(`核对回执与已保存${label.value}服务配置不一致，请刷新后重试`); return;
    }
    if(props.mode==='roster'&&(typeof data.compatible!=='boolean'||!Array.isArray(data.issues)||data.issues.some(v=>typeof v!=='string')||typeof data.scope_note!=='string'||!await verifyRosterCapabilities(data.capabilities)))return;
    if(requestEpoch!==epoch||!current())return;
    result.value = data;
  } catch { /* The shared request layer reports sanitized connection/configuration errors. */ }
  finally { if (requestEpoch === epoch) loading.value = false; }
}, { immediate: true });
watch([() => store.state.user.accessToken, () => JSON.stringify(store.state.user.permissions)], close);
watch(() => JSON.stringify(props.providers.map(item => [item.provider_id, item.revision, item.model, item.kind, item.supported_features])), () => { if (props.target && !current()) close(); });
function useModel() {
  const row = current(), checked = result.value;
  if (!row || !checked || checked.provider_id !== row.provider_id || checked.provider_revision !== row.revision || checked.configured_model !== row.model) {
    ElMessage.warning(`已保存${label.value}服务配置或管理权限已变化，请重新核对`); close(); return;
  }
  emit("edit-model", { provider_id: row.provider_id, revision: row.revision, configured_model: row.model, model: checked.capabilities.model_version, session });
  close();
}
onDeactivated(close);
onBeforeUnmount(close);
</script>

<style scoped>
.qsofa-description { margin-top: 12px; }
.digest { overflow-wrap: anywhere; }
</style>
