<template>
  <section aria-label="受审物资预测入口">
    <p v-if="!allowed">当前身份无法使用物资原量预测。</p>
    <template v-else>
      <p>明确一个真实物资、已审核完整原量序列及预测期限。请求量、毛实发和确认实耗分别核对，缺失与冲突不会补零。</p>
      <el-form inline @submit.prevent="refresh">
        <el-form-item label="预测物资类型">
          <el-select :model-value="kind" @update:model-value="kind = $event || null" aria-label="预测物资类型" clearable :disabled="businessLocked" placeholder="明确药品或耗材">
            <el-option value="pharmaceutical" label="药品" /><el-option value="consumable" label="耗材" />
          </el-select>
        </el-form-item>
        <el-form-item v-if="!businessLocked" label="查找预测物资">
          <el-input v-model="search" aria-label="查找预测物资" placeholder="名称，药品也可按条码" :disabled="!kind" />
          <el-button @click="searchItems" :disabled="!kind">查找物资</el-button>
        </el-form-item>
        <el-form-item label="预测物资">
          <el-select :model-value="item" @update:model-value="item = $event || null" aria-label="预测物资" clearable :disabled="businessLocked || !kind" placeholder="明确真实目录品种，不默认首项">
            <el-option v-for="row in options?.items || []" :key="row.item_id" :value="row.item_id" :label="`${row.name || '原目录品种'} · #${row.item_id}`" />
          </el-select>
        </el-form-item>
        <el-form-item label="物资预测期限">
          <el-select v-model="horizon" aria-label="物资预测期限" clearable placeholder="明确7或14个完整业务日">
            <el-option :value="7" label="完整7个业务日" /><el-option :value="14" label="完整14个业务日" />
          </el-select>
        </el-form-item>
        <el-button native-type="submit" :loading="loading">重新核对物资范围</el-button>
        <el-button v-if="chosen" @click="invalidate">清除物资预测序列</el-button>
      </el-form>
      <div v-if="!businessLocked && options && !item && options.total > 20" aria-label="物资目录分页">
        <el-button :disabled="page <= 1 || loading" @click="changePage(-1)">上一页物资</el-button>
        <span>第 {{ page }} 页，共 {{ options.total }} 个当前目录品种</span>
        <el-button :disabled="page * 20 >= options.total || loading" @click="changePage(1)">下一页物资</el-button>
      </div>
      <p v-if="error" role="alert">{{ error }}</p>
      <p v-if="checking" role="status">正在核对完整原量、计数单位、参数与当前治理。</p>
      <p v-if="chosen" class="hash" aria-label="已绑定物资预测序列">
        {{ selectedSku?.name || '原目录品种' }} · #{{ item }}；原序列 {{ chosen.public_source.source_id }}；
        完整 {{ chosen.snapshot.request.days.length }} 个业务日，明确预测 {{ horizon }} 天。
        完整原件 {{ chosen.content_hash }}；公开投影 {{ chosen.projection_hash }}。
      </p>
      <template v-if="scopeReady">
        <details @toggle="sourcesOpen = $event.target.open">
          <summary>登记与核对原计量单位、请求量、实际发出量及确认消耗量</summary>
          <supply-sources-panel v-if="sourcesOpen" :key="`sources-${childKey}`" :item-kind="kind" :item-id="item" :active="active" @source-changed="sourcesChanged" @invalidate="seriesUnavailable" />
        </details>
        <supply-series-panel :key="`series-${childKey}-${seriesKey}`" :item-kind="kind" :item-id="item" :active="active" @select="selectSeries" @series-changed="seriesChanged" @invalidate="seriesUnavailable" />
      </template>
      <p v-else>先选择当前真实目录中的一个物资，再核对受审原量序列。</p>
    </template>
  </section>
</template>

<script setup>
import { computed, defineAsyncComponent, onActivated, onBeforeUnmount, onDeactivated, ref, watch } from 'vue';
import { useStore } from 'vuex';
import { getSupplySourceOptions, supplySourcePositive } from '@/api/ai/supplySources';
import { getSupplySeriesRecord, supplySeriesReferencesValid, verifySupplySeries } from '@/api/ai/supplySeries';
import { supportCanonical, supportId } from '@/api/inpatientSupport';

