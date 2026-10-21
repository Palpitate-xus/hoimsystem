<template>
 <section aria-label="完整住院账目核对任务">
  <p v-if="!mode" role="alert">此入口仅处理完整账目核对模式，不退回旧截断账目或通用任务。</p><p v-else-if="!scopeValid||!initialValid" role="alert">真实患者、本次住院或明确账目引用无效，不接受外域业务字段。</p><p v-else-if="!userAllowed" role="alert">当前身份不能使用本次完整账目核对。</p><p v-if="error" role="alert">{{error}}</p>
  <el-button v-if="closed&&mode&&scopeValid&&initialValid&&userAllowed" @click="reopen">重新打开完整账目核对</el-button>
  <template v-if="active">
   <p>仅提出部分待人工核实的原记录问题；不确认漏费、重复收费、应收应退或资金流动，不自动新增收费项目、修改数量金额或退款。</p><el-button @click="close">关闭并清除完整账目任务</el-button>
   <charge-reconciliation-input :key="inputKey" :patient-id="patientId" :admission-id="encounterRef" :initial-references="initialReferences" :active="active" @selection="selected" @invalidate="unavailable"/>
   <el-form label-position="top"><el-form-item label="可选待核对问题（保留原字）"><el-input v-model="question" type="textarea" aria-label="完整账目可选问题" placeholder="明确本次待人工核对范围，不授权任何收费或退款动作"/></el-form-item><el-checkbox v-if="superUser" v-model="preview">明确以Super试运行本次核对</el-checkbox></el-form>
   <p v-if="!feature?.enabled||feature?.validation_status!=='validated'">当前配置未启用或尚未完成运营验证；只有Super明确试运行可提交，不代表财务结论获确认。</p>
   <el-button :disabled="!canGenerate||busy" @click="inspect">预览完整账目资料</el-button><el-button type="primary" :disabled="!canGenerate||busy" :loading="busy" @click="submit">提交待人工核对任务</el-button><el-button :disabled="busy" @click="loadHistory">读取本次住院最近任务</el-button>
   <p v-if="message" role="status">{{message}}</p><ul v-if="history.length" aria-label="本次住院最近账目任务"><li v-for="row in history" :key="row.run_id"><el-button :disabled="busy" @click="openRun(row)">打开原账目任务 {{row.run_id}}</el-button> {{statuses[row.status]}}</li></ul>
   <template v-if="run"><p aria-label="本次任务冻结问题">原任务问题：{{run.charge_findings.input.question??'未填写'}}。</p><el-button :disabled="busy" @click="refresh">重新核对当前账目任务</el-button><el-button v-if="['queued','running'].includes(run.status)" :disabled="busy" @click="cancel">明确取消本次结果接收</el-button>
    <charge-reconciliation-findings :run="run" :expected-patient-id="patientId" :expected-admission-id="encounterRef" :expected-run-id="run.run_id" :references="viewReferences" :active="active" @inspect="inspectEvidence" @invalidate="clearDerived"/>
    <el-form v-if="run.status==='succeeded'" label-position="top"><el-form-item label="明确提交人工反馈"><el-select v-model="feedbackOutcome" aria-label="账目核对反馈结论"><el-option value="accepted" label="接受供后续人工复核"/><el-option value="rejected" label="拒绝模型问题"/><el-option value="modified" label="需要修改"/></el-select><el-input v-model="feedbackComment" type="textarea" aria-label="账目核对反馈说明"/></el-form-item><el-button :disabled="busy" @click="feedback">明确保存本次人工反馈</el-button></el-form>
   </template>
  </template>
  <el-dialog :model-value="previewOpen" title="本次完整账目资料预览" :before-close="closePreview" @update:model-value="value=>{if(!value)closePreview();}" destroy-on-close>
   <template v-if="previewData&&active"><p>仅本次真实住院的完整已记账目；不能据此证明现金收退或收费资格。</p><charge-reconciliation-findings :context="previewData" :expected-patient-id="patientId" :expected-admission-id="encounterRef" :references="{charge_case_id:previewData.context.charge_case.case_snapshot_id}" :active="active&&previewOpen" @inspect="inspectEvidence"/><el-button @click="closePreview">关闭本次资料预览</el-button></template><p v-else>正在核对完整原件，尚未展示账目资料。</p>
  </el-dialog>
 </section>
</template>
<script setup>
import ChargeReconciliationInput from'./ChargeReconciliationInput.vue';
import ChargeReconciliationFindings from'./ChargeReconciliationFindings.vue';
import{useChargeReconciliationAssistant}from'./useChargeReconciliationAssistant';
const props=defineProps({feature:{type:Object,default:null},featureKey:{type:String,required:true},initialInput:{type:Object,default:()=>({})},patientId:{type:Number,default:null},encounterRef:{type:String,default:''},active:{type:Boolean,default:true}}),emit=defineEmits(['run-change','availability','inspect']);
const{mode,userAllowed,superUser,scopeValid,initialValid,initialReferences,active,closed,inputKey,selection,question,preview,previewOpen,previewData,run,viewReferences,history,busy,error,message,feedbackOutcome,feedbackComment,canGenerate,selected,unavailable,closePreview,inspect,submit,refresh,loadHistory,openRun,cancel,feedback,inspectEvidence,clearDerived,close,reopen}=useChargeReconciliationAssistant(props,emit);
const statuses={queued:'排队中',running:'生成中',succeeded:'已接收部分待核实问题',failed:'失败',cancelled:'已取消接收'};
</script>
<style scoped>p{line-height:1.7;overflow-wrap:anywhere}.el-button{margin:6px}li{margin:8px 0}.el-select{min-width:240px}</style>
