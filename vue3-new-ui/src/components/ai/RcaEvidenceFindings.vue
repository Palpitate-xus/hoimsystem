<template>
 <section aria-label="事件RCA未核实假设与完整证明">
  <p v-if="v.error" role="alert">{{v.error}}</p><el-button v-if="v.closed&&active" @click="v.reopen">显式重新核对RCA结果</el-button><p v-if="v.busy" role="status">正在核对全部分件与原任务锚。</p><el-button v-if="v.busy" @click="v.close">关闭RCA核验并清除</el-button>
  <template v-if="v.value&&v.authorized"><el-button @click="v.close">关闭并清除RCA结果</el-button><p>本任务 {{v.value.run.run_id}}：{{v.value.run.status}}。仅部分待调查假设，不确认因果、责任、调查完整或整改成效，不自动写回RCA或PDCA。</p>
   <p aria-label="RCA实际用量">输入 {{shown(v.value.run.input_tokens)}} / 输出 {{shown(v.value.run.output_tokens)}}；回执 {{v.value.run.usage_receipt_status}}；模型调用 {{attempt(v.value.run.usage_receipt?.model_call_attempted)}}。未知不补零。</p>
   <p>完整发布文字 {{v.value.parts.source.items.length}} 件；人工时间线 {{v.value.parts.source.timeline.length}} 条；完整成员 {{v.value.parts.source.members.length}} 根。已核对完整Case与可见投影；原终态22字段摘要仅作为服务端锚，未声称浏览器重建不可见字段。</p>
   <p v-if="v.value.parts.result">{{v.value.parts.result.summary}}</p><p v-else>本状态没有已接收模型草稿；不是没有事件促成因素或已完成调查。</p>
   <ol aria-label="RCA未核实假设列表"><li v-for="(h,index) in v.visible" :key="(v.page-1)*8+index"><p>未核实候选：{{h.hypothesis}}</p><div v-for="(q,i) in [...h.supporting_quotes,...h.conflicting_quotes]" :key="i"><p>{{i<h.supporting_quotes.length?'支持引文':'冲突引文'}} {{q.item_id}} [{{q.start}},{{q.end}}) Unicode codepoint</p><details><summary>显式定位这段完整原文中的逐字引文</summary><pre v-if="v.quote(q)" aria-label="RCA逐字引文定位">{{v.quote(q).before}}<mark>{{v.quote(q).quote}}</mark>{{v.quote(q).after}}</pre></details></div><p>尚需证据：{{h.evidence_needed.join('；')||'本候选未列出，不表示证据完整'}}</p><p>待调查问题：{{h.investigation_questions.join('；')||'本候选未列出，不表示已查清'}}</p><p>人工时间线引用：{{h.timeline_entry_ids.join('；')||'未引用'}}</p></li></ol>
   <el-pagination v-if="v.hypotheses.length>8" v-model:current-page="v.page" :page-size="8" :total="v.hypotheses.length" layout="prev,pager,next" aria-label="RCA全部候选分页"/>
   <ul v-if="v.value.parts.result"><li v-for="q in v.value.parts.result.rca_evidence_draft.clarification_questions" :key="q">待澄清：{{q}}</li></ul>
   <el-button @click="v.showSource=!v.showSource">{{v.showSource?'收起完整模型所见资料':'显式展开完整模型所见资料'}}</el-button><pre v-if="v.showSource" aria-label="RCA完整模型所见资料">{{pretty(v.value.parts.source)}}</pre>
   <el-button @click="v.showPrivate=!v.showPrivate">{{v.showPrivate?'收起完整私有Case':'显式展开完整私有Case'}}</el-button><pre v-if="v.showPrivate" aria-label="RCA完整私有Case">{{pretty(v.value.parts.case)}}</pre>
   <template v-if="v.value.trace"><p>已按实际UTF8原字符串核对3项任务JSON及其SHA、固定System/实际Task Prompt、模型快照和精确AuditPK；这不认证因果。</p><el-button @click="v.showTrace=!v.showTrace">{{v.showTrace?'收起原任务JSON审计':'显式展开原任务JSON审计'}}</el-button><pre v-if="v.showTrace" aria-label="RCA完整原任务JSON审计">{{pretty(v.value.trace.raw_frozen_json)}}</pre></template>
  </template>
 </section>
</template>
<script setup>
import {reactive} from 'vue';import {useRcaEvidenceFindings} from './useRcaEvidenceFindings';const props=defineProps({run:{default:null},parts:{default:null},trace:{default:null},expectedRunId:{default:null},expectedCaseId:{default:null},auditOnly:{type:Boolean,default:false},configRevision:{default:null},active:{type:Boolean,default:true}}),emit=defineEmits(['invalidate','close','reload']),v=reactive(useRcaEvidenceFindings(props,emit)),pretty=v=>JSON.stringify(v,null,2),shown=v=>v===null?'未知':String(v),attempt=v=>v===true?'实际有调用回执':v===false?'明确未调用':'未知';defineExpose({state:v});
</script>
<style scoped>p,li{line-height:1.7;overflow-wrap:anywhere}pre{white-space:pre-wrap;overflow-wrap:anywhere;max-height:45vh;overflow:auto}.el-button{margin:6px}mark{background:#ffe38b}</style>
