<template>
  <section aria-label="qSOFA三项资料确定性复核">

    <p v-if="!scoped" role="alert">qSOFA原来源与患者、住院、窗口或原分项绑定不一致，不展示其他范围数值。</p>
    <template v-else>
      <p>评估 {{ source.assessment_id }} · 原窗 {{ source.window_id }} · 原点 {{ source.point_id }}。</p><p>原点观察 {{ source.observed_at }}；原点登记 {{ source.recorded_at }}；原窗可用截止 {{ source.as_of }}。</p><p aria-label="qSOFA当前回顾声明">当前回顾临床声明登记 {{ source.clinical_statements_recorded_at }}，适用于原点 {{ source.clinical_scope_applies_to }}。</p>
      <p>医生确认年龄 {{ source.age_at_observation_years ?? '未知' }}；场景 {{ careLabels[source.care_setting] }}；感染 {{ infectionLabels[source.infection_status] }}；GCS可判读 {{ interpretLabels[source.gcs_interpretability] }}。</p><p class="hash">固定规则 {{ source.rule_id }} · {{ source.recipe_digest }}；评估原摘要 {{ source.content_hash }}。</p>
      <el-button link @click="$emit('inspect',source.source_id)">核对qSOFA原评估依据</el-button><el-button link @click="$emit('inspect',source.point_source_id)">核对qSOFA原点测依据</el-button><el-button link @click="$emit('inspect',source.rule_profile_source_id)">核对qSOFA审核规则依据</el-button>
      <el-table :data="rawRows" aria-label="qSOFA所选原量"><el-table-column prop="label" label="原指标" /><el-table-column prop="display" label="原值或未测原因" /><el-table-column prop="unit" label="原单位" /><el-table-column prop="clock" label="实际观察UTC" min-width="230" /></el-table>
      <template v-if="source.gcs"><p>原GCS登记 {{ source.gcs.recorded_at }}；原点关联 {{ source.gcs.anchor_point_id }}；同次检查人工明确确认，两个真实观察时刻分别保留。{{ source.gcs.conflict ? '同一原点关联的GCS存在冲突，意识项未知。' : '' }}</p><el-button link @click="$emit('inspect',source.gcs.source_id)">核对qSOFA原GCS依据</el-button></template>
      <p v-if="!analysis">尚无计算报告，请先完成评分。</p><p v-else-if="!bound" role="alert">qSOFA分项、原量、总分或运行来源绑定不一致，已拒绝展示计算结果。</p>
      <template v-else>
        <p>适用性 {{ scopeLabels[analysis.scope_status] }}；计算状态 {{ calcLabels[analysis.calculation_status] }}。</p><p v-if="analysis.total_score !== null" aria-label="qSOFA完整总分">完整总分 {{ analysis.total_score }}/3，三项均已核对。</p><p v-else-if="analysis.observed_subtotal !== null" aria-label="qSOFA已知分项下界">已知分项合计至少 {{ analysis.observed_subtotal }}（{{ analysis.scored_count }}/3项）；完整总分未知，缺项不补0。</p><p v-else>范围未知、超出范围或尚无可评分分项，合计未知，不填0。</p><p aria-label="qSOFA提示阈值">{{ thresholdLabels[analysis.threshold_status] }}</p>
        <el-table :data="analysis.criteria" aria-label="qSOFA三项原量与分值"><el-table-column label="分项"><template #default="{row}">{{ labels[row.key] }}</template></el-table-column><el-table-column prop="raw_value" label="核对原值" /><el-table-column label="原单位"><template #default="{row}">{{ row.unit ?? '未取得' }}</template></el-table-column><el-table-column label="分值"><template #default="{row}">{{ row.score ?? '未知，不补0' }}</template></el-table-column><el-table-column label="状态与原因"><template #default="{row}">{{ statuses[row.status] }} · {{ row.reason }}</template></el-table-column><el-table-column prop="observed_at" label="实际原时刻" min-width="230" /></el-table>
        <p v-for="item in noticeList(analysis.missing_data)" :key="item">缺项：{{ item }}</p><p v-for="item in noticeList(analysis.warnings)" :key="item">复核：{{ item }}</p><p class="hash">实际运行 {{ analysis.local_runtime.engine }} · {{ analysis.local_runtime.model_version }}；完整Prompt摘要 {{ analysis.instructions_digest }}。Prompt只作溯源，不改变固定计分；未提供本项目独立临床效果验证。</p><p>{{ analysis.attribution }}</p><p v-for="reference in analysis.rule_references" :key="reference" class="hash">原始规则依据：{{ reference }}</p>
      </template>
    </template>
  </section>
