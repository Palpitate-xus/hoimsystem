<template>
  <section aria-label="NEWS2确定性计算复核" class="news2-findings">
    <p>依据 Royal College of Physicians，National Early Warning Score (NEWS) 2，2017；独立软件实现，未获RCP认证或背书。这里只展示规则计算，不提供患病概率、脓毒症确诊或自动治疗。</p>
    <p v-if="!scoped" role="alert">NEWS2来源与原患者、住院、窗口或计算绑定不一致，不展示其他范围数值。</p>
    <template v-else>
      <p>评估 {{ source.assessment_id }} · 原窗 {{ source.window_id }} · 原点 {{ source.point_id }}<br />原观察 {{ source.observed_at }}；系统登记 {{ source.recorded_at }}；冻结可用截止 {{ source.as_of }}。</p>
      <p>声明原年龄 {{ source.age_at_observation_years }}；妊娠状态 {{ pregnancyLabels[source.pregnancy_status] || source.pregnancy_status }}；SpO₂ Scale {{ source.spo2_scale }}。声明不构成独立适用性证明。</p>
      <p class="hash">规则 {{ source.rule_id }} · 审核版本 {{ source.rule_profile_id }}<br />规则摘要 {{ source.recipe_digest }}<br />原评估摘要 {{ source.content_hash }}</p>
      <el-button link @click="$emit('inspect', source.source_id)">核对NEWS2评估原依据</el-button><el-button link @click="$emit('inspect', source.point_source_id)">核对NEWS2原点测依据</el-button><el-button link @click="$emit('inspect', source.rule_profile_source_id)">核对NEWS2审核规则依据</el-button>
      <template v-if="!analysis"><p>尚未提供确定性计算报告；原测量不等于已评分。</p><el-table :data="sourceRows" aria-label="NEWS2原点测量只读资料"><el-table-column prop="label" label="原指标" /><el-table-column prop="display" label="原值或缺失原因" /><el-table-column prop="unit" label="原单位" /></el-table></template>
      <p v-else-if="!bound" role="alert">NEWS2分项、总分、规则版本或来源绑定不一致，计算结果已拒绝展示。</p>
      <template v-else>
        <p>计算状态：{{ calculationLabels[analysis.calculation_status] }}；适用性：{{ scopeLabels[analysis.scope_status] }}。</p>
        <p v-if="analysis.calculation_status === 'computed'" aria-label="NEWS2完整总分">完整总分 {{ analysis.total_score }}；规则等级 {{ classificationLabels[analysis.classification] }}。</p>
        <template v-else-if="analysis.scope_status === 'within_declared_scope' && analysis.score_is_lower_bound"><p aria-label="NEWS2已知分项下界">已知分项合计至少 {{ analysis.observed_subtotal }}（{{ analysis.scored_component_count }}/7项）；完整总分未知。{{ analysis.minimum_classification ? `已知分项至少达到规则等级：${classificationLabels[analysis.minimum_classification]}。` : '已知分项为0不表示低风险或完整总分为0。' }}</p><p>这是本软件保留已知分项的下界，不是完整NEWS2总分；缺项不掩盖已记录的高分或单项红项。</p></template>
        <p v-else>人群适用性未知或超出范围，未给出分项分数、合计或规则等级；不把未知视为正常。</p>
        <p>单项红项：{{ analysis.red_flag_components.length ? analysis.red_flag_components.map(label).join('、') : '本报告未列红项；不代表无风险' }}。</p>
        <el-table :data="analysis.components" aria-label="NEWS2七项原值与分值"><el-table-column label="分项"><template #default="{ row }">{{ label(row.key) }}</template></el-table-column><el-table-column label="原值"><template #default="{ row }">{{ row.raw_value ?? '未提供' }}</template></el-table-column><el-table-column label="单位"><template #default="{ row }">{{ row.unit ?? '不适用' }}</template></el-table-column><el-table-column label="分值"><template #default="{ row }">{{ row.score ?? '未计算' }}</template></el-table-column><el-table-column label="状态与原因" min-width="200"><template #default="{ row }">{{ componentLabels[row.status] }} · {{ row.reason }}</template></el-table-column><el-table-column prop="observed_at" label="原观察时刻" min-width="220" /></el-table>
        <p v-for="(item, index) in analysis.missing_data" :key="`missing:${index}`">缺项：{{ item }}</p><p v-for="(item, index) in analysis.warnings" :key="`warning:${index}`">复核：{{ item }}</p>
        <p aria-label="NEWS2运行与规则版本" class="hash">运行引擎 {{ analysis.local_runtime.engine }} · {{ analysis.local_runtime.model_version }}<br />运行摘要 {{ analysis.local_runtime.runtime_digest }}<br />完整Prompt摘要 {{ analysis.instructions_digest }}<br />Prompt仅用于溯源，不改变固定规则数值。未提供本项目独立临床验证。</p>
        <p>{{ analysis.attribution }}</p><p v-for="reference in analysis.rule_references" :key="reference" class="hash">规则原始依据：{{ reference }}</p>
      </template>
    </template>
  </section>
