<template>
  <section aria-label="成人AKI确定性标准复核">
    <p>依据KDIGO 2012的成人AKI已观测标准，独立软件实现，未获KDIGO认证或背书。这里核对所选评估资料，不预测未来风险，不替代最终诊断或自动治疗。</p>
    <p v-if="!scoped" role="alert">AKI来源与原患者、住院、窗口或冻结原资料不一致，拒绝展示其他范围数值。</p>
    <template v-else>
      <p>评估 {{ source.assessment_id }} · 原住院 {{ scope.admission_id }} · 原窗 {{ source.window_id }}<br />评估时刻 {{ source.evaluation_at }}；冻结可用截止 {{ source.as_of }}。检验采样时刻与评估时刻分别保留，不表示同时发生。</p>
      <p>声明评估时年龄 {{ source.age_at_evaluation_years }}；规则 {{ source.rule_id }} · {{ source.rule_profile_id }}。人工声明与来源治理不构成独立临床验证。</p>
      <p class="hash">规则摘要 {{ source.recipe_digest }}<br />原评估摘要 {{ source.content_hash }}</p>
      <el-button link @click="$emit('inspect', source.source_id)">核对AKI评估原依据</el-button><el-button link @click="$emit('inspect', source.rule_profile_source_id)">核对AKI审核规则依据</el-button>
      <el-table :data="creatinineRows" aria-label="AKI所选肌酐原值"><el-table-column prop="label" label="选定用途" /><el-table-column label="原值"><template #default="{ row }">{{ row.item.value ?? '非数值或未提供' }} {{ row.item.unit }}</template></el-table-column><el-table-column prop="originalAdmission" label="实际原住院" min-width="250" /><el-table-column prop="item.collected_at_utc" label="原采样UTC" min-width="220" /><el-table-column prop="item.available_at" label="受控登记可用时刻" min-width="220" /><el-table-column label="原依据"><template #default="{ row }"><el-button link @click="$emit('inspect', row.item.source_id)">核对原肌酐来源</el-button></template></el-table-column></el-table>
      <p>基线策略 {{ baselineLabels[source.baseline_mode] || source.baseline_mode }}；血清/血浆用途{{ source.creatinine_review.serum_creatinine_confirmed ? '已有临床声明，仍须复核' : '未确认' }}。只比较相同原单位和已审核项目身份；不自动选择最低、最近或估计基线，不自动换算单位。</p>
      <p v-if="source.weight" aria-label="AKI原体重">原体重 {{ source.weight.value ?? `未测（${source.weight.absent_reason}）` }} {{ source.weight.unit }} · {{ source.weight.observed_at }}；对整段适用{{ source.weight_applicability_confirmed ? '已人工声明' : '未确认' }}。0保留为原值，不能作为计算分母。</p><p v-else>未选择原体重；不补默认、理想或最近体重。</p>
      <el-table :data="source.urine_intervals" aria-label="AKI所选原尿量区间"><el-table-column prop="start_at" label="原区间开始" min-width="220" /><el-table-column prop="end_at" label="原区间结束" min-width="220" /><el-table-column label="原尿量"><template #default="{ row }">{{ row.volume_ml ?? `未测（${row.absent_reason}）` }} mL</template></el-table-column><el-table-column prop="collection_completeness" label="原收集完整性" /><el-table-column label="原患者总量声明"><template #default="{ row }">{{ row.patient_total === true ? '是' : row.patient_total === false ? '否' : '未知' }}</template></el-table-column><el-table-column label="原依据"><template #default="{ row }"><el-button link @click="$emit('inspect', row.source_id)">核对原尿量区间</el-button></template></el-table-column></el-table>
      <p>尿量策略为完整原区间的平均量；不裁剪、不分摊、不虚构逐小时记录，不证明每小时持续少尿。原体重、重叠、遗漏、间隙或收集完整性缺口会保留。</p><p v-for="issue in source.urine_coverage_issues" :key="issue">原覆盖缺口：{{ issueLabels[issue] || issue }}</p>
      <p>RRT原临床声明 {{ rrtLabels[source.rrt.status] || source.rrt.status }}；原启动 {{ source.rrt.started_at ?? '未提供' }}。不从医嘱推断启动，不将维持性RRT当作新发AKI。</p>
      <p v-if="!analysis">尚未提供确定性计算报告；原资料不等于已检出标准或已排除AKI。</p>
      <p v-else-if="!bound" role="alert">AKI标准、最低分期、运行版本或原来源绑定不一致，计算结果已拒绝展示。</p>
      <template v-else>
        <p>计算状态 {{ calculationLabels[analysis.calculation_status] }}；声明范围 {{ scopeLabels[analysis.scope_status] }}。</p>
        <p v-if="analysis.detection === 'met'" aria-label="AKI最低达到分期">所选资料支持至少达到AKI {{ analysis.minimum_stage }}期。{{ analysis.stage_is_lower_bound ? '这是已支持标准的最低分期，其他资料仍可能不完整。' : '已达到本分期规则上限，不代表整个AKI病程资料完整。' }}</p>
        <p v-else-if="analysis.detection === 'not_met_in_selected_data'" aria-label="AKI所选标准未满足">所选资料未满足已评估标准；不能据此排除AKI，也不代表当前病程无AKI。</p>
        <p v-else-if="analysis.detection === 'outside_scope'">超出本软件声明的成人标准范围；不输出分期，不将未知视为正常。</p>
        <p v-else aria-label="AKI资料不足">资料不足，无法给出完整标准判断；不输出0期或“无AKI”。</p>
        <el-table :data="analysis.criteria" aria-label="AKI八项标准与原依据"><el-table-column label="标准"><template #default="{ row }">{{ criterionLabels[row.key] }}</template></el-table-column><el-table-column label="状态"><template #default="{ row }">{{ statusLabels[row.status] }}</template></el-table-column><el-table-column label="支持分期"><template #default="{ row }">{{ row.stage ?? '未给出' }}</template></el-table-column><el-table-column prop="reason_code" label="原因编码" min-width="180" /><el-table-column label="实际原量与区间" min-width="310"><template #default="{ row }"><p v-for="entry in evidenceRows(row.evidence)" :key="entry[0]">{{ entry[0] }}：{{ entry[1] }}</p><el-button v-for="id in row.source_ids" :key="id" link @click="$emit('inspect', id)">核对标准原依据</el-button></template></el-table-column></el-table>
        <p v-for="(item, index) in analysis.missing_data" :key="`missing:${index}`">缺项：{{ item }}</p><p v-for="(item, index) in analysis.warnings" :key="`warning:${index}`">复核：{{ item }}</p>
        <p aria-label="AKI运行与规则版本" class="hash">实际引擎 {{ analysis.local_runtime.engine }} · {{ analysis.local_runtime.model_version }}<br />运行摘要 {{ analysis.local_runtime.runtime_digest }}<br />完整Prompt摘要 {{ analysis.instructions_digest }}<br />Prompt仅用于溯源，不改变固定标准。未提供本项目独立临床验证。</p><p>{{ analysis.attribution }}</p><p v-for="reference in analysis.rule_references" :key="reference" class="hash">规则原始依据：{{ reference }}</p>
      </template>
    </template>
  </section>
