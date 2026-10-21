<template><div v-if="node" class="criteria-summary"><template v-if="['all','any'].includes(node.op)"><p>{{ node.op==='all'?'以下全部条件满足':'以下任一条件满足' }}：</p><ResearchCohortCriteriaSummary v-for="(child,index) in node.children" :key="index" :node="child" /></template><template v-else-if="node.op==='not'"><p>以下条件取反；未知仍保留未知：</p><ResearchCohortCriteriaSummary :node="node.child" /></template><template v-else><p>{{ families[node.family] }}，原字段 {{ node.field }}；{{ node.quantifier==='any_record'?'至少一条记录符合':'全部所列记录符合，空集合保持未知' }}。</p><p v-if="node.op==='recorded_scalar_equal'">原记录整数等于 {{ node.expected }}。</p><p v-else-if="node.op==='recorded_date_compare'">原日历日期{{ comparisons[node.comparison] }} {{ node.expected }}；原时区未知。</p><template v-else><p>原文包含以下完整字面量：</p><pre>{{ node.literal }}</pre></template></template></div></template>
<script setup>
defineProps({node:{type:Object,default:null}});
const families={patient_demographics:'有限人口学字段',registrations:'挂号记录',admissions:'住院记录',medical_records:'门诊病历',structured_medical_records:'结构化病历'},comparisons={before:'早于',on:'等于',after:'晚于'};
</script>
<style scoped>
.criteria-summary{margin:8px 0;padding:8px;border-left:2px solid #dcdfe6}pre{white-space:pre-wrap;overflow-wrap:anywhere}
</style>
