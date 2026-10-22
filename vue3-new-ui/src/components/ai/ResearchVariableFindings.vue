<template>
 <section class="research-variable-findings" aria-label="科研变量逐字草稿核对">
  <el-alert v-if="!sessionAllowed" title="当前角色或登录状态不能核对科研变量原件；超级管理员同样需要项目和逐患者许可。" type="warning" :closable="false" />
  <el-button v-if="closed&&sessionAllowed&&active" @click="requestReload">重新读取当前任务</el-button>
  <template v-if="authorized">
   <el-button @click="close">关闭并清除科研变量内容</el-button>
   <p v-if="busy" role="status">正在核对完整来源、逐字段原量、任务锚与实际用量…</p>
   <el-alert v-if="error" :title="error" type="error" :closable="false" />
   <template v-if="proof">
    <el-alert title="未核实模型候选：逐字位置一致不证明临床含义、缺失机制、变量有效性或研究适用性。" type="warning" :closable="false" />
    <p v-if="auditOnly" aria-label="科研变量冻结审计">明确冻结审计，只读；原签署不恢复当前执行或导出资格。</p>
    <dl><dt>任务状态</dt><dd aria-label="科研变量任务状态">{{ states[proof.run.status] }}</dd><dt>本次明确来源</dt><dd>{{ source.records.length }} 条原记录、{{ source.documents.length }} 个原字段、{{ source.variables.length }} 项变量定义；仅限本次批次。</dd><dt>身份映射</dt><dd>已比对服务器冻结的代号摘要和原件顺序；未在客户端重算私有 HMAC。代号不表示匿名。</dd><dt>Prompt与模型锚</dt><dd>{{ proof.checked.level==='literal_source_and_raw_frozen_task'?'已核对保留的三份原JSON字节、完整Prompt、模型与验证配置。':'已比对服务器冻结的Prompt、模型和任务摘要；本视图未取得完整Prompt原件。' }}</dd></dl>
    <p v-if="proof.run.usage_receipt" aria-label="科研变量实际用量">实际输入用量：{{ shown(proof.run.usage_receipt.input_tokens) }}；实际输出用量：{{ shown(proof.run.usage_receipt.output_tokens) }}。{{ proof.run.usage_receipt.complete?'两项计数均有实际回执。':'用量回执不完整；未知没有按0补齐。' }}</p>
    <p v-else aria-label="科研变量实际用量">用量回执待结算；不能由物理0推断未调用模型。</p>
    <template v-if="proof.parts.result">
     <p aria-label="科研变量固定摘要">{{ proof.parts.result.result.summary }}</p>
     <p v-if="!candidates.length">本次没有提出候选，不能据此判断未测、不适用、正常、不存在或完整覆盖。</p>
     <article v-for="(candidate,index) in candidates" :key="index" :aria-label="`未核实变量候选${index+1}`">
      <h4>{{ index+1 }}. {{ variable(candidate.variable_key)?.label }}（未核实）</h4>
      <p>{{ classes[candidate.classification] }}；原类型：{{ kinds[candidate.value_kind] }}。{{ variable(candidate.variable_key)?.declared_unit===null?'未声明解释单位；原文不换算。':`人工声明单位：${variable(candidate.variable_key)?.declared_unit}；原文不换算。` }}</p>
      <p>Unicode 码点区间 [{{ candidate.start }}, {{ candidate.end }})，零起点、右端不包含。</p>
      <pre :aria-label="`科研变量第${index+1}条逐字引文`">{{ candidate.quote }}</pre>
     </article>
     <p v-for="note in proof.parts.result.result.warnings" :key="note">{{ note }}</p>
    </template>
    <p v-else>当前状态没有已接收的变量草稿；未构造空成功结果。</p>
    <p>未自动保存已审核变量、选择赢家、生成矩阵或CSV，未导出或回写临床记录。</p>
    <el-button @click="originalOpen=!originalOpen">{{ originalOpen?'收起本次完整原件':'展开本次完整原件' }}</el-button>
    <section v-if="originalOpen" aria-label="科研变量已授权原件">
     <p>仅展示本次已核对分件中的原量；原无时区钟点、NULL与0分别保留。</p>
     <ol><li v-for="(row,index) in visibleRecords" :key="(recordPage-1)*20+index"><el-button link @click="selectOriginal((recordPage-1)*20+index)">查看原记录 {{ (recordPage-1)*20+index+1 }}：{{ row.family }} · {{ row.recorded_clock===null?'原钟点未知':row.recorded_clock }}</el-button></li></ol>
     <el-pagination v-if="records.length>20" v-model:current-page="recordPage" layout="prev,pager,next" :page-size="20" :total="records.length" />
     <article v-if="original" aria-label="科研变量选定完整原记录">
      <p>原患者技术标识：{{ original.patient_id }}；原记录标识：{{ original.record_id }}；父关联原状态：{{ original.parent_binding.status }}。</p>
      <section v-for="field in original.variables" :key="field.variable_key"><p>{{ variable(field.variable_key)?.label }} · {{ field.value_kind }}</p><p v-if="field.literal===null" aria-label="科研变量原NULL">原值为NULL；缺失含义未知。</p><pre v-else aria-label="科研变量完整原字段">{{ field.literal }}</pre></section>
     </article>
    </section>
    <p v-for="note in source.limitations" :key="note">{{ note }}</p>
   </template>
  </template>
 </section>
</template>
<script setup>
import {useResearchVariableFindings} from './useResearchVariableFindings';
const props=defineProps({run:{type:Object,default:null},parts:{type:Object,default:null},trace:{type:Object,default:null},expectedRunId:{type:String,default:null},expectedBatchId:{type:String,default:null},active:{type:Boolean,default:true},auditOnly:{type:Boolean,default:false}}),emit=defineEmits(['cleared','reload-requested']);
const {proof,busy,error,closed,sessionAllowed,authorized,close,requestReload,source,candidates,records,visibleRecords,original,originalOpen,recordPage,selectOriginal,variable}=useResearchVariableFindings(props,emit);
const states={queued:'排队中',running:'执行中',succeeded:'草稿已接收，未审核',failed:'任务失败',cancelled:'已取消'},shown=v=>v===null?'未知':String(v);
const classes={value_quote_candidate:'原值引文候选',not_measured_quote_candidate:'未测陈述候选（未核实）',not_applicable_quote_candidate:'不适用陈述候选（未核实）',conflict_quote_candidate:'冲突陈述候选（未核实）'},kinds={verbatim_text:'原文',original_integer:'原整数字面值',original_calendar_date:'原日历日期',original_naive_clock:'原无时区钟点'};
</script>
<style scoped>
.research-variable-findings{display:grid;gap:12px}article{border:1px solid var(--el-border-color);padding:12px}pre{white-space:pre-wrap;overflow-wrap:anywhere;max-height:360px;overflow:auto}dl{display:grid;grid-template-columns:120px 1fr;gap:8px}dd{margin:0;overflow-wrap:anywhere}h4{margin:0 0 8px}
</style>
