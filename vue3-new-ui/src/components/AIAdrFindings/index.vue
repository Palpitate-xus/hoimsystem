<template>
  <section v-if="findings?.reports?.length" class="adr-findings">
    <h4>ADR原上报与处理记录</h4><p>{{ findings.scope_note }}</p>
    <p>症状发生时间、实际给药关联与对应就诊：原记录未注明，不根据上报时间推断。</p>
    <el-collapse><el-collapse-item v-for="row in findings.reports" :key="row.source_id" :name="row.source_id" :title="`ADR #${row.reaction_id} · ${row.status_text || '状态待核实'}`">
      <p v-if="row.recorded_state === 'legacy_ambiguous'" class="data-gap">历史状态2尚未核实为已处理或已排除，保持未知。</p>
      <el-descriptions :column="1" border>
        <el-descriptions-item label="原报告药品">{{ row.drug_reference_resolved ? row.pharmaceutical_name : '原药品引用未核实' }}</el-descriptions-item>
        <el-descriptions-item label="原上报症状"><p class="recorded-text">{{ row.reported_symptom || '未记录' }}</p></el-descriptions-item>
        <el-descriptions-item label="原严重度">{{ severities[row.recorded_severity] || '未知' }}（原码 {{ row.recorded_severity ?? '未记录' }}）</el-descriptions-item>
        <el-descriptions-item label="原上报时间">{{ row.report_time || '未记录' }}</el-descriptions-item>
        <el-descriptions-item label="原上报备注"><p class="recorded-text">{{ row.recorded_note || '未记录' }}</p></el-descriptions-item>
        <el-descriptions-item label="原处理说明"><p class="recorded-text">{{ row.resolution_note || '未记录' }}</p></el-descriptions-item>
        <el-descriptions-item label="原处理核实时间">{{ row.status_reviewed_at || '未记录' }}</el-descriptions-item>
      </el-descriptions>
      <p>{{ row.definition_note }}</p><p>{{ row.onset_and_exposure_note }}</p>
      <el-button link @click="$emit('inspect', row.source_id)">查看ADR原始依据</el-button>
    </el-collapse-item></el-collapse>
  </section>
</template>
<script setup>
defineProps({ findings: { type: Object, default: null } });
defineEmits(["inspect"]);
const severities = { 1: "上报轻度", 2: "上报中度", 3: "上报重度" };
</script>
<style scoped>
.adr-findings { line-height: 1.7; margin: 16px 0; }
.recorded-text { white-space: pre-wrap; overflow-wrap: anywhere; margin: 0; }
.data-gap { color: #9a6700; }
</style>
