<template>
  <el-dialog :model-value="!!target && allowed" title="本地qSOFA规则服务核对" width="min(820px, 95vw)" @update:model-value="visible => { if (!visible) close(); }">
    <div v-loading="loading">
      <p>核对已保存服务：{{ target?.name }}。只读取规则与运行声明，不发送患者点测、GCS、感染声明或创建计分任务。</p>
      <template v-if="result">
        <el-alert :type="result.compatible ? 'success' : 'warning'" :closable="false" :title="result.compatible ? '服务声明与登记配置匹配；临床适用性及效果仍待验证' : '登记配置与服务声明存在差异'" />
        <p v-for="issue in result.issues || []" :key="issue">{{ issue }}</p>
        <el-descriptions :column="1" border class="qsofa-description">
          <el-descriptions-item v-for="row in descriptions" :key="row[0]" :label="row[0]"><span class="digest">{{ row[1] }}</span></el-descriptions-item>
        </el-descriptions>
        <p>{{ result.scope_note }}</p>
      </template>
    </div>
    <template #footer>
      <el-button @click="close">关闭</el-button>
      <el-button v-if="result && target?.model !== result.capabilities.model_version" @click="useModel">填写实际模型，待保存</el-button>
    </template>
  </el-dialog>
</template>

<script setup>
import { computed, onBeforeUnmount, onDeactivated, ref, watch } from "vue";
import { useStore } from "vuex";
import { ElMessage } from "element-plus";
import { checkQsofaProvider } from "@/api/aiQsofa";

const props = defineProps({ target: { type: Object, default: null }, providers: { type: Array, default: () => [] } });
const emit = defineEmits(["close", "edit-model"]);
const store = useStore();
const allowed = computed(() => !!store.state.user.accessToken && store.state.user.permissions.includes("super_admin"));
const result = ref(null), loading = ref(false);
const descriptions = computed(() => {
  const cap = result.value?.capabilities;
  return cap ? [
    ["实际模型", cap.model_version],
    ["固定规则", "Sepsis-3 2016 qSOFA三项独立固定计数；不是脓毒症诊断、排除或风险概率。"],
    ["选择策略", "明确原呼吸频率、收缩压和完整原GCS分项；同次检查须明确关联，不自动拼接最近记录。"],
    ["适用性", "医生现在回顾核实原观察时的成人、非ICU与疑似/明确感染；不冒充原截止时已知的信息。"],
    ["缺项与下界", "缺项或NT不补1分或总GCS；保留已知小计下界，未达两项不能排除脓毒症。"],
    ["实际运行环境", `Python ${cap.python_version}；${Object.entries(cap.engine_versions || {}).map(([name, version]) => `${name} ${version}`).join(' ')}`],
    ["请求限制", `最大 ${cap.max_request_bytes} 字节；服务时限 ${cap.timeout_seconds} 秒，模型请求另留传输时间。`],
    ["Prompt", "仅用于溯源，不改变固定判据或数值。"],
    ["筛查用途", "SSC 2026不推荐将qSOFA作为单一脓毒症筛查工具。"],
    ["临床验证", `${cap.clinical_validation}：能力检查和数值测试不代替实际临床验证。`],
    ["规则摘要", cap.recipe_digest], ["运行摘要", cap.runtime_digest],
  ] : [];
});
let epoch = 0, session = null;
function current() {
  const row = props.providers.find(item => item.provider_id === props.target?.provider_id);
  return allowed.value && session === store.state.user.accessToken && props.target?.session === session && row && row.revision === props.target.revision && row.model === props.target.model && row.kind === "specialist" && row.supported_features?.includes("sepsis_risk") ? row : null;
}
function close() { epoch++; result.value = null; loading.value = false; session = null; emit("close"); }
watch(() => props.target, async target => {
  const requestEpoch = ++epoch;
  result.value = null; loading.value = false; session = target?.session;
  if (!target || !current()) return;
  loading.value = true;
  try {
    const response = await checkQsofaProvider(target.provider_id, target.revision);
    if (requestEpoch !== epoch || !current()) return;
    const data = response.data;
    if (data?.provider_id !== target.provider_id || data.provider_revision !== target.revision || data.configured_model !== target.model || !/^qsofa:[a-f0-9]{64}$/.test(data.capabilities?.model_version || "") || data.capabilities.schema_version !== "8" || data.capabilities.feature_key !== "sepsis_risk") {
      ElMessage.warning("核对回执与已保存qSOFA服务配置不一致，请刷新后重试"); return;
    }
    result.value = data;
  } catch { /* The shared request layer reports sanitized connection/configuration errors. */ }
  finally { if (requestEpoch === epoch) loading.value = false; }
}, { immediate: true });
watch([() => store.state.user.accessToken, () => JSON.stringify(store.state.user.permissions)], close);
watch(() => JSON.stringify(props.providers.map(item => [item.provider_id, item.revision, item.model, item.kind, item.supported_features])), () => { if (props.target && !current()) close(); });
function useModel() {
  const row = current(), checked = result.value;
  if (!row || !checked || checked.provider_id !== row.provider_id || checked.provider_revision !== row.revision || checked.configured_model !== row.model) {
    ElMessage.warning("已保存qSOFA服务配置或管理权限已变化，请重新核对"); close(); return;
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
