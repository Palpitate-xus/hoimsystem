<template>
  <section v-if="findings && (findings.current_templates?.length || findings.enrollments?.length)" class="pathway-findings">
    <h4>院内路径与原入径记录</h4><p>{{ findings.scope_note }}</p>
    <el-collapse>
      <el-collapse-item v-for="row in findings.current_templates || []" :key="row.source_id" :name="row.source_id" :title="`${row.name || '原模板未核实'} · 路径 #${row.pathway_id}${row.explicitly_selected ? ' · 本次所选' : ''}`">
        <p>当前目录状态：{{ row.exists_in_current_directory ? ({ 0: '启用', 1: '停用' })[row.recorded_status] || '未知' : '未核实' }}；原病种：{{ row.disease_name || '未记录' }}；原疾病编码：{{ row.disease_code || '未记录' }}。</p>
        <p v-if="row.reviewed_knowledge">本功能可引用的当前审核版本：{{ row.reviewed_knowledge.version }}。适用于该患者的条件仍待核对。</p>
        <p v-else class="data-gap">本功能和科室缺少当前匹配的已审核版本，未提供原步骤用于推荐。</p>
        <p>原预计天数：{{ row.expected_days ?? '未记录' }}，不作个体出院目标。当前模板不是入径当时冻结版本。</p>
        <p>{{ row.definition_note }}</p><el-button link @click="$emit('inspect', row.source_id)">查看当前模板元数据依据</el-button>
      </el-collapse-item>
      <el-collapse-item v-for="row in findings.enrollments || []" :key="row.source_id" :name="row.source_id" :title="`入径 #${row.enrollment_id} · ${row.recorded_status_meaning || '状态未知'}${row.explicitly_selected ? ' · 本次所选' : ''}`">
        <p>就诊关联：{{ assignments[row.encounter_assignment] || '待核实' }}。入径当时的模板版本与逐项实际执行：未记录。</p>
        <el-descriptions :column="1" border>
          <el-descriptions-item label="原入径日期">{{ row.enroll_date || '未记录' }}</el-descriptions-item>
          <el-descriptions-item label="原退出日期">{{ row.exit_date || '未记录' }}</el-descriptions-item>
          <el-descriptions-item label="原完成计数">{{ row.completed_items ?? '未记录' }} / {{ row.total_items ?? '未记录' }}；{{ row.counter_state === 'known' ? `${row.completion_rate}%（仅计数比例）` : row.counter_state === 'invalid' ? '原计数矛盾，比例未计算' : '比例未知' }}</el-descriptions-item>
          <el-descriptions-item label="原变异类型">{{ row.variation_type || '未记录' }}</el-descriptions-item>
          <el-descriptions-item label="原变异原因"><p class="recorded-text">{{ row.variation_reason || '未记录' }}</p></el-descriptions-item>
          <el-descriptions-item label="原退出原因"><p class="recorded-text">{{ row.exit_reason || '未记录' }}</p></el-descriptions-item>
        </el-descriptions>
        <p :class="{ 'data-gap': row.counter_state !== 'known' }">{{ row.counter_note }}</p><p>{{ row.definition_note }}</p>
        <el-button link @click="$emit('inspect', row.source_id)">查看原入径记录依据</el-button>
      </el-collapse-item>
    </el-collapse>
  </section>
</template>
<script setup>
defineProps({ findings: { type: Object, default: null } });
defineEmits(["inspect"]);
const assignments = { current_encounter: "已核实对应本次住院", verified_historical_admission: "已核实历史住院，未指定本次就诊", not_recorded: "原记录未注明，不按日期推断" };
</script>
<style scoped>
.pathway-findings { line-height: 1.7; margin: 16px 0; }
.recorded-text { white-space: pre-wrap; overflow-wrap: anywhere; margin: 0; }
.data-gap { color: #9a6700; }
</style>