const SupplySourcesPanel = defineAsyncComponent(() => import('./SupplySourcesPanel.vue'));
const SupplySeriesPanel = defineAsyncComponent(() => import('./SupplySeriesPanel.vue'));
const props = defineProps({ itemKind: { type: String, default: null }, itemId: { type: Number, default: null }, initialReferences: { type: Object, default: null }, active: { type: Boolean, default: true } });
const emit = defineEmits(['scope-change', 'selection', 'availability', 'invalidate']);
const store = useStore();
const roles = computed(() => store.getters['user/permissions'] || []);
const allowed = computed(() => props.active && !!store.state.user.accessToken && roles.value.some(role => ['super_admin', 'admin', 'director', 'pharmacist'].includes(role)));
const kindValid = value => ['pharmaceutical', 'consumable'].includes(value);
const horizonValid = value => Number.isInteger(value) && (value === 7 || value === 14);
const referencesValid = value => value !== null && typeof value === 'object' && !Array.isArray(value) && supportCanonical(Object.keys(value).sort()) === supportCanonical(['horizon_days', 'supply_series_id']) && supportId(value.supply_series_id) && horizonValid(value.horizon_days);
const kind = ref(props.itemKind), item = ref(props.itemId), horizon = ref(null), search = ref(''), page = ref(1);
const options = ref(null), selectedSku = ref(null), chosen = ref(null), loading = ref(false), checking = ref(false), error = ref(''), sourcesOpen = ref(false), childKey = ref(0);
const seriesKey = ref(0);
const businessLocked = computed(() => props.itemKind !== null || props.itemId !== null);
let epoch = 0, catalogSequence = 0, selectionSequence = 0, alive = true, paused = false;
const identity = () => supportCanonical([props.itemKind, props.itemId, props.initialReferences, props.active, kind.value, item.value, store.state.user.accessToken, store.state.user.username, roles.value]);
const ticket = () => ({ epoch, identity: identity() });
const current = token => alive && !paused && allowed.value && token.epoch === epoch && token.identity === identity();
const scopeReady = computed(() => allowed.value && kindValid(kind.value) && supplySourcePositive(item.value) && selectedSku.value?.item_kind === kind.value && selectedSku.value.item_id === item.value && selectedSku.value.status === 0);

