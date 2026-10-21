<template>
  <section aria-label="受审库存候选比较入口">
    <p v-if="!allowed">当前身份无法使用库存候选比较。</p>
    <template v-else>
      <p>明确一个真实品种，核对独立库存观察、未来出库情景和完整有限采购候选。全部候选使用同一预算及逐日约束，保留未知和全部并列项。</p>
      <el-form inline @submit.prevent="refresh">
        <el-form-item label="库存品种类型"><el-select :model-value="kind" @update:model-value="editKind" aria-label="库存品种类型" clearable :disabled="businessLocked" placeholder="明确药品或耗材"><el-option value="pharmaceutical" label="药品" /><el-option value="consumable" label="耗材" /></el-select></el-form-item>
        <el-form-item v-if="!businessLocked" label="查找库存品种"><el-input v-model="search" aria-label="查找库存品种" placeholder="名称，药品也可按条码" :disabled="!kind" /><el-button @click="searchItems" :disabled="!kind">查找库存品种</el-button></el-form-item>
        <el-form-item label="库存品种"><el-select :model-value="item" @update:model-value="editItem" aria-label="库存品种" clearable :disabled="businessLocked || !kind" placeholder="明确真实品种，不默认首项"><el-option v-for="row in options?.items || []" :key="row.item_id" :value="row.item_id" :label="`${row.name || '原目录品种'} · #${row.item_id}`" /></el-select></el-form-item>
        <el-button native-type="submit" :loading="loading">重新核对库存范围</el-button><el-button v-if="chosen" @click="clearSelection">清除库存比较场景</el-button>
      </el-form>
      <div v-if="!businessLocked && options && !item && options.total > 20" aria-label="库存品种目录分页"><el-button :disabled="page <= 1 || loading" @click="changePage(-1)">上一页品种</el-button><span>第 {{ page }} 页，共 {{ options.total }} 个当前目录品种</span><el-button :disabled="page * 20 >= options.total || loading" @click="changePage(1)">下一页品种</el-button></div>
      <p v-if="error" role="alert">{{ error }}</p><p v-if="checking" role="status">正在核对完整原件、共同约束、全部候选与当前治理。</p>
      <p v-if="chosen" class="hash" aria-label="已绑定库存比较场景">{{ selectedSku?.name || '原目录品种' }} · #{{ item }}；原场景 {{ chosen.public_source.source_id }}；{{ chosen.public_source.date_from }} 至 {{ chosen.public_source.date_to }}；完整 {{ chosen.public_source.candidates.length }} 个已声明候选。完整原件 {{ chosen.content_hash }}；公开投影 {{ chosen.projection_hash }}。</p>
      <template v-if="scopeReady">
        <details @toggle="sourcesOpen = $event.target.open"><summary>登记与核对独立库存观察、未来出库情景及原采购候选</summary><inventory-sources-panel v-if="sourcesOpen" :key="`sources-${childKey}`" :item-kind="kind" :item-id="item" :active="active" @source-changed="sourcesChanged" @invalidate="scenarioUnavailable" /></details>
        <inventory-scenarios-panel :key="`scenarios-${childKey}-${scenarioKey}`" :item-kind="kind" :item-id="item" :active="active" @select="selectScenario" @scenario-changed="scenariosChanged" @invalidate="scenarioUnavailable" />
      </template>
      <p v-else>先选择当前真实目录中的一个品种，再核对受审完整场景。</p>
      <p>比较结果等待人工复核，不自动选择、生成采购单、处置或改库存。采购成本口径不包含完整经济成本。</p>
    </template>
  </section>
</template>

<script setup>
import { computed, defineAsyncComponent, onActivated, onBeforeUnmount, onDeactivated, ref, watch } from 'vue';
import { useStore } from 'vuex';
import { getInventorySourceOptions, inventorySourceOptionsValid, inventorySourcePositive } from '@/api/ai/inventorySources';
import { getInventoryScenarioRecord, inventoryScenarioReferencesValid, verifyInventoryScenario } from '@/api/ai/inventoryScenarios';
import { supportCanonical, supportId } from '@/api/inpatientSupport';