</template>
<script setup>
import { computed } from "vue";
import { news2Canonical } from "@/api/aiNews2";
const props = defineProps({ source: { type: Object, default: null }, analysis: { type: Object, default: null }, scope: { type: Object, default: null }, expectedPatientId: { type: Number, required: true }, expectedAdmissionId: { type: String, required: true } });
defineEmits(["inspect"]);
const keys = ["respiratory_rate", "spo2", "systolic_bp", "pulse_rate", "temperature", "supplemental_oxygen", "consciousness"];
const labels = { respiratory_rate: "呼吸率", spo2: "SpO₂", systolic_bp: "收缩压", pulse_rate: "脉搏", temperature: "体温", supplemental_oxygen: "补充氧", consciousness: "意识/新发混乱" };
const label = key => labels[key] || key;
const sourceRows = computed(() => keys.map(key => {
  const measurement = props.source?.measurements?.[key];
  const display = key === "supplemental_oxygen" ? props.source?.supplemental_oxygen : key === "consciousness" ? (props.source?.consciousness ? `${props.source.consciousness.system}:${props.source.consciousness.code}` : "未记录") : measurement?.value ?? (measurement ? `未测（${measurement.absent_reason}）` : "未记录");
  return { label: label(key), display, unit: measurement?.unit || "不适用" };
}));
const calculationLabels = { computed: "完整计算", insufficient_data: "资料不足", outside_scope: "超出声明适用范围" }, scopeLabels = { within_declared_scope: "在声明范围内，未独立核实", unknown: "未知", outside_scope: "超出范围" }, pregnancyLabels = { not_pregnant: "已声明未妊娠", pregnant: "妊娠", not_applicable: "明确不适用妊娠条件", unknown: "未知" };
const classificationLabels = { zero: "0分组", low: "低分组（非无风险）", single_red: "单项3分红项", medium: "中等级", high: "高等级" }, componentLabels = { scored: "已评分", missing: "缺项", conflict: "原值冲突", outside_precision: "原精度无法直接评分", requires_review: "须核实", outside_scope: "超出范围" };
const scoped = computed(() => props.source && props.scope?.patient_id === props.expectedPatientId && props.scope.admission_id === props.expectedAdmissionId && props.scope.window_id === props.source.window_id && (!props.scope.assessment_id || props.scope.assessment_id === props.source.assessment_id) && (!props.scope.content_hash || props.scope.content_hash === props.source.content_hash) && ["point_id", "window_content_hash", "rule_profile_id", "rule_profile_content_hash", "recipe_digest"].every(key => !(key in props.scope) || props.scope[key] === props.source[key]));
const band = (subtotal, red, partial) => subtotal >= 7 ? "high" : subtotal >= 5 ? "medium" : red.length ? "single_red" : subtotal === 0 ? (partial ? null : "zero") : "low";
const bound = computed(() => {
  const value = props.analysis, source = props.source;
  if (!scoped.value || !value || value.schema_version !== "1" || value.rule_id !== "news2_2017" || value.rule_id !== source.rule_id || news2Canonical(value.source_binding) !== news2Canonical(source) || !["computed", "insufficient_data", "outside_scope"].includes(value.calculation_status) || !["within_declared_scope", "unknown", "outside_scope"].includes(value.scope_status) || !Array.isArray(value.components) || value.components.length !== 7 || value.components.some((row, index) => row.key !== keys[index] || row.source_id !== source.point_source_id || row.observed_at !== source.observed_at || !(row.status in componentLabels) || (row.score !== null && (!Number.isInteger(row.score) || row.score < 0 || row.score > 3)) || (row.status === "scored") !== (row.score !== null)) || !Array.isArray(value.red_flag_components) || !Array.isArray(value.missing_data) || !Array.isArray(value.warnings) || value.clinical_validation !== "not_provided" || value.independent_implementation !== true) return false;
  const sourceUnits = { respiratory_rate: "/min", spo2: "%", systolic_bp: "mm[Hg]", pulse_rate: "/min", temperature: "Cel" };
  if (value.components.some(row => {
    const expectedRaw = row.key === "supplemental_oxygen" ? source.supplemental_oxygen : row.key === "consciousness" ? (source.consciousness ? `${source.consciousness.system}:${source.consciousness.code}` : null) : source.measurements?.[row.key]?.value ?? null;
    return row.raw_value !== expectedRaw || row.unit !== (sourceUnits[row.key] || null);
  })) return false;
  const runtime = value.local_runtime;
  if (runtime?.engine !== "stdlib-news2-rules" || runtime.rule_id !== source.rule_id || runtime.recipe_digest !== source.recipe_digest || !/^[a-f0-9]{64}$/.test(runtime.runtime_digest || "") || runtime.model_version !== `news2:${runtime.runtime_digest}` || runtime.prompt_handling !== "provenance_only" || runtime.clinical_validation !== "not_provided" || !/^[a-f0-9]{64}$/.test(value.instructions_digest || "")) return false;
  const scored = value.components.filter(row => row.score !== null), red = value.components.filter(row => row.score === 3).map(row => row.key), subtotal = scored.reduce((sum, row) => sum + row.score, 0);
  if (news2Canonical(red) !== news2Canonical(value.red_flag_components) || value.scored_component_count !== scored.length) return false;
  if (value.scope_status !== "within_declared_scope") return scored.length === 0 && value.total_score === null && value.observed_subtotal === null && value.classification === null && value.minimum_classification === null && value.score_is_lower_bound === false && (value.scope_status === "unknown" ? value.calculation_status === "insufficient_data" : value.calculation_status === "outside_scope");
  if (value.calculation_status === "computed") return scored.length === 7 && value.total_score === subtotal && value.observed_subtotal === subtotal && value.classification === band(subtotal, red, false) && value.minimum_classification === value.classification && value.score_is_lower_bound === false;
  return value.calculation_status === "insufficient_data" && value.total_score === null && value.classification === null && value.observed_subtotal === subtotal && value.minimum_classification === band(subtotal, red, true) && value.score_is_lower_bound === true;
});
</script>
<style scoped>p { line-height: 1.7; }.hash { overflow-wrap: anywhere; }</style>