function invalidate() {
  selectionSequence++; checking.value = false; chosen.value = null;
  emit('selection', null); emit('availability', false); emit('invalidate');
}
function reset() {
  epoch++; catalogSequence++; options.value = null; selectedSku.value = null; sourcesOpen.value = false;
  loading.value = false; error.value = ''; childKey.value++; invalidate(); emit('scope-change', null);
}
function unavailable(message) {
  reset(); error.value = message || '当前品种、来源或治理无法核对，旧选择已清除。';
}
function optionsValid(value, requested) {
  return value && value.scope === 'hospital_inventory' && value.provider_required === false &&
    supportCanonical(value.item_kinds) === supportCanonical(['pharmaceutical', 'consumable']) &&
    supportCanonical(value.source_kinds) === supportCanonical(['unit_definition', 'daily_quantity']) &&
    supportCanonical(value.targets) === supportCanonical(['recorded_request_quantity', 'gross_fulfilled_issue_quantity', 'confirmed_consumed_quantity']) &&
    value.page === requested.page && value.page_size === 20 && Number.isSafeInteger(value.total) && value.total >= 0 &&
    Array.isArray(value.items) && value.items.length <= 20 && value.total >= value.items.length && (requested.item_id === undefined || value.total <= 1) && new Set(value.items.map(row => row.item_id)).size === value.items.length &&
    value.items.every(row => row.item_kind === requested.item_kind && supplySourcePositive(row.item_id) && (row.name === null || typeof row.name === 'string') && row.status === 0 && row.scope === 'hospital_inventory' && /^[a-f0-9]{64}$/.test(row.identity_hash) && (requested.item_id === undefined || row.item_id === requested.item_id));
}
async function refresh() {
  invalidate(); options.value = null; selectedSku.value = null; emit('scope-change', null); childKey.value++;
  const token = ticket(), sequence = ++catalogSequence;
  if (!current(token)) return;
  loading.value = true; error.value = '';
  try {
    if (businessLocked.value && (!kindValid(props.itemKind) || !supplySourcePositive(props.itemId) || kind.value !== props.itemKind || item.value !== props.itemId)) throw new Error('业务入口须同时绑定真实物资类型与标识。');
    if (kind.value !== null && !kindValid(kind.value) || item.value !== null && !supplySourcePositive(item.value) || item.value !== null && kind.value === null) throw new Error('物资类型或标识无效。');
    if (props.initialReferences !== null && !referencesValid(props.initialReferences)) throw new Error('原引用须完整提供规范序列标识及整数7或14天期限。');
    if (!kind.value && props.initialReferences !== null) {
      const original = (await getSupplySeriesRecord(props.initialReferences.supply_series_id, { auditOnly: false })).data;
      if (!current(token) || sequence !== catalogSequence) return;
      if (original.series_id !== props.initialReferences.supply_series_id || original.audit_only !== false || !original.eligible || !await verifySupplySeries(original, { auditOnly: false })) throw new Error('原序列当前无法用于执行。');
      if (!current(token) || sequence !== catalogSequence) return;
      kind.value = original.item_kind; item.value = original.item_id; return;
    }
    const requested = { page: item.value === null ? page.value : 1, page_size: 20, ...(kind.value ? { item_kind: kind.value } : {}), ...(item.value !== null ? { item_id: item.value } : {}), ...(item.value === null && search.value ? { keyword: search.value } : {}) };
    const value = (await getSupplySourceOptions(requested)).data;
    if (!current(token) || sequence !== catalogSequence) return;
    if (!optionsValid(value, requested)) throw new Error('当前真实物资目录的身份、分页或范围无法核对。');
    options.value = value;
    if (item.value !== null) {
      if (value.items.length !== 1) throw new Error('所选物资已经失效或不在当前目录范围。');
      selectedSku.value = value.items[0]; emit('scope-change', { item_kind: kind.value, item_id: item.value, scope: 'hospital_inventory' });
    }
    if (props.initialReferences !== null && scopeReady.value && horizonValid(horizon.value)) await selectSeries({ supply_series_id: props.initialReferences.supply_series_id });
  } catch (failure) {
    if (current(token) && sequence === catalogSequence) unavailable(failure.message);
  } finally {
    if (current(token) && sequence === catalogSequence) loading.value = false;
  }
}
async function selectSeries(reference) {
  invalidate(); const token = ticket(), sequence = selectionSequence, days = horizon.value;
  if (!current(token) || !scopeReady.value) return;
  if (!horizonValid(days)) { error.value = '请先明确选择7或14个完整业务日，再选择受审序列。'; return; }
  checking.value = true; error.value = '';
  try {
    if (!supplySeriesReferencesValid(reference)) throw new Error('序列选择必须为一个明确原引用。');
    const row = (await getSupplySeriesRecord(reference.supply_series_id, { auditOnly: false })).data;
    if (!current(token) || sequence !== selectionSequence || days !== horizon.value) return;
    if (row.series_id !== reference.supply_series_id || row.audit_only !== false || !row.eligible || !row.public_source || !await verifySupplySeries(row, { itemKind: kind.value, itemId: item.value, auditOnly: false })) throw new Error('所选原量、单位、参数、完整集合或当前治理无法核对。');
    if (!current(token) || sequence !== selectionSequence || days !== horizon.value) return;
    chosen.value = row; emit('selection', { supply_series_id: row.series_id, horizon_days: days }); emit('availability', true);
  } catch (failure) {
    if (current(token) && sequence === selectionSequence) unavailable(failure.message);
  } finally {
    if (current(token) && sequence === selectionSequence) checking.value = false;
  }
}
function searchItems() { page.value = 1; if (item.value !== null) item.value = null; else refresh(); }
function changePage(change) { page.value += change; refresh(); }
function sourcesChanged() { invalidate(); seriesKey.value++; error.value = '原来源或单位已变化，请重新核对完整集合后选择。'; }
function seriesChanged() { invalidate(); error.value = '原序列治理已变化，请重新读取并选择完整原件。'; }
function seriesUnavailable() { const selected = chosen.value !== null || checking.value; invalidate(); if (selected) error.value = '当前序列访问或完整原件已无法核对，旧选择已清除。'; }
watch(() => [props.itemKind, props.itemId], values => { kind.value = values[0]; item.value = values[1]; }, { flush: 'sync' });
watch(kind, () => { if (!businessLocked.value) item.value = null; page.value = 1; }, { flush: 'sync' });
watch(() => supportCanonical(props.initialReferences), () => { horizon.value = referencesValid(props.initialReferences) ? props.initialReferences.horizon_days : null; }, { immediate: true, flush: 'sync' });
watch(horizon, () => { const original = chosen.value; invalidate(); if (original && horizonValid(horizon.value)) selectSeries({ supply_series_id: original.series_id }); }, { flush: 'sync' });
watch(identity, () => { reset(); refresh(); }, { immediate: true, flush: 'sync' });
onDeactivated(() => { paused = true; reset(); });
onActivated(() => { if (paused) { paused = false; reset(); refresh(); } });
onBeforeUnmount(() => { alive = false; reset(); });
</script>

<style scoped>
p { line-height: 1.7; }
.hash { overflow-wrap: anywhere; }
.el-select { min-width: 220px; }
.el-button { margin: 6px 8px 6px 0; }
details { margin: 12px 0; }
</style>
