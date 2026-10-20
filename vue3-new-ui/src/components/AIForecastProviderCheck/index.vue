<template>
  <el-dialog :model-value="!!target && allowed" title="本地统计预测服务核对" width="min(820px, 95vw)" @update:model-value="visible => { if (!visible) close(); }">
    <div v-loading="loading">
      <p>核对已保存服务：{{ target?.name }}。只读取能力声明，不发送日序列，不创建预测任务。</p>
      <template v-if="result">
        <el-alert :type="result.compatible ? 'success' : 'warning'" :closable="false" :title="result.compatible ? '服务声明与登记配置匹配；运营预测效果仍待验证' : '登记配置与服务声明存在差异'" />
        <p v-for="issue in result.issues || []" :key="issue">{{ issue }}</p>
        <el-descriptions :column="1" border class="forecast-description">
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
import { checkAIForecastProvider } from "@/api/aiForecastProbe";

const props = defineProps({ target: { type: Object, default: null }, providers: { type: Array, default: () => [] } });
const emit = defineEmits(["close", "edit-model"]);
const store = useStore();
const allowed = computed(() => !!store.state.user.accessToken && store.state.user.permissions.includes("super_admin"));
const result = ref(null), loading = ref(false);
const descriptions = computed(() => {
  const cap = result.value?.capabilities;
  return cap ? [
    ["实际模型", cap.model_version],
    ["统计目标", "每日挂号创建记录数，包含已取消记录；不是实际到诊人数。"],
    ["固定算法", `${cap.recipe}：最近四周同星期均值；不按回测成绩自动择优。`],
    ["历史与跨度", `${cap.history_min_days}–${cap.history_max_days} 个连续已确认日；外推 ${cap.horizon_days?.join(' / ')} 天。`],
    ["回测与区间", `${cap.backtest_origins} 个滚动起点；名义 ${cap.nominal_coverage * 100}% 经验区间，不保证未来覆盖。`],
    ["实际运行环境", `Python ${cap.python_version}；${Object.entries(cap.engine_versions || {}).map(([name, version]) => `${name} ${version}`).join(' ')}`],
    ["请求限制", `最大 ${cap.max_request_bytes} 字节；服务时限 ${cap.timeout_seconds} 秒，模型请求另留传输时间。`],
    ["Prompt", "仅用于溯源，不改变固定统计数值。"],
    ["效果验证", `${cap.operational_validation}：服务未提供独立运营效果验证；能力核对不修改验证状态。`],
    ["算法摘要", cap.recipe_digest], ["运行摘要", cap.runtime_digest],
  ] : [];
});
let epoch = 0, session = null;
function current() {
  const row = props.providers.find(item => item.provider_id === props.target?.provider_id);
  return allowed.value && session === store.state.user.accessToken && props.target?.session === session && row && row.revision === props.target.revision && row.model === props.target.model && row.kind === "specialist" && row.supported_features?.includes("visit_forecast") ? row : null;
}
function close() { epoch++; result.value = null; loading.value = false; session = null; emit("close"); }
watch(() => props.target, async target => {
  const requestEpoch = ++epoch;
  result.value = null; loading.value = false; session = target?.session;
  if (!target || !current()) return;
  loading.value = true;
  try {
    const response = await checkAIForecastProvider(target.provider_id, target.revision);
    if (requestEpoch !== epoch || !current()) return;
    const data = response.data;
    if (data?.provider_id !== target.provider_id || data.provider_revision !== target.revision || data.configured_model !== target.model || !data.capabilities?.model_version) {
      ElMessage.warning("核对回执与已保存统计服务配置不一致，请刷新后重试"); return;
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
    ElMessage.warning("已保存统计服务配置或管理权限已变化，请重新核对"); close(); return;
  }
  emit("edit-model", { provider_id: row.provider_id, revision: row.revision, configured_model: row.model, model: checked.capabilities.model_version, session });
  close();
}
onDeactivated(close);
onBeforeUnmount(close);
</script>

<style scoped>
.forecast-description { margin-top: 12px; }
.digest { overflow-wrap: anywhere; }
</style>
