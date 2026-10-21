<template>
 <section aria-label="有限科研队列待核问题任务">
  <el-alert title="固定患者集合与纳排AST只产生原记录三值结果；模型只提出部分待核问题，不执行SQL、不扩大队列、不自动入组或导出。" type="info" :closable="false" />
  <p v-if="!authorized" role="status">当前会话、角色或科研来源引用不能使用本任务。</p>
  <template v-else>
   <ResearchCohortSourceInput :active="active" :initial-references="initialReferences" @selection="select" @availability="availability" @invalidate="clear" />
   <el-input v-model="v.question" type="textarea" aria-label="本次科研待核原问题" placeholder="可留空；最多2000码点/8000 UTF8字节" />
   <p v-if="v.selected&&!v.canRequestModel" role="status">本地来源有效不代表允许模型处理；本项目尚未明确允许外部模型处理，本界面不会提交模型任务。</p>
   <el-button :disabled="v.busy||!v.selected" @click="preview">预览本次模型来源与原问题</el-button>
   <el-button :disabled="v.busy||v.audit||!v.canRequestModel" @click="generate">提交科研待核问题任务</el-button>
   <el-button @click="v.historyOpen=!v.historyOpen">{{ v.historyOpen?'关闭科研任务目录':'打开科研任务目录' }}</el-button>
   <el-checkbox v-if="role==='super_admin'" v-model="v.audit">显式技术审计读取（仍须当前项目逐患者权限）</el-checkbox>
   <ResearchCohortTasks v-if="v.historyOpen" :active="active" :audit-only="v.audit" @open="openRun" @invalidate="closed" />
   <article v-if="v.run" aria-label="科研任务技术状态"><p>任务 {{ v.run.run_id }}；{{ status[v.run.status] }}。</p><p>实际输入用量：{{ v.run.usage.input_tokens??'未知' }}；实际输出用量：{{ v.run.usage.output_tokens??'未知' }}；模型调用：{{ v.run.usage.model_call_attempted===null?'不确定':v.run.usage.model_call_attempted?'已尝试':'未尝试' }}。</p><p v-if="v.run.cancellation_pending">停止请求已记录，原在途调用的实际回执尚未确定；未把未知用量填为零。</p><p v-if="!v.run.clinical_parts_available">当前仅有技术元数据和不透明哈希，不能恢复临床引文、原Task或完整结果。</p><el-button v-if="v.run.clinical_parts_available" :disabled="v.busy" @click="openParts">明确读取并核对完整任务分件</el-button><el-button v-if="['queued','running'].includes(v.run.status)" :disabled="v.busy" @click="cancel">停止接收本次任务</el-button><el-button :disabled="v.busy" @click="openRun(v.run.run_id)">刷新本次任务状态</el-button></article>
  </template>
  <p v-if="v.error" role="alert">{{ v.error }}</p>
  <el-dialog :model-value="v.previewOpen" title="本次公开模型来源与原问题预览" width="90%" :close-on-click-modal="false" @update:model-value="value=>!value&&closePreview()"><template v-if="v.preview"><p>这是当前授权公开来源和本次原问题；完整固定System、实际Task版本及请求预算仍在服务端外发前核对。</p><pre aria-label="本次公开科研来源">{{ JSON.stringify(v.preview,null,2) }}</pre></template></el-dialog>
  <el-dialog :model-value="v.viewOpen" title="科研任务独立完整分件" width="90%" :close-on-click-modal="false" @update:model-value="value=>!value&&closed()"><ResearchCohortFindings v-if="v.parts" :metadata="v.run" :parts="v.parts" :audit-only="v.audit" :active="active&&v.viewOpen" @invalidate="closed" /></el-dialog>
 </section>
</template>
<script setup>
import ResearchCohortSourceInput from './ResearchCohortSourceInput.vue';
import ResearchCohortFindings from './ResearchCohortFindings.vue';
import ResearchCohortTasks from './ResearchCohortTasks.vue';
import {useResearchCohortAssistant} from './useResearchCohortAssistant';
const props=defineProps({initialReferences:{type:Object,default:null},active:{type:Boolean,default:true}}),emit=defineEmits(['run-change','invalidate']);
const {v,authorized,role,select,availability,clear,preview,closePreview,generate,openRun,openParts,closed,cancel}=useResearchCohortAssistant(props,emit),status={queued:'排队中',running:'处理中',succeeded:'待核问题已保存',failed:'任务未完成',cancelled:'已停止接收'};
defineExpose({clear,openRun});
</script>
<style scoped>section{min-width:0}pre{white-space:pre-wrap;overflow-wrap:anywhere;max-height:60vh;overflow:auto}.el-input{margin:12px 0}[role=alert]{color:#b42318}</style>
