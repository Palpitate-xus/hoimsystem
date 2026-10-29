<template>
 <section aria-label="合成教学练习与AI反馈">
  <h3>合成教学练习</h3>
  <p>选择课程、完成练习，提交后查看解析；需要进一步理解时，可选择目标获取 AI 讲解。请勿填写真实患者资料。</p>
  <p v-if="!authorized" role="alert">当前会话或明确提交引用无效。</p>
  <template v-else>
   <ClinicalTrainingPractice :key="v.practiceKey" :active="active" :config-revision="configRevision" @select="practiceSelection"/>
   <el-button v-if="initialReferences" :disabled="v.busy" @click="select(initialReferences)">核对传入的本人实际提交</el-button>
   <section aria-label="本次练习AI讲解">
    <h3>AI 讲解</h3>
    <p v-if="v.configBusy" role="status">正在检查 AI 讲解是否可用…</p>
    <p v-else-if="v.configError" role="status">{{v.configError}}</p>
    <p v-else-if="!v.feature">尚未取得讲解配置；本地练习仍可使用。</p>
    <p v-else-if="!configured||!v.feature.enabled||!v.feature.provider_configured||v.feature.validation_status!=='validated'">AI 讲解暂不可用；你仍可完成练习并查看课程解析。</p>
    <p v-else>AI 讲解已就绪。请先提交练习，再选择讲解目标。</p>
    <el-button :disabled="v.busy||v.configBusy" @click="configuration">重新检查讲解可用性</el-button>
    <details v-if="v.feature"><summary>讲解配置详情</summary><p>当前模型配置：{{v.feature.enabled?'已启用':'未启用'}}；教学反馈范围验证：{{v.feature.validation_status}}。提交时仍由服务端重新核对独立模型许可。</p></details>
    <p v-if="v.selected">已核对本人实际提交：{{v.selected.clinical_training_submission_id}}</p>
    <label>本次明确教学目标<el-select v-model="v.objective" :disabled="v.busy" aria-label="本次明确教学目标"><el-option v-for="(label,key) in objectives" :key="key" :value="key" :label="label"/></el-select></label>
    <el-button :disabled="!ready||v.busy" @click="generate(false)">获取 AI 讲解</el-button>
    <el-button v-if="session.role.value==='super_admin'" :disabled="!configured||!v.selected||!v.objective||v.busy" @click="generate(true)">预览讲解任务</el-button>
    <el-button :disabled="v.busy" @click="history()">查看讲解记录</el-button>
    <p v-if="v.error" role="alert">{{v.error}}</p>
    <table v-if="v.history"><tbody><tr v-for="row in v.history.items" :key="row.run_id"><td>{{row.run_id}} {{states[row.status]||'状态待核对'}}</td><td><el-button :disabled="v.busy" @click="openRun(row.run_id)">查看本次讲解</el-button></td></tr></tbody></table>
    <template v-if="v.run"><p aria-label="教学任务当前短状态">任务{{v.run.run_id}}：{{states[v.run.status]||'状态待核对'}}；{{v.run.receipt_pending?'尚待原在途调用真实回执':v.run.usage?'已有实际独立用量回执':'尚无用量回执'}}。</p><el-button :disabled="v.busy||v.run.parts_state!=='available'" @click="openParts">查看讲解反馈</el-button><el-button v-if="session.role.value==='super_admin'&&['queued','running'].includes(v.run.status)" :disabled="v.busy" @click="cancel">停止本次任务</el-button><p v-if="v.run.binding===null">当前只能查看任务状态；无权读取的练习或反馈不会恢复显示。</p></template>
    <template v-if="failure"><p role="alert">{{failure.message}}</p><details v-if="failure.details"><summary>技术详情</summary><code>{{failure.details}}</code></details><el-button :disabled="v.busy" @click="openRun(v.run.run_id)">重新查询任务</el-button></template>
    <template v-if="v.partsOpen&&v.parts">
     <el-button @click="closeParts">关闭当前反馈</el-button>
     <ClinicalTrainingFindings :metadata="v.run" :parts="v.parts" :active="active" :config-revision="configRevision" @invalidate="clear()"/>
     <template v-if="v.run.status==='succeeded'"><label>人工复核结论<el-select v-model="v.feedbackOutcome" aria-label="人工复核结论"><el-option value="accepted" label="接受教学说明"/><el-option value="rejected" label="不接受教学说明"/><el-option value="modified" label="需人工修改"/></el-select></label><label>本次复核备注<el-input v-model="v.feedbackComment" type="textarea" aria-label="本次复核备注"/></label><el-button :disabled="v.busy||!v.feedbackOutcome" @click="feedback">记录教学说明人工复核</el-button><p v-if="v.feedbackAck" role="status">复核已记录；原练习计数未改变。</p><details v-if="v.feedbackAck"><summary>复核记录标识</summary><p>{{v.feedbackAck.feedback_id}}</p></details></template>
    </template>
   </section>
  </template>
 </section>
</template>
<script setup>
import{computed}from'vue';import{aiError}from'@/utils/aiError.cjs';
const states={queued:'排队中',running:'生成中',succeeded:'讲解已生成',failed:'生成失败',cancelled:'已取消'};
import ClinicalTrainingPractice from'./ClinicalTrainingPractice.vue';import ClinicalTrainingFindings from'./ClinicalTrainingFindings.vue';import{useClinicalTrainingAssistant}from'./useClinicalTrainingAssistant';import{trainingTaskObjectives as objectives}from'@/api/ai/clinicalTrainingTasks';
const props=defineProps({active:{type:Boolean,default:true},initialReferences:{type:Object,default:null},initialObjective:{type:String,default:''},configRevision:{type:[String,Number],default:null}}),emit=defineEmits(['selection','run-change','invalidate']);const{v,session,authorized,configured,ready,configuration,select,practiceSelection,generate,history,openRun,openParts,closeParts,cancel,feedback,clear}=useClinicalTrainingAssistant(props,emit);const failure=computed(()=>v.run?.status==='failed'?aiError(v.run,'AI讲解未能生成，请核对任务记录或联系管理员。'):null);defineExpose({openRun,clear});
</script><style scoped>section{display:grid;gap:12px}table{width:100%}label{display:grid;gap:8px}</style>
