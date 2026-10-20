<template>
  <section v-if="findings?.incident_record" class="incident-findings">
    <h4>本次事件原始资料</h4>
    <p>{{ findings.scope_note }}</p>
    <p>读取时刻：{{ findings.snapshot_time || '旧任务未留存' }}；事件标识：{{ findings.incident_record.event_id }}</p>
    <p>就诊归属：未记录；独立根因核验状态：未记录。</p>
    <p v-for="(text, index) in findings.missing_data || []" :key="index" class="data-gap">{{ text }}</p>
    <p v-if="findings.truncated_sources?.length" class="data-gap">关联分析清单有截断，不能据此断言没有其他调查记录。</p>
    <el-descriptions :column="1" border>
      <el-descriptions-item label="原事件类型">{{ findings.incident_record.recorded_event_type || '未记录' }}</el-descriptions-item>
      <el-descriptions-item label="原上报时间">{{ findings.incident_record.report_time || '未记录' }}</el-descriptions-item>
      <el-descriptions-item label="原严重度编码">{{ findings.incident_record.recorded_severity ?? '未知' }}</el-descriptions-item>
      <el-descriptions-item label="原处理状态">{{ ({ 0: '待处理', 1: '处理中', 2: '已闭环' })[findings.incident_record.recorded_status] || '未知' }}</el-descriptions-item>
      <el-descriptions-item label="上报陈述"><p class="recorded-text">{{ findings.incident_record.reported_description || '未记录' }}</p></el-descriptions-item>
      <el-descriptions-item label="原处理结论"><p class="recorded-text">{{ findings.incident_record.recorded_handle_result || '未记录' }}</p></el-descriptions-item>
    </el-descriptions>
    <p>{{ findings.incident_record.definition_note }}</p>
    <el-button link @click="$emit('inspect', findings.incident_record.source_id)">查看事件上报依据</el-button>
    <el-collapse>
      <el-collapse-item v-for="row in findings.incident_rca_records || []" :key="row.source_id" :name="row.source_id" :title="`已保存RCA #${row.rca_id} · 核验状态未记录`">
        <p>{{ row.definition_note }}</p>
        <el-descriptions :column="1" border><el-descriptions-item v-for="(label, key) in fields" :key="key" :label="label"><p class="recorded-text">{{ row[key] ?? '未记录' }}</p></el-descriptions-item></el-descriptions>
        <el-button link @click="$emit('inspect', row.source_id)">查看已保存RCA依据</el-button>
      </el-collapse-item>
    </el-collapse>
  </section>
</template>

<script setup>
defineProps({ findings: { type: Object, default: null } });
defineEmits(["inspect"]);
const fields = { recorded_summary: "原分析摘要", recorded_timeline_text: "原时间线文本", recorded_root_cause_text: "原根因分析文本", recorded_corrective_actions: "原改进措施", recorded_pdca_stage: "原PDCA阶段", recorded_responsible_department: "原责任科室", due_date: "原期限", recorded_completed_date: "原完成日期", recorded_effect_evaluation: "原效果评价", updated_at: "原更新时间" };
</script>

<style scoped>
.incident-findings { line-height: 1.7; margin: 16px 0; }
.recorded-text { white-space: pre-wrap; overflow-wrap: anywhere; margin: 0; }
.data-gap { color: #9a6700; }
</style>
