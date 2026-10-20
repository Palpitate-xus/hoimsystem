<template>
  <section aria-label="每日挂号记录数预测输入">
    <el-form-item label="冻结预测来源"><el-select v-model="seriesId" aria-label="冻结预测来源" clearable filterable placeholder="明确选择已确认的历史来源" :disabled="!allowed || loading"><el-option v-for="item in items" :key="item.series_id" :value="item.series_id" :label="`${item.name} · ${item.date_from}至${item.date_to} · ${item.timezone}`" /></el-select><el-button :disabled="!allowed" :loading="loading" @click="load">刷新来源目录</el-button></el-form-item>
    <el-form-item label="外推跨度"><el-select v-model="horizon" aria-label="外推跨度"><el-option label="7天" :value="7" /><el-option label="14天" :value="14" /></el-select></el-form-item>
    <p v-if="truncated">目录仅显示前100个有权限的活动来源，并非完整清单。</p>
    <p v-if="selected">{{ selected.scope === 'hospital' ? '全院' : `科室 #${selected.department_id}` }} · 原历史 {{ selected.date_from }} 至 {{ selected.date_to }} · {{ selected.day_count }} 日 · 原钟点时区解释 {{ selected.timezone }}。列表尚未保证原资料仍一致。</p>
    <p v-if="checking">正在重新核对所选冻结来源与当前原资料。</p><p v-if="error" role="alert">{{ error }}</p>
    <template v-if="source"><p>当前核对通过。目标为每日所有状态挂号原记录数（条/日），不是实际到诊或独立患者；覆盖和原无时区钟点解释均为超级管理员声明，未独立核实外部完整性。</p><p>自历史末日次日起算：{{ nextDate(source.date_to) }}，外推 {{ horizon }} 天。旧历史窗口可能只是在过去日期外推；这不是从今天起算。</p><p class="hash">来源 {{ source.source_id }}<br />冻结摘要 {{ source.content_hash }}<br />原登记摘要 {{ source.registration_digest }}</p><p>无时间挂号记录 {{ source.unassigned_time_records }} 条，无法分日，已排除。来源、历史日期、目标、时区和原数值均不能在补充JSON中替换。</p></template>
  </section>
</template>
<script setup>
import { computed, onBeforeUnmount, onDeactivated, onMounted, ref, watch } from "vue";
import { useStore } from "vuex";
import { getAIForecastSeries, getAIOperationalContext } from "@/api/ai";
const props = defineProps({ initialSeriesId: { type: String, default: "" } });
const emit = defineEmits(["selection", "availability"]), store = useStore();
const allowed = computed(() => !!store.state.user.accessToken && store.getters["user/permissions"].some(role => ["super_admin", "admin", "director"].includes(role)));
const seriesId = ref(""), horizon = ref(7), items = ref([]), truncated = ref(false), loading = ref(false), checking = ref(false), source = ref(null), error = ref("");
const selected = computed(() => items.value.find(item => item.series_id === seriesId.value));
let listEpoch = 0, checkEpoch = 0;
function nextDate(value) { const time = new Date(`${value}T00:00:00Z`); time.setUTCDate(time.getUTCDate() + 1); return time.toISOString().slice(0, 10); }
function invalidate() { checkEpoch++; source.value = null; checking.value = false; error.value = ""; emit("availability", false); }
function clear() { listEpoch++; invalidate(); seriesId.value = ""; items.value = []; loading.value = false; emit("selection", null); }
watch([() => JSON.stringify(store.getters["user/permissions"]), () => store.state.user.accessToken], () => { clear(); if (allowed.value) load(); });
onDeactivated(clear); onBeforeUnmount(clear);
async function load() {
  if (!allowed.value) return; const epoch = ++listEpoch; loading.value = true; invalidate(); seriesId.value = ""; emit("selection", null);
  try { const response = await getAIForecastSeries(); if (epoch !== listEpoch || !allowed.value) return; items.value = response.data?.items ?? []; truncated.value = response.data?.truncated === true; if (props.initialSeriesId && items.value.some(item => item.series_id === props.initialSeriesId)) seriesId.value = props.initialSeriesId; }
  catch { if (epoch === listEpoch && allowed.value) { items.value = []; error.value = "预测来源目录加载失败"; } }
  finally { if (epoch === listEpoch) loading.value = false; }
}
watch([seriesId, horizon], async () => {
  invalidate(); const epoch = checkEpoch, item = selected.value;
  const binding = item ? { forecast_series_id: item.series_id, horizon_days: horizon.value } : null;
  emit("selection", binding); if (!binding || !allowed.value) return; checking.value = true;
  try {
    const response = await getAIOperationalContext({ feature_key: "visit_forecast", input: binding });
    if (epoch !== checkEpoch || !allowed.value) return;
    const context = response.data?.context, candidate = context?.forecast_source;
    if (!candidate || context.series_revision !== item.revision || context.horizon_days !== horizon.value || !["series_id", "source_id", "content_hash", "target", "grain", "scope", "department_id", "date_from", "date_to", "timezone", "time_basis"].every(key => candidate[key] === item[key]) || candidate.coverage_status !== "super_admin_attested" || !Array.isArray(candidate.observations) || candidate.observations.length !== item.day_count) throw new Error("binding");
    source.value = candidate; emit("availability", true);
  } catch { if (epoch === checkEpoch && allowed.value) { source.value = null; error.value = "所选来源未通过当前原资料核对；请刷新或由超级管理员建立新来源"; emit("availability", false); } }
  finally { if (epoch === checkEpoch) checking.value = false; }
});
onMounted(load);
</script>
<style scoped>p { line-height: 1.7; }.hash { overflow-wrap: anywhere; }</style>
