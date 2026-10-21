<template>
  <el-dialog :model-value="!!target && allowed" title="本地库存候选比较服务核对" width="min(850px,95vw)" @update:model-value="value => !value && close()">
    <div v-loading="loading">
      <p>核对已保存服务 {{ target?.name }}。平台仅鉴权读取服务能力声明，不发送库存原件或问题，不创建比较任务。</p>
      <p v-if="error" role="alert">{{ error }}</p>
      <template v-if="result">
        <el-alert :type="result.compatible ? 'success' : 'warning'" :closable="false" :title="result.compatible ? '服务声明与登记配置匹配，运营适用性和效果仍须独立验证' : '已保存配置与服务实际声明存在差异'" />
        <p v-for="issue in result.issues" :key="issue">{{ issue }}</p>
        <el-descriptions :column="1" border><el-descriptions-item v-for="[label, value] in rows" :key="label" :label="label"><span class="hash">{{ value }}</span></el-descriptions-item></el-descriptions>
        <p>{{ result.scope_note }}</p>
        <p>在人工声明的完整有限候选中比较；保留全部并列项，不证明全集之外的最优，不自动采购、选单、处置或改库存。</p>
        <p>能力核对不启用功能、不改变验证状态。填写实际模型只回填编辑表单，仍须核对并保存当前版本。</p>
      </template>
    </div>
    <template #footer><el-button @click="close">关闭</el-button><el-button v-if="result && target?.model !== result.capabilities.model_version" @click="editModel">填写实际模型，待保存</el-button></template>
  </el-dialog>
</template>

<script setup>
import { computed, onBeforeUnmount, onDeactivated, ref, watch } from 'vue';
import { useStore } from 'vuex';
import { checkInventoryProvider, verifyInventoryProviderCheck } from '@/api/ai/inventoryProvider';

const props = defineProps({ target: { type: Object, default: null }, providers: { type: Array, default: () => [] } }), emit = defineEmits(['close', 'edit-model']), store = useStore();
const result = ref(null), loading = ref(false), error = ref('');
let epoch = 0, identity = null, alive = true;
const roles = computed(() => store.getters['user/permissions'] || []);
const allowed = computed(() => !!store.state.user.accessToken && roles.value.includes('super_admin'));
const sessionIdentity = () => JSON.stringify([store.state.user.accessToken, store.state.user.username, roles.value]);
const rows = computed(() => {
  const c = result.value?.capabilities;
  return c ? [
    ['实际模型', c.model_version],
    ['声明范围', '单实际品种、原计数单位、未来1至31个完整业务日、完整有限采购候选与零订单原候选。'],
    ['共同约束', '全部候选共享逐日期末最小可用量、最大总量及明确预算；原币种和成本单位不自动换算。'],
    ['固定计算', '日初失效、收货、FEFO分配和期末约束；完整逐日守恒与批次账。'],
    ['原量边界', '独立实盘与数据库采集区分；已知零、未知、负量、冻结、效期、专业确认与集合缺口分别保留。'],
    ['成本口径', '全部订购量价款、订单费用及方案费用；包括未用或过期的订购量，不冒充完整经济成本。'],
    ['真实运行环境', `Python ${c.python_version}；${Object.entries(c.engine_versions).map(([k, v]) => k + ' ' + v).join('；')}`],
    ['四核心文件', Object.entries(c.core_sha256).map(([k, v]) => k + ': ' + v).join('；')],
    ['时区库', c.timezone_database_digest],
    ['固定限制', `请求 ${c.max_request_bytes} 字节；响应 ${c.max_response_bytes} 字节；处理时限 ${c.timeout_seconds} 秒。`],
    ['原规则及输入政策', c.recipe_digest + '；' + c.input_policy_digest],
    ['实际运行摘要', c.runtime_digest],
    ['验证', `运营 ${c.operational_validation}；临床 ${c.clinical_validation}。`],
    ['Prompt', '仅作溯源，不改变原量、候选、共同约束或计算结果。'],
  ] : [];
});
function current() {
  const row = props.providers.find(p => p.provider_id === props.target?.provider_id);
  return alive && allowed.value && identity === sessionIdentity() && props.target?.session === store.state.user.accessToken && props.target?.username === store.state.user.username && row && row.revision === props.target.revision && row.model === props.target.model && row.kind === 'specialist' && row.supported_features?.includes('inventory_optimization') ? row : null;
}
function close() { epoch++; result.value = null; loading.value = false; error.value = ''; identity = null; emit('close'); }
watch(() => props.target, async target => {
  const ticket = ++epoch;
  result.value = null; loading.value = false; error.value = ''; identity = sessionIdentity();
  if (!target || !current()) return;
  loading.value = true;
  try {
    const response = await checkInventoryProvider(target.provider_id, target.revision);
    if (ticket !== epoch || !current()) return;
    if (!await verifyInventoryProviderCheck(response.data, target)) throw new Error('完整能力声明与当前已保存库存比较服务不一致，请刷新重试');
    if (ticket === epoch && current()) result.value = response.data;
  } catch (failure) {
    if (ticket === epoch && current()) error.value = failure?.message || '库存候选比较服务核对失败';
  } finally { if (ticket === epoch && current()) loading.value = false; }
}, { immediate: true, deep: true });
watch(sessionIdentity, close, { flush: 'sync' });
watch(() => JSON.stringify(props.providers.map(p => [p.provider_id, p.revision, p.model, p.kind, p.supported_features])), () => { if (props.target && identity !== null && !current()) close(); }, { flush: 'sync' });
function editModel() {
  const row = current(), checked = result.value;
  if (!row || !checked || checked.provider_id !== row.provider_id || checked.provider_revision !== row.revision || checked.configured_model !== row.model) { close(); return; }
  emit('edit-model', { provider_id: row.provider_id, revision: row.revision, configured_model: row.model, model: checked.capabilities.model_version, session: store.state.user.accessToken, username: store.state.user.username }); close();
}
onDeactivated(close); onBeforeUnmount(() => { alive = false; close(); });
</script>

<style scoped>
p { line-height: 1.7; } .hash { overflow-wrap: anywhere; } .el-descriptions { margin: 12px 0; }
</style>
