<template>
 <section aria-label="说明书逐字抽取助手" class="drug-label-assistant">
  <el-alert v-if="!v.mode" title="当前说明书提取配置不可用，请联系管理员。" type="warning" :closable="false" />
  <el-alert v-else-if="!v.scopeValid||!v.initialValid" title="说明书来源引用无效，请重新选择。" type="error" :closable="false" />
  <el-alert v-else-if="!v.sessionAllowed" title="仅当前药师或超级管理员可使用说明书逐字抽取" type="warning" :closable="false" />
  <p v-if="v.error" role="alert">{{ v.error }}</p>
  <el-button v-if="v.closed&&v.sessionAllowed&&v.mode&&v.scopeValid&&v.initialValid&&active" @click="v.reopen">重新打开说明书助手</el-button>
  <template v-if="v.active">
   <el-alert title="仅提出待药师逐项复核的逐字字段草稿；不会自动修改药品目录、发布知识或生成临床规则。" type="warning" :closable="false" />
   <el-button @click="v.close">关闭并清除说明书助手</el-button>
   <DrugLabelSourceInput :key="v.inputKey" :active="v.active" :initial-references="v.initialReferences" :pharmaceutical-id="pharmaceuticalId" @selection="v.selected" @availability="v.availability" @invalidate="v.invalidateSelection" />
   <p v-if="v.selection" aria-label="说明书本次来源已核对">已独立重读来源 {{ v.selection.references.drug_label_source_binding_id }}，目录 {{ v.selection.source.identity.pharmaceutical_id }}：{{ v.selection.source.identity.name===null?'名称未记录':v.selection.source.identity.name }}。</p>
   <el-form label-position="top"><el-form-item label="查找问题（可选）"><el-input v-model="v.question" type="textarea" aria-label="说明书抽取可选问题" /><small aria-label="补充问题长度">{{ Array.from(v.question).length }}/2000</small></el-form-item><el-checkbox v-if="v.superUser" v-model="v.preview">超级管理员试运行</el-checkbox><el-checkbox v-if="v.superUser" v-model="v.wantTrace">附带任务审计详情</el-checkbox></el-form>
   <p>请核对所提供版本的完整性与适用性；模型处理需有资料使用许可。</p>
   <div><el-button :disabled="!v.canGenerate||v.busy" @click="v.inspect">预览完整说明书来源</el-button><el-button type="primary" :disabled="!v.canGenerate||v.busy" :loading="v.busy" @click="v.submit">提交未核实说明书字段抽取</el-button><el-button :disabled="!v.selection||v.busy" @click="v.loadHistory">读取此来源任务历史</el-button></div>
   <p v-if="v.message" role="status">{{ v.message }}</p>
   <ul v-if="v.history.length" aria-label="说明书来源任务历史"><li v-for="row in v.history" :key="row.run_id"><el-button :disabled="v.busy" @click="v.openRun(row.run_id)">打开说明书原任务 {{ row.run_id }}</el-button> {{ statuses[row.status] }}；输入{{ shown(row.input_tokens) }} / 输出{{ shown(row.output_tokens) }}</li></ul>
   <template v-if="v.run||v.lastRunId">
    <p v-if="v.run" aria-label="说明书原任务冻结问题">原任务问题：{{ v.run.drug_label_findings.input.question===undefined?'未填写':v.run.drug_label_findings.input.question===null?'明确为null':v.run.drug_label_findings.input.question }}</p>
    <div><el-button :disabled="v.busy" @click="v.refresh">重新核对说明书任务</el-button><el-button v-if="v.run&&['queued','running'].includes(v.run.status)" :disabled="v.busy" @click="v.cancel">明确取消本次说明书结果接收</el-button></div>
    <DrugLabelFindings :run="v.run" :trace="v.trace" :references="v.selection?.references||null" :pharmaceutical-id="v.selection?.source.identity.pharmaceutical_id||pharmaceuticalId" :expected-run-id="v.lastRunId" :active="v.active" :audit-only="v.superUser&&v.run?.drug_label_findings?.drug_label_source_record?.audit_only===true" :config-revision="feature?.revision??null" @invalidate="v.clearResult" @reload="v.refresh" />
    <el-form v-if="v.run?.status==='succeeded'" label-position="top"><el-form-item label="明确选择人工反馈（不代替字段审核）"><el-select v-model="v.feedbackOutcome" aria-label="说明书反馈结论" placeholder="请选择"><el-option label="接受草稿供后续复核" value="accepted"/><el-option label="拒绝草稿" value="rejected"/><el-option label="需要修改" value="modified"/></el-select><el-input v-model="v.feedbackComment" type="textarea" aria-label="说明书反馈说明" /></el-form-item><el-button :disabled="v.busy||!v.feedbackOutcome" @click="v.feedback">明确保存说明书人工反馈</el-button></el-form>
   </template>
  </template>
  <el-dialog :model-value="v.previewOpen" title="完整说明书来源预览" :before-close="v.closePreview" destroy-on-close @update:model-value="open=>{if(!open)v.closePreview()}">
   <template v-if="v.previewData&&v.active"><p>本次说明书来源与签署已核对。</p><p>待提交的本地问题：{{ v.question }}</p><p>目录 {{ v.previewData.drug_label_source_record.snapshot.identity.pharmaceutical_id }}；版本 {{ v.previewData.context.drug_label_source.declared_version }}</p><el-button @click="v.previewRaw=!v.previewRaw">{{ v.previewRaw?'收起预览完整原文':'展开预览完整原文' }}</el-button><pre v-if="v.previewRaw" aria-label="说明书预览完整原文">{{ v.previewData.context.drug_label_source.text }}</pre></template><p v-else>正在核对完整来源，尚未展示正文。</p>
  </el-dialog>
 </section>
</template>
<script setup>
import {reactive} from 'vue';
import DrugLabelSourceInput from './DrugLabelSourceInput.vue';
import DrugLabelFindings from './DrugLabelFindings.vue';
import {useDrugLabelAssistant} from './useDrugLabelAssistant';
const props=defineProps({feature:{type:Object,default:null},featureKey:{type:String,required:true},initialInput:{type:Object,default:()=>({})},initialReferences:{type:Object,default:null},pharmaceuticalId:{type:Number,default:null},patientId:{type:Number,default:null},encounterRef:{type:String,default:''},active:{type:Boolean,default:true}}),v=reactive(useDrugLabelAssistant(props));
const statuses={queued:'排队中',running:'执行中',succeeded:'未核实草稿已接收',failed:'任务失败',cancelled:'任务已取消'},shown=value=>value===null?'未知':String(value);
</script>
<style scoped>
.drug-label-assistant{display:grid;gap:12px}pre{white-space:pre-wrap;overflow-wrap:anywhere;max-height:360px;overflow:auto}ul{padding-left:20px}
</style>
