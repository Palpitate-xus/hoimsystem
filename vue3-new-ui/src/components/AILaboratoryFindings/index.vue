<template>
  <section aria-label="冻结检验原来源复核">
    <p v-if="!scoped" role="alert">检验来源与指定患者或原住院不一致，不展示其他范围原值。</p>
    <template v-else>
      <p class="hash">检验来源 {{ source.lab_source_id }} · 原住院 {{ source.admission_id }} · 状态 {{ statusLabel(source.status) }} · v{{ source.revision }}<br />内容摘要 {{ source.content_hash }}</p>
      <p>人工核实采样UTC：{{ source.collected_at_utc || frozen?.collected_at_utc || '未提供' }}<br />本次登记：{{ source.registered_at || frozen?.registered_at || '未提供' }}<br />本次纳入可用：{{ source.available_at || frozen?.available_at || '未提供' }}。这是本次受控登记可用时点，不是原报告首次可用时间。</p>
      <p v-if="source.freshness">当前一致性：{{ freshnessLabel(source.freshness.state) }}。{{ source.freshness.message || '' }}</p>
      <p>当前输入资格：{{ source.eligible === true ? '本次核对可纳入，生成时仍会复核' : '未确认可作为当前有效输入' }}；当前映射状态 {{ source.mapping_current?.status || '未提供' }}。{{ (source.exclusion_reasons || []).map(reason => ({ source_revoked: '来源已撤销', mapping_revoked: '项目映射已撤销' })[reason] || reason).join('；') }}</p>
      <p v-if="!frozen">当前响应未提供冻结原值；已变化或撤销的旧资料不能补作当前有效来源。</p>
      <template v-else>
        <p v-if="source.window_projection">此为目标检验项及父链标识的观测窗投影；原报告全文与申请正文未作为本窗事实输入，原摘要仍绑定完整原资料。人工核实说明仅用于溯源，不是测量结果。</p>
        <p>以下保留当时原数据库的结构化值及其表示，不声称恢复最初输入词法。旧采样、报告、审核钟点原样展示，未自动补时区。</p>
        <dl class="lab-fields">
          <div><dt>原观察项 / 报告 / 申请</dt><dd>{{ observation.observation_id || source.observation_id }} / {{ report.lab_result_id || '未提供' }} / {{ order.lab_order_id || report.lab_order_id || '未提供' }}</dd></div>
          <div><dt>原项目</dt><dd>{{ observation.display || '未提供' }} · {{ observation.code_system }}:{{ observation.code }}</dd></div>
          <div><dt>原数据库结果</dt><dd aria-label="冻结原检验值">{{ observation.value_num !== null && observation.value_num !== undefined ? observation.value_num : observation.value_text ?? '未提供' }} {{ observation.unit ?? '' }}</dd></div>
          <div><dt>方法 / 标本</dt><dd>{{ observation.method || '未记录' }} / {{ observation.specimen_type || '未记录' }}</dd></div>
          <div><dt>原采样钟点（时区未知）</dt><dd>{{ observation.collected_at ?? '未记录' }}</dd></div>
          <div><dt>原报告 / 审核钟点</dt><dd>{{ report.report_time ?? '未记录' }} / {{ report.audit_time ?? '未记录' }}（保留原时钟语义）</dd></div>
          <div><dt>原报告审核</dt><dd>{{ report.audit_status === 1 ? '原报告已审核' : '未确认已审核' }}；不代表映射或模型已验证</dd></div>
          <div><dt>冻结项目映射</dt><dd>{{ mapping.label || mapping.analyte_label || mapping.analyte_key || '未提供' }} · {{ mapping.mapping_id || source.mapping_id }} · v{{ mapping.revision ?? '未知' }} · {{ mapping.status || '未知状态' }}</dd></div>
          <div><dt>冻结来源命名空间</dt><dd>{{ mapping.source_namespace || '未提供' }}</dd></div>
          <div><dt>映射依据</dt><dd>{{ mapping.evidence_reference || '未提供' }}</dd></div>
        </dl>
        <p>采样UTC核实依据：{{ frozen.collection_time_basis_note || '未提供' }}</p>
        <p>原住院关联依据：{{ frozen.admission_binding_note || '未提供' }}</p>
        <p>来源命名空间核实依据：{{ frozen.source_namespace_basis_note || '未提供' }}</p>
        <p>仅核对项目身份和原来源；未自动换算单位、补齐基线、推断感染、计算量表或验证临床模型。</p>
      </template>
    </template>
  </section>
</template>
<script setup>
import { computed } from "vue";
import { labSourceMatches } from "@/api/inpatientLaboratory";
const props = defineProps({ source: { type: Object, required: true }, expectedPatientId: { type: Number, required: true }, expectedAdmissionId: { type: String, required: true } });
const scoped = computed(() => labSourceMatches(props.source, props.expectedPatientId, props.expectedAdmissionId));
const frozen = computed(() => props.source?.snapshot || null);
const observation = computed(() => frozen.value?.original?.observation || {}), report = computed(() => frozen.value?.original?.report || {}), order = computed(() => frozen.value?.original?.order || {}), mapping = computed(() => frozen.value?.mapping || {});
const statusLabel = status => ({ active: "活动", revoked: "已撤销，仅供审计" }[status] || "状态待核对");
const freshnessLabel = status => ({ current: "本次核对一致", stale: "原资料已变化", revoked: "已撤销", not_checked: "尚未核对" }[status] || "尚未核对");
</script>
<style scoped>.lab-fields { display: grid; grid-template-columns: repeat(auto-fit,minmax(240px,1fr)); gap: 12px; }.lab-fields dd { margin-left: 0; overflow-wrap: anywhere; }p { line-height: 1.7; }.hash { overflow-wrap: anywhere; }</style>
