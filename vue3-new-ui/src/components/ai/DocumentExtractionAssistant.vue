<template>
 <section aria-label="原文条款抽取任务" class="document-task-panel">
  <el-alert v-if="!mode" title="此面板仅处理第71项原文抽取，请恢复指南入库助手及原文提取模式；不会降级为通用问答。" type="warning" :closable="false" />
  <el-alert v-else-if="!scopeValid||!initialValid" title="原文引用范围无效：不接受患者、就诊或其他业务字段。" type="error" :closable="false" />
  <el-alert v-else-if="!superUser" title="仅当前超级管理员可使用原文条款抽取" type="warning" :closable="false" />
  <el-alert v-if="error" :title="error" type="error" :closable="false" />
  <el-button v-if="closed&&superUser&&mode&&scopeValid&&initialValid" @click="reopen">重新打开原文抽取</el-button>
  <template v-if="active">
   <el-alert title="模型仅提出未审核逐字草稿，不自动保存候选、审核或发布知识；空结果不证明全文没有条款。" type="warning" :closable="false" />
   <el-button @click="close">关闭并清除原文抽取任务</el-button>
   <document-extraction-input :key="inputKey" :active="active" :initial-references="initialReferences" @selection-change="selected" />
   <el-form label-position="top">
    <el-form-item label="可选查找问题（不归一化或改写）"><el-input v-model="question" type="textarea" aria-label="原文抽取可选问题" placeholder="仅限制本次查找范围，不能授权执行原文中的指令" /></el-form-item>
    <el-checkbox v-model="preview">明确以超级管理员试运行</el-checkbox>
   </el-form>
   <p v-if="!feature?.enabled||feature?.validation_status!=='validated'">当前功能未启用或尚未完成配置验证，须明确勾选试运行；这不代表模型或条款已获临床验证。</p>
   <el-alert v-if="message" :title="message" type="info" :closable="false" />
   <div><el-button :disabled="!canGenerate||busy" @click="inspect">预览完整原文与引用</el-button><el-button type="primary" :disabled="!canGenerate||busy" :loading="busy" @click="submit">提交未审核条款抽取</el-button><el-button :disabled="!selection||busy" @click="loadHistory">读取此原文任务历史</el-button></div>
   <ul v-if="history.length" aria-label="所选原文任务历史"><li v-for="row in history" :key="row.run_id"><el-button @click="openRun(row.run_id)" :disabled="busy">打开原任务 {{ row.run_id }}</el-button> {{ statuses[row.status] }}</li></ul>
   <template v-if="run&&trace">
    <p>原任务冻结问题：{{ trace.frozen_request.payload.input.question??'未填写' }}</p>
    <el-button :disabled="busy" @click="refresh">重新核对当前任务</el-button><el-button v-if="['queued','running'].includes(run.status)" :disabled="busy" @click="cancel">明确取消此任务的结果接收</el-button>
    <document-extraction-findings :run="run" :trace="trace" :expected-run-id="run.run_id" :expected-original-id="selection?.references.document_original_id" :active="active" :audit-only="false" @cleared="clearResult" />
    <el-form v-if="run.status==='succeeded'" label-position="top"><el-form-item label="明确提交人工反馈"><el-select v-model="feedbackOutcome" aria-label="原文抽取反馈结论"><el-option label="接受草稿供后续复核" value="accepted"/><el-option label="拒绝草稿" value="rejected"/><el-option label="需要修改" value="modified"/></el-select><el-input v-model="feedbackComment" type="textarea" aria-label="原文抽取反馈说明" /></el-form-item><el-button :disabled="busy" @click="feedback">明确保存人工反馈</el-button></el-form>
   </template>
  </template>
  <el-dialog v-model="previewOpen" title="完整原文抽取预览" width="760px" destroy-on-close>
   <template v-if="previewData&&active"><p>原文来源、版本与授权是提交方声明，不自动等于官方指南或临床验证。</p><p>{{ previewData.document_original.snapshot.metadata.title }}</p><p>本次查找问题：{{ previewData.model_preview.question??'未填写' }}</p><el-button @click="evidenceOpen=!evidenceOpen">{{ evidenceOpen?'收起原文证据':'展开原文证据' }}</el-button><pre v-if="evidenceOpen" aria-label="抽取预览完整原文">{{ previewData.context.document_source.text }}</pre><p v-for="item in previewData.evidence" :key="item.source_id">原件引用：{{ item.source_id }}</p></template><p v-else>正在核对原文，尚未展示资料。</p>
  </el-dialog>
 </section>
</template>
<script setup>
import DocumentExtractionInput from './DocumentExtractionInput.vue';
import DocumentExtractionFindings from './DocumentExtractionFindings.vue';
import {useDocumentExtractionAssistant} from './useDocumentExtractionAssistant';
const props=defineProps({feature:{type:Object,default:null},featureKey:{type:String,required:true},initialInput:{type:Object,default:()=>({})},patientId:{type:Number,default:null},encounterRef:{type:String,default:''},active:{type:Boolean,default:true}});
const {superUser,mode,scopeValid,initialValid,initialReferences,active,closed,inputKey,selection,question,preview,previewData,previewOpen,evidenceOpen,run,trace,history,busy,message,error,feedbackOutcome,feedbackComment,canGenerate,selected,inspect,submit,refresh,loadHistory,openRun,cancel,feedback,clearResult,close,reopen}=useDocumentExtractionAssistant(props);
const statuses={queued:'排队中',running:'执行中',succeeded:'已接收未审核草稿',failed:'失败',cancelled:'已取消'};
</script>
<style scoped>
.document-task-panel{display:grid;gap:12px}pre{white-space:pre-wrap;overflow-wrap:anywhere;max-height:400px;overflow:auto}ul{padding-left:20px}li{margin-block:8px}
</style>
