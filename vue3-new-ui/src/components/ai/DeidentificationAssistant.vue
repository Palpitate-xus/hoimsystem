<template>
 <section aria-label="受控脱敏候选助手" class="deidentification-assistant">
  <p>用途 deidentification_review。临床正文出站须另有 external_model 明确许可；即使超级管理员也不能绕过项目与逐患者授权。</p>
  <p v-if="!v.mode" role="alert">本入口只允许 deidentification_evidence 独立模式；不回退到通用任务。</p>
  <p v-else-if="!v.initialValid" role="alert">来源输入含空字段、外来引用或不一致范围，已拒绝。</p>
  <p v-else-if="!v.scopeRequest" role="status">请先选择项目和患者。</p>
  <p v-else-if="!v.userAllowed" role="status">当前会话角色不可读取此用途，旧资料已清除。</p>
  <el-button v-if="v.closed" @click="v.reopen">重新打开脱敏候选助手</el-button>
  <template v-if="v.active">
   <el-button @click="v.close">关闭并清除脱敏候选助手</el-button>
   <DeidentificationInput :key="v.inputKey" :scope="scope" :patient-id="patientId" :initial-references="v.initialReferences" :active="v.active" @selection="v.selected" @availability="ok=>{if(!ok)v.unavailable()}"/>
   <p v-if="v.selection" aria-label="助手当前脱敏来源">已单独重读并绑定 {{ v.selection.case_id }}；来源选择不自动提交模型。</p>
   <el-input v-model="v.question" type="textarea" placeholder="补充问题（可选）" aria-label="脱敏候选可选问题"/>
   <el-checkbox v-if="v.superUser" v-model="v.auditOnly">明确读取当前研究授权范围内的只读审计任务</el-checkbox>
   <el-checkbox v-if="v.superUser" v-model="v.preview">明确超级管理员配置预览；仍需要研究与出站权限</el-checkbox>
   <p v-if="!v.configured" role="status">完整模型与功能配置尚未提供，不发送正文。</p>
   <div><el-button :disabled="!v.canGenerate||v.busy" @click="v.inspect">显式核对本次模型出站预览</el-button><el-button :disabled="!v.canGenerate||v.busy" @click="v.submit">明确提交部分脱敏候选任务</el-button></div>
   <p v-if="v.busy" role="status">正在按当前范围核对；不会自动重试模型调用。</p>
   <p v-if="v.error" role="alert">{{ v.error }}</p>
   <el-input :model-value="v.runId" @update:model-value="v.changeRunId" placeholder="明确既有任务UUID（不会建立新的来源选择）" aria-label="明确脱敏任务UUID"/>
   <div><el-button :disabled="v.busy||!v.runId" @click="v.refresh">显式重读既有脱敏任务</el-button><el-button :disabled="v.busy||!v.runId" @click="v.technical">显式请求安全技术用量</el-button><el-button v-if="!v.auditOnly&&v.view&&['queued','running'].includes(v.view.run.data.status)" :disabled="v.busy" @click="v.cancel">明确取消当前脱敏任务</el-button><el-button v-if="v.superUser&&v.view" :disabled="v.busy" @click="v.trace">显式读取当前授权任务原始审计</el-button></div>
   <p v-if="v.view" aria-label="助手脱敏任务状态">{{ v.view.run.data.status }}；{{ v.pending?'终态或实际用量待返回':'本次状态已核对' }}。</p>
   <DeidentificationFindings v-if="v.view||v.safeTechnical" :run="v.view?.run||null" :source-part="v.view?.sourcePart||null" :technical="v.view?.technical||v.safeTechnical" :result-part="v.view?.resultPart||null" :trace="v.view?.trace||null" :scope="scope" :patient-id="patientId" :references="v.selection?{deidentification_case_id:v.selection.case_id}:null" :expected-run-id="v.runId" :active="v.active" :config-revision="feature?.revision" :audit-only="v.auditOnly"/>
  </template>
  <el-dialog :model-value="v.active&&v.previewOpen" title="本次完整所选字段出站预览" append-to-body destroy-on-close @update:model-value="open=>{if(!open)v.closePreview()}">
   <template v-if="v.previewData"><p>完整所选字段和用途已核对；未发送模型，不会自动遮蔽或创建复核。</p><el-button @click="v.previewTextOpen=!v.previewTextOpen">{{ v.previewTextOpen?'收起本次模型所见完整字段':'显式展开本次模型所见完整字段' }}</el-button><pre v-if="v.previewTextOpen" aria-label="脱敏模型所见完整字段">{{ JSON.stringify(v.previewData.data.source.documents,null,2) }}</pre></template>
   <p v-else>正在核对本次完整来源；关闭后迟到预览不会恢复。</p>
  </el-dialog>
 </section>
</template>
<script setup>
import{reactive}from'vue';import{useDeidentificationAssistant}from'./useDeidentificationAssistant';import DeidentificationInput from'./DeidentificationInput.vue';import DeidentificationFindings from'./DeidentificationFindings.vue';
const props=defineProps({feature:{type:Object,default:null},featureKey:{type:String,default:'deidentification'},initialInput:{type:Object,default:null},initialReferences:{type:Object,default:null},scope:{type:Object,default:null},patientId:{type:Number,default:null},active:{type:Boolean,default:true}}),emit=defineEmits(['run-change','availability']),v=reactive(useDeidentificationAssistant(props,emit));
</script>
<style scoped>.deidentification-assistant{display:grid;gap:12px}pre{white-space:pre-wrap;overflow-wrap:anywhere;max-height:360px;overflow:auto}</style>
