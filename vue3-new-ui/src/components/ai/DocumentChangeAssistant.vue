<template>
  <section class="document-change-assistant" aria-label="双原文核对问题任务">
    <el-alert v-if="!mode" title="请恢复第72项双原文核对模式；此面板不会降级为通用问答。" type="warning" :closable="false" />
    <el-alert v-else-if="!scopeValid || !initialValid" title="有限范围输入无效：不接受患者、就诊或其它业务字段。" type="error" :closable="false" />
    <el-alert v-else-if="!superUser" title="仅当前超级管理员可以使用完整双原文核对" type="warning" :closable="false" />
    <el-alert v-if="error" :title="error" type="error" :closable="false" />
    <el-button v-if="closed && mode && superUser && scopeValid && initialValid" @click="reopen">重新打开双原文核对</el-button>
    <template v-if="active">
      <el-button @click="close">关闭并清除双原文任务</el-button>
      <document-change-input :key="inputKey" :active="active" :initial-references="initialReferences" @selection-change="selected" />
      <el-form label-position="top"><el-form-item label="可选核对问题（原样保留）"><el-input v-model="question" type="textarea" aria-label="双原文可选问题" /></el-form-item><el-checkbox v-model="preview">明确以超级管理员试运行</el-checkbox></el-form>
      <p v-if="!feature?.enabled || feature?.validation_status !== 'validated'">功能尚未启用或验证尚未完成，超级管理员可勾选试运行。</p>
      <el-alert v-if="message" :title="message" type="info" :closable="false" />
      <div><el-button :disabled="!canGenerate || busy" @click="inspect">预览双原文与有限范围</el-button><el-button type="primary" :disabled="!canGenerate || busy" :loading="busy" @click="submit">生成未核实核对问题</el-button><el-button :disabled="!selection || busy" @click="loadHistory">读取此范围任务历史</el-button></div>
      <ul v-if="history.length" aria-label="有限范围任务历史"><li v-for="row in history" :key="row.run_id"><el-button :disabled="busy" @click="openRun(row.run_id)">打开原任务 {{ row.run_id }}</el-button> {{ states[row.status] }}</li></ul>
      <template v-if="bundle">
        <p>原任务冻结问题：{{ bundle.trace.frozen_request.payload.input.question ?? '未填写' }}</p>
        <el-button :disabled="busy" @click="refresh">重新核对当前任务</el-button><el-button v-if="['queued','running'].includes(bundle.run.status)" :disabled="busy" @click="cancel">明确取消结果接收</el-button>
        <document-change-findings :bundle="bundle" :live-scope="liveScope" :audit-only="false" :active="active" @cleared="clearResult" />
        <el-form v-if="bundle.run.status === 'succeeded'" label-position="top"><el-form-item label="明确人工反馈"><el-select v-model="feedbackOutcome" aria-label="双原文反馈结论"><el-option label="接受问题供进一步核实" value="accepted" /><el-option label="需要修改" value="modified" /><el-option label="拒绝问题草稿" value="rejected" /></el-select><el-input v-model="feedbackComment" type="textarea" aria-label="双原文反馈说明" /></el-form-item><el-button :disabled="busy" @click="feedback">明确保存人工反馈</el-button></el-form>
      </template>
    </template>
    <el-dialog v-model="previewOpen" title="完整双原文核对预览" width="780px" :before-close="closePreview" destroy-on-close>
      <template v-if="previewData && active"><p>本次问题：{{ previewData.question }}</p><p>只有完整公开双原文投影与该问题发送给模型；私有目标原件保留院内。</p><details><summary>请求容量详情</summary><p>完整提供方报文包括 Prompt 与协议头，提交前仍需服务器容量检查。</p></details><el-button @click="evidenceOpen = !evidenceOpen">{{ evidenceOpen ? '收起双原文证据' : '展开完整双原文证据' }}</el-button><section v-if="evidenceOpen"><div v-for="side in ['baseline','candidate']" :key="side"><strong>{{ side === 'baseline' ? '基准原文' : '候选原文' }}</strong><pre>{{ previewData.source[side].text }}</pre></div></section><p v-for="item in previewData.evidence" :key="item.source_id">引用：{{ item.source_id }}</p></template><p v-else>尚未完成原件核对。</p>
    </el-dialog>
  </section>
</template>
<script setup>
import DocumentChangeInput from './DocumentChangeInput.vue';
import DocumentChangeFindings from './DocumentChangeFindings.vue';
import {useDocumentChangeAssistant} from './useDocumentChangeAssistant';
import {documentChangeRunStates as states} from '@/api/ai/documentChangeResults';
const props=defineProps({feature:{type:Object,default:null},featureKey:{type:String,required:true},initialInput:{type:Object,default:()=>({})},patientId:{type:Number,default:null},encounterRef:{type:String,default:''},active:{type:Boolean,default:true}});
const {superUser,mode,scopeValid,initialValid,active,closed,inputKey,initialReferences,selection,question,preview,canGenerate,bundle,liveScope,history,busy,error,message,previewOpen,previewData,evidenceOpen,feedbackOutcome,feedbackComment,selected,inspect,submit,refresh,loadHistory,openRun,cancel,feedback,close,reopen,closePreview,clearResult}=useDocumentChangeAssistant(props);
</script>
<style scoped>
.document-change-assistant{display:grid;gap:12px}pre{white-space:pre-wrap;overflow-wrap:anywhere;max-height:400px;overflow:auto}li,p{line-height:1.7}
</style>
