<template>
  <section v-if="findings" class="nursing-findings" aria-label="护理与评分原始依据">
    <h4>护理与评分原始依据</h4>
    <p>仅本次住院的有限原记录；未知项保留为未知。人工分项汇总不能作为疾病概率或自动转出决定。</p>
    <p v-for="note in findings.limitations || []" :key="note" class="data-gap">{{ note }}</p>
    <el-collapse>
      <el-collapse-item v-for="row in findings.assessments || []" :key="row.source_id" :name="row.source_id" :title="`已完成护理评估${row.explicitly_selected ? ' · 本次所选' : ''}`">
        <p>评估发生时间：{{ utcTime(row.assessed_at) }}；原创建：{{ row.create_time || '未记录' }}；原更新：{{ row.update_time || '未记录' }}。</p>
        <p v-if="row.legacy_defaults_possible" class="data-gap">历史记录：原默认值是否经过显式评估未核实，保留原值。</p>
        <p v-else>新表单保留未评估项；保存或完成不代表标准量表验证。</p>
        <el-descriptions :column="1" border>
          <el-descriptions-item v-for="(label, key) in assessmentFields" :key="key" :label="label">{{ assessmentValue(row, key) }}</el-descriptions-item>
          <el-descriptions-item label="护理备注"><p class="recorded-text">{{ row.note || '未记录' }}</p></el-descriptions-item>
        </el-descriptions>
        <p>未知项：{{ names(row.missing_fields) || '这五项已有原值；量表版本与逐项答案仍未记录' }}。</p>
        <el-button link @click="$emit('inspect', row.source_id)">核对原评估依据</el-button>
      </el-collapse-item>
      <el-collapse-item v-for="row in findings.critical_records || []" :key="row.source_id" :name="row.source_id" :title="`危重护理原记录${row.explicitly_selected ? ' · 本次所选' : ''}`">
        <p>原时间：{{ row.record_time || '未记录' }}；{{ timeBases[row.time_basis] || '原时区未注明' }}。</p>
        <p v-if="row.legacy_defaults_possible" class="data-gap">历史默认值是否经过显式评估未核实。</p>
        <p>意识原标记：{{ row.consciousness == null ? '未评估' : (consciousness[row.consciousness] ?? `未知原值 ${row.consciousness}`) }}；GCS原总数：{{ row.gcs_score ?? '未评估' }}，未提供睁眼、语言、运动三项，不重新计算。</p>
        <p>脉搏：{{ row.pulse ?? '未记录' }}；SpO₂：{{ row.spo2 ?? '未记录' }}。氧疗原文：{{ row.oxygen_support || '未记录' }}；血压原文：{{ row.blood_pressure || '未记录' }}；尿量原文：{{ row.urine_output || '未记录' }}。</p>
        <p class="recorded-text">{{ row.note || '无备注' }}</p>
        <el-button link @click="$emit('inspect', row.source_id)">核对危重护理依据</el-button>
      </el-collapse-item>
      <el-collapse-item v-for="row in findings.scores || []" :key="row.source_id" :name="row.source_id" :title="`${scoreTitle(row)}原评分${row.explicitly_selected ? ' · 本次所选' : ''}`">
        <p>原总分：{{ row.total_score ?? '未记录' }}；评估发生时间：{{ utcTime(row.assessed_at) }}；原登记时间：{{ row.assess_time || '未记录' }}。</p>
        <p :class="{ 'data-gap': row.component_check?.state !== 'manual_sum_matches' }">{{ scoreChecks[row.component_check?.state] || '完整性未核实' }}。{{ row.component_check?.note }}</p>
        <p>版本：{{ row.calculation_version || 'legacy_unverified' }}；原分项：</p><pre class="recorded-text">{{ row.detail_json || '未记录' }}</pre>
        <p class="recorded-text">原保存解释（未重新验证）：{{ row.interpretation || '未记录' }}</p>
        <el-button link @click="$emit('inspect', row.source_id)">核对原评分依据</el-button>
      </el-collapse-item>
      <el-collapse-item v-for="row in findings.plans || []" :key="row.source_id" :name="row.source_id" :title="`护理计划${row.explicitly_selected ? ' · 本次所选' : ''}`">
        <p>原状态：{{ ({ 0: '进行中', 1: '已完成', 2: '已取消' })[row.status] || '未知' }}。{{ row.status_note }}</p>
        <p class="recorded-text">原护理诊断：{{ row.nursing_diagnosis || '未记录' }}</p><p class="recorded-text">原目标：{{ row.goal || '未记录' }}</p><p class="recorded-text">原措施：{{ row.measures || '未记录' }}</p>
        <el-button link @click="$emit('inspect', row.source_id)">核对原护理计划依据</el-button>
      </el-collapse-item>
    </el-collapse>
  </section>
</template>

<script setup>
defineProps({ findings: { type: Object, default: null } });
defineEmits(["inspect"]);
const assessmentFields = { adl_score: "ADL原分值", pressure_ulcer_risk: "压疮风险原标记", fall_risk: "跌倒风险原标记", consciousness: "意识原标记", nutrition_risk: "营养风险原标记" };
const consciousness = { 0: "清醒", 1: "嗜睡", 2: "意识模糊", 3: "昏迷" };
const risks = { 0: "无（原标记0）", 1: "低（原标记1）", 2: "中（原标记2）", 3: "高（原标记3）" };
const scoreNames = { gcs: "GCS", sofa: "原1996 SOFA", apache2: "APACHE II人工小计", aldrete: "原1970 Aldrete", steward: "Steward" };
const legacyScoreNames = { gcs: "GCS", sofa: "SOFA", apache2: "APACHE II", aldrete: "Aldrete", steward: "Steward" };
const scoreTitle = row => row.calculation_version === "manual_components_v2" ? scoreNames[row.score_type] || row.score_type : `${legacyScoreNames[row.score_type] || row.score_type}（历史定义未核实）`;
const timeBases = { utc: "明确UTC时间", unspecified: "原时区未注明", recorded_at_only: "仅登记时刻，非已核实观测时刻" };
const scoreChecks = { legacy_unverified: "历史分项完整性未核实", invalid_components: "原分项不完整或不合法", total_mismatch: "分项与原总分矛盾", manual_sum_matches: "人工分项算术一致，临床正确性未核实" };
const names = fields => (fields || []).map(key => assessmentFields[key] || key).join("、");
const utcTime = value => value ? `${value}（UTC）` : "未记录，不用更新时间代替";
function assessmentValue(row, key) {
  if (row[key] == null) return "未评估";
  if (key === "adl_score") return row[key];
  const labels = key === "consciousness" ? consciousness : risks;
  return labels[row[key]] ?? `未知原值 ${row[key]}`;
}
</script>

<style scoped>
.nursing-findings { line-height: 1.7; margin: 16px 0; }
.data-gap { color: #9a6700; }
.recorded-text { white-space: pre-wrap; overflow-wrap: anywhere; margin: 0; }
</style>
