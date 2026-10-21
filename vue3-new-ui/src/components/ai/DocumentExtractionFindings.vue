<template>
 <section class="document-extraction-findings" aria-label="原文条款抽取核对">
  <el-alert v-if="!sessionAllowed" title="仅当前超级管理员可核对原文抽取结果" type="warning" :closable="false" />
  <el-button v-if="closed&&sessionAllowed" @click="reopen">重新核对原任务</el-button>
  <template v-if="authorized">
   <el-button @click="close">关闭并清除抽取结果</el-button>
   <el-alert v-if="error" :title="error" type="error" :closable="false" />
   <p v-if="busy" role="status">正在核对完整原文、冻结Prompt与保留摘要…</p>
   <template v-if="proof">
    <el-alert title="未审核模型草稿：逐字位置一致不代表临床含义、隐私、适用性或完整覆盖正确" type="warning" :closable="false" />
    <p v-if="auditOnly" aria-label="抽取审计只读">冻结审计，只读；不能保存候选或发布知识。</p>
    <dl><dt>原文</dt><dd>{{ proof.run.document_original.snapshot.metadata.title }} · {{ proof.run.document_original.snapshot.metadata.version }}</dd><dt>原文当前治理</dt><dd aria-label="抽取原文当前治理">{{ originalStates[proof.run.document_original.governance.status] }}{{ proof.run.document_original.eligible?'':'；历史冻结签署不恢复当前资格。' }}</dd><dt>任务状态</dt><dd>{{ states[proof.run.status] }}</dd><dt>Prompt与模型</dt><dd>已比对服务器冻结Prompt及模型摘要，并核对保留的原JSON字节；这不等于独立观测模型服务或临床验证。</dd></dl>
    <p aria-label="抽取实际用量">实际输入用量：{{ shown(proof.run.usage_receipt.input_tokens) }}；实际输出用量：{{ shown(proof.run.usage_receipt.output_tokens) }}。{{ proof.run.usage_receipt.complete?'回执完整':'用量回执不完整；未知未按0补齐' }}</p>
    <template v-if="proof.run.result">
     <p aria-label="抽取固定摘要">{{ proof.run.result.summary }}</p>
     <p v-if="!proof.run.result.document_extraction.spans.length">本次草稿为空；不能据此认为全文没有条款或已完整覆盖。</p>
     <article v-for="(span,index) in proof.run.result.document_extraction.spans" :key="index" :aria-label="`未审核条款草稿${index+1}`">
      <p>模型拟题（未审核）：{{ span.proposed_heading }}</p><p>{{ clauseKinds[span.clause_kind] }}；Unicode codepoint 区间 [{{ span.start }}, {{ span.end }})，零起点、右端不包含。</p>
      <pre :aria-label="`第${index+1}条逐字引文`">{{ span.quote }}</pre>
      <el-button v-if="!auditOnly" :disabled="!canSave||busy||!!saved[index]" @click="save(index)">保存第{{ index+1 }}条为未审核候选</el-button>
      <p v-if="saved[index]" :aria-label="`第${index+1}条候选保存回执`">已明确保存为未审核候选 {{ saved[index].snapshot.candidate_id }}；隐私和原意尚未审核，未发布知识。</p>
     </article>
     <p v-for="note in proof.run.result.warnings" :key="note">{{ note }}</p>
    </template>
    <p v-else>此状态没有已接收的条款草稿；未创建候选或知识。</p>
    <el-button @click="rawOpen=!rawOpen">{{ rawOpen?'收起冻结完整原文':'展开冻结完整原文' }}</el-button>
    <pre v-if="rawOpen" aria-label="抽取冻结完整原文">{{ proof.run.document_extraction_findings.document_source.text }}</pre>
   </template>
  </template>
 </section>
</template>
<script setup>
import {documentClauseKinds as clauseKinds} from '@/api/ai/documentEvidence';
import {useDocumentExtractionFindings} from './useDocumentExtractionFindings';
const props=defineProps({run:{type:Object,default:null},trace:{type:Object,default:null},expectedRunId:{type:String,default:null},expectedOriginalId:{type:String,default:null},active:{type:Boolean,default:true},auditOnly:{type:Boolean,default:false}}),emit=defineEmits(['candidate-saved','cleared']);
const {authorized,sessionAllowed,closed,reopen,proof,busy,error,rawOpen,saved,canSave,close,save}=useDocumentExtractionFindings(props,emit);
const originalStates={draft:'待审核',published:'已发布',rejected:'已拒绝',revoked:'已撤销'};
const states={queued:'排队中',running:'执行中',succeeded:'草稿已接收，未审核',failed:'任务失败',cancelled:'已取消'},shown=v=>v===null?'未知':String(v);
</script>
<style scoped>
.document-extraction-findings{display:grid;gap:12px}article{border:1px solid var(--el-border-color);padding:12px}pre{white-space:pre-wrap;overflow-wrap:anywhere;max-height:360px;overflow:auto}dl{display:grid;grid-template-columns:100px 1fr;gap:8px}dd{margin:0;overflow-wrap:anywhere}
</style>