</template>
<script setup>
import { computed } from "vue";
import { akiAssessmentMatches, akiCanonical } from "@/api/aiAki";
import { observationTime } from "@/api/inpatientObservations";
const props = defineProps({ source: { type: Object, default: null }, analysis: { type: Object, default: null }, scope: { type: Object, default: null }, expectedPatientId: { type: Number, required: true }, expectedAdmissionId: { type: String, required: true } });
defineEmits(["inspect"]);
const keys = ["creatinine_48h", "creatinine_ratio_7d", "creatinine_absolute_stage3", "urine_6h", "urine_12h", "urine_24h", "anuria_12h", "acute_rrt"];
const criterionLabels = { creatinine_48h: "SCr原48小时变化", creatinine_ratio_7d: "SCr明确7日基线倍数", creatinine_absolute_stage3: "SCr绝对值3期标准", urine_6h: "原区间平均尿量至少6小时", urine_12h: "原区间平均尿量至少12小时", urine_24h: "原区间平均尿量至少24小时", anuria_12h: "原完整零尿量至少12小时", acute_rrt: "临床确认因AKI新启动急性RRT" };
const baselineLabels = { unknown: "未知", observed_within_7d: "明确7日内原测量", presumed_within_7d: "明确较早原来源及临床确认7日内急性升高" }, rrtLabels = { unknown: "未知", not_initiated: "已临床声明未启动", acute_initiated_for_aki: "已临床声明因AKI新启动", maintenance: "维持性RRT，超出新发AKI判定范围" };
const issueLabels = { unselected_active_interval: "选段内存在未选活动原区间", overlap: "原区间重叠", gap: "原区间间隙", partial_collection: "收集不完整或完整性未知", unknown_volume: "原尿量未知", not_patient_total: "未明确为患者总量" };
const statusLabels = { met: "满足已评估标准", not_met_in_selected_data: "所选资料未满足", unknown: "未知", outside_scope: "超出范围" }, calculationLabels = { computed: "确定性计算", insufficient_data: "资料不足", outside_scope: "超出范围" }, scopeLabels = { within_declared_scope: "在人工声明范围内，未独立核实", outside_scope: "超出范围" };
const evidenceLabels = { index_value: "原index值", reference_value: "原比较值", unit: "原单位", index_at: "index原采样时刻", reference_at: "比较值原采样时刻", absolute_change: "实际精确差值", threshold: "本条固定阈值", multiplier: "本条固定倍数", elapsed_microseconds: "实际时长（微秒）", interval_start_at: "原选段开始", interval_end_at: "原选段结束", total_volume_ml: "完整原区间总量mL", weight_kg: "原体重kg", rate_numerator: "精确平均率分子", rate_denominator: "精确平均率分母", interval_source_ids: "原尿量来源链", coverage_issues: "选段复核覆盖缺口" };
const evidenceRows = evidence => Object.entries(evidence || {}).filter(([, value]) => value !== null && value !== undefined && (!Array.isArray(value) || value.length)).map(([key, value]) => [evidenceLabels[key] || key, Array.isArray(value) ? value.join("；") : value]);
const creatinineRows = computed(() => [["明确index", "index_creatinine"], ["明确48小时比较", "comparison_48h"], ["明确基线", "baseline_creatinine"]].filter(([, role]) => props.source?.[role]).map(([label, role]) => ({ label, item: props.source[role], originalAdmission: props.scope?.snapshot?.[role]?.admission_id })));
const scoped = computed(() => !!props.source && !!props.scope && akiAssessmentMatches({ ...props.scope, specialist_source: props.source }, props.expectedPatientId, props.expectedAdmissionId, props.source.window_id, true));
const decimalScale = value => typeof value === "string" && /^-?(?:0|[1-9]\d*)(?:\.\d{1,8})?$/.test(value) ? BigInt(value.replace(".", "").replace(/^-/, "")) * 10n ** BigInt(8 - (value.split(".")[1] || "").length) * (value.startsWith("-") ? -1n : 1n) : null;
function evidenceMatches(row, source) {
  const evidence = row.evidence;
  if (!Array.isArray(evidence.coverage_issues || []) || (evidence.coverage_issues || []).some(issue => !(issue in issueLabels))) return false;
  if (row.key.startsWith("creatinine")) {
    const index = source.index_creatinine, reference = row.key === "creatinine_48h" ? source.comparison_48h : row.key === "creatinine_ratio_7d" ? source.baseline_creatinine : null;
    for (const [key, expected] of [["index_value", index?.value], ["index_at", index?.collected_at_utc], ["unit", index?.unit], ["reference_value", reference?.value], ["reference_at", reference?.collected_at_utc]]) if (evidence[key] != null && evidence[key] !== expected) return false;
    if (evidence.absolute_change != null && (decimalScale(evidence.absolute_change) === null || decimalScale(index?.value) === null || decimalScale(reference?.value) === null || decimalScale(evidence.absolute_change) !== decimalScale(index.value) - decimalScale(reference.value))) return false;
    if (evidence.elapsed_microseconds != null) { try { if (!Number.isSafeInteger(evidence.elapsed_microseconds) || !index || !reference || BigInt(evidence.elapsed_microseconds) !== observationTime(index.collected_at_utc).microseconds - observationTime(reference.collected_at_utc).microseconds) return false; } catch { return false; } }
  }
  if (row.key === "acute_rrt" && evidence.index_at != null && evidence.index_at !== source.rrt.started_at) return false;
  if (row.key.startsWith("urine") || row.key === "anuria_12h") {
    const ids = evidence.interval_source_ids || [];
    if (!Array.isArray(ids) || new Set(ids).size !== ids.length) return false;
    const chain = ids.map(id => source.urine_intervals.find(item => item.source_id === id));
    if (chain.some(item => !item)) return false;
    if (chain.length) {
      if (evidence.interval_start_at !== chain[0].start_at || evidence.interval_end_at !== chain.at(-1).end_at || chain.some((item, index) => index && item.start_at !== chain[index - 1].end_at) || chain.some(item => item.volume_ml === null || item.collection_completeness !== "complete" || item.patient_total !== true)) return false;
      try {
        const duration = observationTime(chain.at(-1).end_at).microseconds - observationTime(chain[0].start_at).microseconds;
        if (!Number.isSafeInteger(evidence.elapsed_microseconds) || BigInt(evidence.elapsed_microseconds) !== duration || chain.some(item => decimalScale(item.volume_ml) === null)) return false;
        const total = chain.reduce((sum, item) => sum + decimalScale(item.volume_ml), 0n);
        if (decimalScale(evidence.total_volume_ml) !== total || (evidence.weight_kg != null && evidence.weight_kg !== source.weight?.value)) return false;
        if (evidence.rate_numerator != null || evidence.rate_denominator != null) {
          const weight = decimalScale(source.weight?.value);
          if (!/^\d+$/.test(evidence.rate_numerator || "") || !/^[1-9]\d*$/.test(evidence.rate_denominator || "") || weight === null || weight <= 0n || BigInt(evidence.rate_numerator) * weight * duration !== BigInt(evidence.rate_denominator) * total * 3600000000n) return false;
        }
      } catch { return false; }
    } else if (["interval_start_at", "interval_end_at", "total_volume_ml", "weight_kg", "rate_numerator", "rate_denominator"].some(key => evidence[key] != null)) return false;
  }
  return true;
}
const bound = computed(() => {
  const value = props.analysis, source = props.source;
  if (!scoped.value || !value || value.schema_version !== "1" || value.rule_id !== "kdigo_aki_2012" || source.rule_id !== value.rule_id || akiCanonical(value.source_binding) !== akiCanonical(source) || value.aki_excluded !== false || value.clinical_validation !== "not_provided" || value.independent_implementation !== true || !Array.isArray(value.criteria) || value.criteria.length !== 8 || !Array.isArray(value.missing_data) || !Array.isArray(value.warnings) || !Array.isArray(value.rule_references) || value.rule_references.length !== 4) return false;
  const runtime = value.local_runtime;
  if (runtime?.engine !== "stdlib-kdigo-aki-rules" || runtime.rule_id !== source.rule_id || runtime.recipe_digest !== source.recipe_digest || !/^[a-f0-9]{64}$/.test(runtime.runtime_digest || "") || runtime.model_version !== `aki:${runtime.runtime_digest}` || runtime.prompt_handling !== "provenance_only" || runtime.clinical_validation !== "not_provided" || !/^[a-f0-9]{64}$/.test(value.instructions_digest || "")) return false;
  const allowed = new Set([source.source_id, source.window_source_id, source.rule_profile_source_id, source.index_creatinine?.source_id, source.comparison_48h?.source_id, source.baseline_creatinine?.source_id, source.weight?.source_id, ...(source.urine_intervals || []).map(row => row.source_id)].filter(Boolean));
  if (value.criteria.some((row, index) => row.key !== keys[index] || !(row.status in statusLabels) || !row.evidence || typeof row.evidence !== "object" || Array.isArray(row.evidence) || !Array.isArray(row.source_ids) || row.source_ids.some(id => !allowed.has(id)) || !evidenceMatches(row, source) || (row.status === "met" ? !Number.isInteger(row.stage) || row.stage < 1 || row.stage > 3 : row.stage !== null))) return false;
  if ((source.age_at_evaluation_years < 18 || source.rrt.status === "maintenance") !== (value.scope_status === "outside_scope")) return false;
  const met = value.criteria.filter(row => row.status === "met"), minimum = met.length ? Math.max(...met.map(row => row.stage)) : null;
  if (value.minimum_stage !== minimum || typeof value.stage_is_lower_bound !== "boolean") return false;
  if (value.scope_status === "outside_scope") return value.calculation_status === "outside_scope" && value.detection === "outside_scope" && minimum === null && value.stage_is_lower_bound === false && value.criteria.every(row => row.status === "outside_scope");
  if (value.scope_status !== "within_declared_scope" || !["computed", "insufficient_data"].includes(value.calculation_status)) return false;
  if (minimum !== null) return value.detection === "met" && value.stage_is_lower_bound === (minimum < 3) && value.calculation_status === (value.criteria.some(row => row.status === "unknown") ? "insufficient_data" : "computed");
  return value.stage_is_lower_bound === false && (value.criteria.some(row => row.status === "unknown") ? value.detection === "insufficient_data" && value.calculation_status === "insufficient_data" : value.detection === "not_met_in_selected_data" && value.calculation_status === "computed");
});
</script>
<style scoped>p { line-height: 1.7; }.hash { overflow-wrap: anywhere; }</style>
