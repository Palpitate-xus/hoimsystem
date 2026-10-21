<template>
 <section aria-label="完整评价证据分析任务">
  <p v-if="!mode" role="alert">请由超级管理员配置完整评价证据分析模式。</p><p v-else-if="!scopeValid||!initialValid" role="alert">本入口只接受明确评价原件和可选问题，不能混入患者、就诊或其他来源。</p><p v-else-if="!userAllowed" role="alert">当前身份不能使用本次评价证据。</p><p v-if="error" role="alert">{{error}}</p>
  <el-button v-if="closed&&mode&&scopeValid&&initialValid&&userAllowed" @click="reopen">重新打开评价证据分析</el-button>
  <template v-if="active">
   <p>完整原评分由服务器精确统计；模型只提出部分人工摘录主题，含义和后续处理需人工核实。</p><el-button @click="close">关闭并清除评价任务</el-button>
   <satisfaction-input :key="inputKey" :initial-references="initialReferences" :active="active" @selection="selected" @invalidate="unavailable" />
   <el-form label-position="top"><el-form-item label="可选待核对问题（保留原字）"><el-input v-model="question" type="textarea" aria-label="评价分析可选问题" placeholder="明确本次待人工核查的问题" /></el-form-item><el-checkbox v-if="superUser" v-model="preview">明确以Super试运行本次评价分析</el-checkbox></el-form>
   <p v-if="!feature?.enabled||feature?.validation_status!=='validated'">当前配置未启用或尚未完成运营验证，超级管理员可明确试运行。</p>
   <el-button :disabled="!canGenerate||busy" @click="inspect">预览完整安全评价资料</el-button><el-button type="primary" :disabled="!canGenerate||busy" :loading="busy" @click="submit">提交评价主题核查任务</el-button><el-button :disabled="!selection||busy" @click="loadHistory">读取本件原件最近任务</el-button>
   <p v-if="message" role="status">{{message}}</p><ul v-if="history.length" aria-label="本件评价原件最近任务"><li v-for="row in history" :key="row.run_id"><el-button :disabled="busy" @click="openRun(row)">打开原评价任务 {{row.run_id}}</el-button> {{statuses[row.status]}}</li></ul>
   <template v-if="run"><p>当前状态：{{statuses[run.status]}}</p><p aria-label="评价任务实际用量">输入token：{{run.usage.input_tokens??'未报告'}}；输出token：{{run.usage.output_tokens??'未报告'}}；{{run.usage.model_call_attempted===true?'已尝试调用':run.usage.model_call_attempted===false?'明确未调用':'调用状态未知'}}。</p><p v-if="run.error_message" role="alert">{{run.error_message}}</p>
    <el-button :disabled="busy" @click="refresh">重新核对当前评价任务</el-button><el-button v-if="['queued','running'].includes(run.status)" :disabled="busy" @click="cancel">明确取消本次评价结果接收</el-button>
    <satisfaction-findings :packet="run.satisfaction_findings" :result="run.result" :references="references" :active="active" @invalidate="clearDerived" />
    <el-form v-if="run.status==='succeeded'" label-position="top"><el-form-item label="明确提交人工反馈"><el-select v-model="feedbackOutcome" aria-label="评价主题反馈结论"><el-option value="accepted" label="接受供后续人工核查"/><el-option value="rejected" label="拒绝模型主题"/><el-option value="modified" label="需要修改"/></el-select><el-input v-model="feedbackComment" type="textarea" aria-label="评价主题反馈说明"/></el-form-item><el-button :disabled="busy" @click="feedback">明确保存本次评价人工反馈</el-button></el-form>
   </template>
  </template>
  <el-dialog :model-value="previewOpen" title="本次完整安全评价资料" :before-close="closePreview" @update:model-value="value=>{if(!value)closePreview();}" destroy-on-close><satisfaction-findings v-if="previewData&&active" :packet="previewData.context" :references="references" :active="active&&previewOpen" @invalidate="closePreview" /><template #footer><el-button @click="closePreview">关闭本次安全资料预览</el-button></template></el-dialog>
 </section>
</template>
<script setup>
import SatisfactionInput from './SatisfactionInput.vue';
import SatisfactionFindings from './SatisfactionFindings.vue';
import {useSatisfactionAssistant} from './useSatisfactionAssistant';
const props=defineProps({feature:{type:Object,default:null},featureKey:{type:String,required:true},initialInput:{type:Object,default:()=>({})},patientId:{type:Number,default:null},encounterRef:{type:String,default:''},active:{type:Boolean,default:true}}),emit=defineEmits(['run-change','availability']);
const{mode,scopeValid,initialValid,userAllowed,superUser,active,closed,inputKey,selection,initialReferences,references,question,preview,previewOpen,previewData,run,history,busy,error,message,feedbackOutcome,feedbackComment,canGenerate,selected,unavailable,closePreview,inspect,submit,refresh,loadHistory,openRun,cancel,feedback,clearDerived,close,reopen}=useSatisfactionAssistant(props,emit);
const statuses={queued:'排队中',running:'生成中',succeeded:'已接收部分待核查主题',failed:'失败',cancelled:'已取消接收'};
</script>
<style scoped>p{line-height:1.7;overflow-wrap:anywhere}.el-button{margin:6px}li{margin:8px 0}.el-select{min-width:240px}</style>