const InventorySourcesPanel = defineAsyncComponent(() => import('./InventorySources.vue'));
const InventoryScenariosPanel = defineAsyncComponent(() => import('./InventoryScenarios.vue'));
const props = defineProps({ itemKind: { type: String, default: null }, itemId: { type: Number, default: null }, initialReferences: { type: Object, default: null }, active: { type: Boolean, default: true } });
const emit = defineEmits(['scope-change', 'selection', 'availability', 'invalidate']), store = useStore();
const roles = computed(() => store.getters['user/permissions'] || []);
const allowed = computed(() => props.active && !!store.state.user.accessToken && roles.value.some(role => ['super_admin', 'admin', 'director', 'pharmacist'].includes(role)));
const kindValid = value => ['pharmaceutical', 'consumable'].includes(value);
const referencesValid = value => value !== null && typeof value === 'object' && !Array.isArray(value) && supportCanonical(Object.keys(value)) === supportCanonical(['inventory_scenario_id']) && supportId(value.inventory_scenario_id);
const kind = ref(props.itemKind), item = ref(props.itemId), search = ref(''), page = ref(1);
const options = ref(null), selectedSku = ref(null), chosen = ref(null), loading = ref(false), checking = ref(false), error = ref(''), sourcesOpen = ref(false), childKey = ref(0), scenarioKey = ref(0);
const businessLocked = computed(() => props.itemKind !== null || props.itemId !== null);
let epoch = 0, catalogSequence = 0, selectionSequence = 0, alive = true, paused = false, initialReferenceAllowed = true;
const identity = () => supportCanonical([props.itemKind, props.itemId, props.initialReferences, props.active, kind.value, item.value, store.state.user.accessToken, store.state.user.username, roles.value]);
const ticket = () => ({ epoch, identity: identity() });
const current = token => alive && !paused && allowed.value && token.epoch === epoch && token.identity === identity();
const scopeReady = computed(() => allowed.value && kindValid(kind.value) && inventorySourcePositive(item.value) && selectedSku.value?.item_kind === kind.value && selectedSku.value.item_id === item.value && selectedSku.value.status === 0);
function invalidate() { selectionSequence++; checking.value = false; chosen.value = null; emit('selection', null); emit('availability', false); emit('invalidate'); }
function reset() { epoch++; catalogSequence++; options.value = null; selectedSku.value = null; sourcesOpen.value = false; loading.value = false; error.value = ''; childKey.value++; invalidate(); emit('scope-change', null); }
function unavailable(message) { reset(); error.value = message || '当前品种、完整来源或治理无法核对，旧选择已清除。'; }
async function refresh() {
  invalidate(); options.value = null; selectedSku.value = null; emit('scope-change', null); childKey.value++;
  const token = ticket(), sequence = ++catalogSequence;
  if (!current(token)) return;
  loading.value = true; error.value = '';
  try {
    if (businessLocked.value && (!kindValid(props.itemKind) || !inventorySourcePositive(props.itemId) || kind.value !== props.itemKind || item.value !== props.itemId)) throw new Error('业务入口须同时绑定真实库存品种类型与标识。');
    if (kind.value !== null && !kindValid(kind.value) || item.value !== null && !inventorySourcePositive(item.value) || item.value !== null && kind.value === null) throw new Error('库存品种类型或标识无效。');
    if (props.initialReferences !== null && !referencesValid(props.initialReferences)) throw new Error('库存原引用须仅包含一个规范场景标识。');
    if (initialReferenceAllowed && !kind.value && props.initialReferences !== null) {
      const original = (await getInventoryScenarioRecord(props.initialReferences.inventory_scenario_id, { auditOnly: false })).data;
      if (!current(token) || sequence !== catalogSequence) return;
      if (original.scenario_id !== props.initialReferences.inventory_scenario_id || original.audit_only !== false || !original.eligible || !await verifyInventoryScenario(original, { auditOnly: false })) throw new Error('原库存比较场景当前无法用于执行。');
      if (!current(token) || sequence !== catalogSequence) return;
      kind.value = original.item_kind; item.value = original.item_id; return;
    }
    const requested = { page: item.value === null ? page.value : 1, page_size: 20, ...(kind.value ? { item_kind: kind.value } : {}), ...(item.value !== null ? { item_id: item.value } : {}), ...(item.value === null && search.value ? { keyword: search.value } : {}) };
    const value = (await getInventorySourceOptions(requested)).data;
    if (!current(token) || sequence !== catalogSequence) return;
    if (!inventorySourceOptionsValid(value, requested)) throw new Error('当前真实库存目录的身份、分页或范围无法核对。');
    options.value = value;
    if (item.value !== null) {
      if (value.items.length !== 1) throw new Error('所选库存品种已经失效或不在当前目录范围。');
      selectedSku.value = value.items[0]; emit('scope-change', { item_kind: kind.value, item_id: item.value, scope: 'hospital_inventory' });
    }
    if (initialReferenceAllowed && props.initialReferences !== null && scopeReady.value) await selectScenario(props.initialReferences);
  } catch (failure) { if (current(token) && sequence === catalogSequence) unavailable(failure.message); }
  finally { if (current(token) && sequence === catalogSequence) loading.value = false; }
}
async function selectScenario(reference) {
  invalidate(); const token = ticket(), sequence = selectionSequence;
  if (!current(token) || !scopeReady.value) return;
  checking.value = true; error.value = '';
  try {
    if (!inventoryScenarioReferencesValid(reference)) throw new Error('库存场景选择必须为一个明确原引用。');
    const row = (await getInventoryScenarioRecord(reference.inventory_scenario_id, { auditOnly: false })).data;
    if (!current(token) || sequence !== selectionSequence) return;
    if (row.scenario_id !== reference.inventory_scenario_id || row.audit_only !== false || !row.eligible || !row.public_source || !await verifyInventoryScenario(row, { itemKind: kind.value, itemId: item.value, auditOnly: false })) throw new Error('库存原量、单位、共同约束、完整候选或当前治理无法核对。');
    if (!current(token) || sequence !== selectionSequence) return;
    chosen.value = row; emit('selection', { inventory_scenario_id: row.scenario_id }); emit('availability', true);
  } catch (failure) { if (current(token) && sequence === selectionSequence) unavailable(failure.message); }
  finally { if (current(token) && sequence === selectionSequence) checking.value = false; }
}
function editKind(value) { initialReferenceAllowed = false; kind.value = value || null; }
function editItem(value) { initialReferenceAllowed = false; item.value = value || null; }
function clearSelection() { initialReferenceAllowed = false; invalidate(); }
function searchItems() { initialReferenceAllowed = false; page.value = 1; if (item.value !== null) item.value = null; else refresh(); }
function changePage(change) { page.value += change; refresh(); }
function sourcesChanged() { invalidate(); scenarioKey.value++; error.value = '原库存观察、单位或候选已变化，请重新核对完整场景。'; }
function scenariosChanged() { invalidate(); error.value = '原场景治理已变化，请重新读取完整原件。'; }
function scenarioUnavailable() { const selected = chosen.value !== null || checking.value; invalidate(); if (selected) error.value = '当前场景或完整原件无法核对，旧选择已清除。'; }
watch(() => supportCanonical([props.itemKind, props.itemId, props.initialReferences]), () => { initialReferenceAllowed = true; }, { flush: 'sync' });
watch(() => [props.itemKind, props.itemId], values => { kind.value = values[0]; item.value = values[1]; }, { flush: 'sync' });
watch(kind, () => { if (!businessLocked.value) item.value = null; page.value = 1; }, { flush: 'sync' });
watch(identity, () => { reset(); refresh(); }, { immediate: true, flush: 'sync' });
onDeactivated(() => { paused = true; reset(); });
onActivated(() => { if (paused) { paused = false; reset(); refresh(); } });
onBeforeUnmount(() => { alive = false; reset(); });
</script>

<style scoped>
p { line-height: 1.7; } .hash { overflow-wrap: anywhere; } .el-select { min-width: 220px; } .el-button { margin: 6px 8px 6px 0; } details { margin: 12px 0; }
</style>
