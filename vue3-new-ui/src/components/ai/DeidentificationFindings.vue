<template>
 <section aria-label="脱敏候选任务结果" class="deidentification-findings">
  <p>仅对所选完整字段提出部分逐字候选；不保证检出全部标识或匿名，不创建人工复核、发布或导出。</p>
  <p v-if="!v.allowed" role="status">当前身份或会话不可读取，旧正文已清除。超级管理员也需要当前项目和逐患者用途授权。</p>
  <template v-else>
   <el-button :disabled="v.busy" @click="v.inspect">核对本次拆分任务</el-button>
   <el-button @click="v.inspectTechnical">仅查看安全技术状态与用量</el-button>
   <el-button @click="v.close">关闭并清除脱敏任务结果</el-button>
   <p v-if="v.busy" role="status">正在核对原HTTP字节、完整所选来源与逐字候选…</p>
   <p v-if="v.error" role="alert">{{ v.error }}</p>
   <template v-if="v.usage">
    <p aria-label="脱敏任务实际用量">输入：{{ shown(v.usage.input_tokens) }}；输出：{{ shown(v.usage.output_tokens) }}；{{ v.usage.complete?'两项用量均已返回':'用量尚不完整' }}；{{ v.usage.model_call_attempted===null?'是否实际调用未知':v.usage.model_call_attempted?'已有实际调用回执':'已确认未调用模型' }}。</p>
   </template>
   <template v-if="v.safe">
    <p aria-label="安全技术读取范围">仅技术状态 {{ states[v.safe.status] }}、付费用量和不透明SHA；未读取临床正文、候选引文或原始任务JSON。技术状态不恢复研究或导出资格。</p>
    <pre aria-label="安全技术不透明锚">{{ JSON.stringify(v.safe.opaque_hashes,null,2) }}</pre>
   </template>
   <template v-if="v.proof">
    <p aria-label="脱敏任务状态">{{ states[v.run.status] }}；无自动遮蔽、复核、发布或下载。</p>
    <p aria-label="脱敏结果核验范围">已核对当前授权响应中的完整所选来源、原始来源Artifact UTF8字节SHA、公开投影、任务绑定和逐字候选。{{ v.proof.traceVerified?'已另外按原始三项JSON字符串核对任务、证据及元数据SHA。':'原始三项任务JSON未提供，其SHA仅为服务端锚，未声称浏览器重建原字节。' }} 用量为服务端具体审计回执，不是浏览器独立查询数据库审计。</p>
    <p>所选字段 {{ v.source.documents.length }} 件；未选正文和姓名字典未读取。{{ auditOnly?'当前超级管理员审计也经过项目与逐患者用途核验；不能恢复撤回的权限。':'' }}</p>
    <template v-if="v.result">
     <p aria-label="脱敏部分候选摘要">模型仅返回 {{ v.result.candidate_count }} 条部分候选；{{ v.result.candidate_count===0?'零候选不表示没有标识风险。':'须由人工逐条选择后另行建立复核。' }}</p>
     <el-table v-if="v.candidates.length" :data="v.visibleCandidates" aria-label="脱敏部分逐字候选">
      <el-table-column label="类别（未审核）"><template #default="{row}">{{ categories[row.category] }}</template></el-table-column>
      <el-table-column label="Unicode码点区间"><template #default="{row}">[{{ row.start }}, {{ row.end }})</template></el-table-column>
      <el-table-column prop="review_note" label="模型待核对说明"/>
      <el-table-column label="逐字定位"><template #default="{row}"><el-button @click="v.inspectQuote(row)">展开第{{ row.ordinal+1 }}条原文候选</el-button></template></el-table-column>
     </el-table>
     <el-pagination v-if="v.candidates.length>10" v-model:current-page="v.page" :page-size="10" :total="v.candidates.length" layout="prev,pager,next" aria-label="脱敏候选分页"/>
    </template>
    <p v-else>此状态没有已接收模型候选；未知用量不会填零。</p>
    <el-button @click="v.originalOpen=!v.originalOpen">{{ v.originalOpen?'收起完整所选原文':'显式展开完整所选原文' }}</el-button>
    <el-button @click="v.privateOpen=!v.privateOpen">{{ v.privateOpen?'收起私有来源原件':'显式展开私有来源原件' }}</el-button>
    <div v-if="v.originalOpen"><article v-for="d in v.source.documents" :key="d.source_id"><p>{{ d.field }}：{{ d.text===null?'NULL（未记录）':d.text===''?'已记录空串':d.utf8_bytes+' UTF8字节 / '+d.codepoint_length+'码点' }}</p><pre v-if="d.text!==null" aria-label="任务完整所选字段">{{ d.text }}</pre></article></div>
    <pre v-if="v.privateOpen" aria-label="任务私有来源原件">{{ JSON.stringify(v.proof.body.source_snapshot,null,2) }}</pre>
   </template>
  </template>
  <el-dialog :model-value="v.allowed&&v.quote!==null" title="待人工核对的逐字候选" append-to-body destroy-on-close @update:model-value="open=>{if(!open)v.quote=null}">
   <template v-if="v.quote"><p>Unicode码点 [{{ v.quote.start }}, {{ v.quote.end }})；仅定位本次所选字段。</p><pre aria-label="脱敏候选原文引文">{{ v.quote.quote }}</pre><p>{{ v.quote.review_note }}</p><p>尚未创建人工编辑或独立残余风险复核。</p></template>
  </el-dialog>
 </section>
</template>
<script setup>
import{reactive}from'vue';import{useDeidentificationFindings}from'./useDeidentificationFindings';import{deidentificationCandidateCategories as categories}from'@/api/ai/deidentificationResults';
const props=defineProps({run:{type:Object,default:null},sourcePart:{type:Object,default:null},technical:{type:Object,default:null},resultPart:{type:Object,default:null},trace:{type:Object,default:null},scope:{type:Object,default:null},patientId:{type:Number,default:null},references:{type:Object,default:null},expectedRunId:{type:String,default:null},auditOnly:{type:Boolean,default:false},configRevision:{type:[Number,String],default:null},active:{type:Boolean,default:true}}),emit=defineEmits(['invalidate','inspect']),v=reactive(useDeidentificationFindings(props,emit));
const states={queued:'排队中',running:'执行中',succeeded:'部分候选已接收，未审核',failed:'任务失败',cancelled:'任务已取消'},shown=v=>v===null?'未知':String(v);
</script>
<style scoped>.deidentification-findings{display:grid;gap:12px}pre{white-space:pre-wrap;overflow-wrap:anywhere;max-height:360px;overflow:auto}</style>