</template>
<script setup>
import { noticeText, noticeList } from "@/utils/noticeText.cjs";
import { computed } from "vue";
import { qsofaAssessmentMatches, qsofaCanonical } from "@/api/aiQsofa";
import { gcsAbsentLabels, gcsHash } from "@/api/inpatientGcs";
const props = defineProps({ source: { type: Object, default: null }, analysis: { type: Object, default: null }, scope: { type: Object, default: null }, expectedPatientId: { type: Number, required: true }, expectedAdmissionId: { type: String, required: true } });defineEmits(["inspect"]);
const keys = ["respiratory_rate", "systolic_bp", "mentation"], labels = { respiratory_rate: "呼吸率", systolic_bp: "收缩压", mentation: "意识（原完整GCS）" }, careLabels = { non_icu: "已核实非ICU", icu: "ICU", unknown: "未知" }, infectionLabels = { suspected: "疑似感染", documented: "已知感染", not_suspected: "未疑似感染", unknown: "未知" }, interpretLabels = { confirmed: "明确可判读", limited: "受限", unknown: "未知" }, scopeLabels = { confirmed: "人工声明范围内，未独立核实", unknown: "适用范围未知", outside_scope: "超出声明范围" }, calcLabels = { computed: "完整计数", insufficient_data: "资料不足", outside_scope: "超出范围" }, statuses = { scored: "已计分", missing: "缺项", conflict: "原来源冲突", requires_review: "须复核", outside_scope: "不评分" }, thresholdLabels = { at_least_two: "已核对分项达到至少2项提示阈值。", below_two_in_complete_data: "本次三项计数低于2项提示阈值。", unknown: "本次阈值结果未知，未取得的分项不默认0。" };
const scoped = computed(() => !!props.source && qsofaAssessmentMatches({ ...props.scope, specialist_source: props.source }, props.expectedPatientId, props.expectedAdmissionId, props.source.window_id, true));
const rawRows = computed(() => [ ...keys.slice(0,2).map(key => { const item=props.source?.measurements?.[key];return {label:labels[key],display:item?.value ?? (item ? `未测（${item.absent_reason}）` : "未记录"),unit:item?.unit,clock:props.source?.observed_at}; }), ...Object.entries(props.source?.gcs?.components || {}).map(([key,item])=>({label:`GCS ${key}`,display:item.score ?? gcsAbsentLabels[item.absent_reason] ?? "未知",unit:"原分项",clock:props.source.gcs.observed_at})) ]);
const bound = computed(() => {
  const value = props.analysis, source = props.source;
  if (!scoped.value || !value || value.schema_version !== "1" || value.rule_id !== "qsofa_sepsis3_2016" || qsofaCanonical(value.source_binding) !== qsofaCanonical(source) || value.diagnosis_provided !== false || value.probability_provided !== false || value.clinical_validation !== "not_provided" || value.independent_implementation !== true || !Array.isArray(value.criteria) || value.criteria.length !== 3 || !Array.isArray(value.missing_data) || !Array.isArray(value.warnings) || !Array.isArray(value.rule_references) || value.rule_references.length !== 4 || !gcsHash(value.instructions_digest)) return false;
  const runtime = value.local_runtime;
  if (runtime?.engine !== "stdlib-qsofa-rules" || runtime.rule_id !== source.rule_id || runtime.recipe_digest !== source.recipe_digest || !gcsHash(runtime.runtime_digest) || runtime.model_version !== `qsofa:${runtime.runtime_digest}` || runtime.prompt_handling !== "provenance_only" || runtime.clinical_validation !== "not_provided") return false;
  for (const [index,row] of value.criteria.entries()) {
    if (row.key !== keys[index] || !(row.status in statuses) || !Array.isArray(row.source_ids) || !row.source_ids.length || row.source_ids.some(id => ![source.source_id,source.point_source_id,source.gcs?.source_id].includes(id)) || (row.status === "scored" ? ![0,1].includes(row.score) : row.score !== null)) return false;
    const expectedIds = index < 2 ? [source.point_source_id] : source.gcs ? [source.gcs.source_id, source.point_source_id] : [source.source_id];
    if (qsofaCanonical(row.source_ids) !== qsofaCanonical(expectedIds)) return false;
    if (index < 2) { const original=source.measurements[row.key];if (row.raw_value !== (original?.value ?? null) || row.unit !== (index === 0 ? "/min" : "mm[Hg]") || row.observed_at !== source.observed_at || !row.source_ids.includes(source.point_source_id)) return false; }
    else { const gcs=source.gcs, scores=gcs?Object.values(gcs.components).map(item=>item.score):[], total=scores.length===3 && scores.every(score=>Number.isInteger(score))?String(scores.reduce((sum,score)=>sum+score,0)):null;if(row.raw_value!==total || row.unit!=="score" || row.observed_at!==(gcs?.observed_at ?? null) || (gcs && !row.source_ids.includes(gcs.source_id)))return false; }
  }
  const outside = source.age_at_observation_years !== null && source.age_at_observation_years < 18 || source.care_setting === "icu" || source.infection_status === "not_suspected", unknown = source.age_at_observation_years === null || source.care_setting === "unknown" || source.infection_status === "unknown";
  if (value.scope_status !== (outside ? "outside_scope" : unknown ? "unknown" : "confirmed")) return false;
  const scored=value.criteria.filter(row=>row.status==="scored"), subtotal=scored.length?scored.reduce((sum,row)=>sum+row.score,0):null;
  if (value.scored_count !== scored.length || value.observed_subtotal !== subtotal || typeof value.score_is_lower_bound !== "boolean") return false;
  if (value.scope_status !== "confirmed") return value.criteria.every(row=>row.score===null) && value.total_score===null && subtotal===null && value.score_is_lower_bound===false && value.threshold_status==="unknown" && value.calculation_status===(outside?"outside_scope":"insufficient_data");
  const total=scored.length===3?subtotal:null;
  return value.total_score===total && value.score_is_lower_bound===(total===null && subtotal!==null) && value.calculation_status===(total===null?"insufficient_data":"computed") && value.threshold_status===(subtotal>=2?"at_least_two":total!==null?"below_two_in_complete_data":"unknown");
});
</script>
<style scoped>p{line-height:1.7;}.hash{overflow-wrap:anywhere;}</style>
