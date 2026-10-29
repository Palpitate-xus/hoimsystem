<template>
 <section aria-label="科研队列明确来源与治理">
  <el-alert title="请按项目核对患者授权和筛选条件。" type="info" :closable="false" />
  <p v-if="!v.authorized" role="status">当前会话、角色或读取模式不满足本项条件。</p>
  <template v-else>
   <p v-if="v.project">当前明确项目：{{ v.project.scope_id }}。目录定位不授予患者读取或模型调用权限。</p>
   <el-tabs v-model="v.tab"><el-tab-pane label="明确项目" name="projects" /><el-tab-pane label="项目成员权限" name="acl" /><el-tab-pane label="逐患者研究授权" name="authorization" /><el-tab-pane label="完整病例来源" name="cases" /></el-tabs>
   <ResearchCohortRegistry v-if="v.tab==='projects'" kind="scope" :active="active" :audit-only="auditOnly" @project="v.chooseProject" @invalidate="v.registryInvalidate" @source-changed="v.registryChanged" />
   <ResearchCohortRegistry v-else-if="v.tab==='acl'||v.tab==='authorization'" :kind="v.tab" :scope-id="v.project?.scope_id??null" :active="active" :audit-only="auditOnly" @invalidate="v.registryInvalidate" @source-changed="v.registryChanged" />
   <template v-else>
    <p v-if="!v.project">请先在项目目录明确选择本项目；不会自动使用第一项。</p>
    <template v-else>
     <el-button :disabled="v.busy" @click="v.refresh(1)">刷新完整病例目录</el-button><el-button v-if="v.canCapture" :disabled="v.busy" @click="v.openCapture">明确条件并捕获完整病例来源</el-button>
     <el-table :data="v.rows" aria-label="科研病例技术目录"><el-table-column prop="case_id" label="病例来源标识" /><el-table-column label="状态"><template #default="{row}">{{ states[row.status] }}</template></el-table-column><el-table-column prop="created_at" label="捕获UTC" /><el-table-column label="操作"><template #default="{row}"><el-button :disabled="v.busy" @click="v.inspect(row)">按当前授权读取本件</el-button><el-button v-if="v.role==='super_admin'&&!auditOnly" :disabled="v.busy" @click="v.inspect(row,{technical:true})">技术治理核对</el-button></template></el-table-column></el-table>
     <el-button :disabled="v.busy||v.page<=1" @click="v.refresh(v.page-1)">上一页</el-button><span>第{{ v.page }}页，共{{ v.total }}件</span><el-button :disabled="v.busy||v.page*20>=v.total" @click="v.refresh(v.page+1)">下一页</el-button>
    </template>
   </template>
  </template>
  <p v-if="v.error" role="alert">{{ v.error }}</p><p v-if="v.notice" role="status">{{ v.notice }}</p>
  <el-dialog :model-value="v.detailOpen" title="科研病例完整来源核对" width="90%" :close-on-click-modal="false" @update:model-value="value=>!value&&v.closePrivate()">
   <template v-if="v.detail"><p>病例来源 {{ v.detail.case_id }}；状态 {{ states[v.detail.status] }}；版本 {{ v.detail.revision }}。</p><p v-if="v.detailAudit">本次为技术审计读取，不恢复模型执行资格；临床正文仍需当前项目和逐患者授权。</p>
    <template v-if="v.detail.snapshot"><p>完整来源与本地三值结果已核对；{{ v.detail.eligible?'当前来源条件满足':'当前来源条件尚未满足' }}。</p><ResearchCohortCriteriaSummary :node="v.detail.snapshot.request.criteria.root" /><el-table :data="v.detail.snapshot.evaluation.outcomes" aria-label="本地逐患者原记录条件结果"><el-table-column prop="patient_id" label="明确患者ID" /><el-table-column label="原记录条件"><template #default="{row}">{{ truth[row.truth] }}</template></el-table-column></el-table><p>结果按本次所选记录和筛选条件整理。</p><el-button @click="v.showOriginal=!v.showOriginal">{{ v.showOriginal?'收起完整原始记录':'显式展开完整原始记录' }}</el-button><ResearchCohortOriginals v-if="v.showOriginal" :capture="v.detail.snapshot.capture" /><p v-if="v.detail.public_source?.external_model_use!=='recorded_permitted'">本项目尚未记录明确外部模型处理许可；本地条件核对不授予外部模型调用权限。</p><el-button v-if="v.canSelect" :disabled="v.busy" @click="v.selectSource">明确选用当前完整病例来源</el-button></template>
    <p v-else role="status">仅有技术元数据；未读取或核对完整临床正文，不能选作模型来源。</p>
    <fieldset v-if="v.canReview||v.canRevoke" :disabled="v.writePending"><legend>本次技术治理</legend><p v-if="!v.detail.snapshot">当前只核对状态、版本和本次依据回执，不恢复患者正文。</p><el-select v-if="v.canReview" v-model="v.decision" aria-label="病例技术审核决定" placeholder="明确选择决定"><el-option value="publish" label="技术发布本件病例来源" /><el-option value="reject" label="拒绝本件病例来源" /></el-select><el-input v-model="v.basis" type="textarea" aria-label="病例技术治理完整依据" placeholder="20字以上完整依据，保留未知与否定" /><el-button v-if="v.canReview" :disabled="v.busy||!v.decision" @click="v.mutate('review')">提交病例技术审核</el-button><el-button v-if="v.canRevoke" :disabled="v.busy" @click="v.mutate('revoke')">撤销本件病例来源</el-button></fieldset><p v-if="v.formError" role="alert">{{ v.formError }}</p>
   </template>
  </el-dialog>
  <el-dialog :model-value="v.captureOpen" title="明确条件与完整来源捕获" width="90%" :close-on-click-modal="false" @update:model-value="value=>!value&&v.closePrivate()">
   <template v-if="v.captureOpen"><p>只使用本项目已明确声明和逐患者授权的记录集合；最多64个条件节点、8层。缺记录、未知日期和矛盾父关联保持未知。</p><fieldset :disabled="v.writePending"><legend>本次明确条件</legend><ResearchCohortCriteriaNode v-model="v.criteria" /><el-button :disabled="v.busy||!v.criteriaValid" @click="v.readPreview">读取完整来源并本地核对条件</el-button><template v-if="v.preview"><p role="status">完整来源及本地条件结果已核对；尚未创建病例、调用模型或导出。</p><el-table :data="v.preview.evaluation.outcomes" aria-label="本次条件预览结果"><el-table-column prop="patient_id" label="明确患者ID" /><el-table-column label="原记录条件"><template #default="{row}">{{ truth[row.truth] }}</template></el-table-column></el-table><el-input v-model="v.captureBasis" type="textarea" aria-label="本次完整捕获依据" placeholder="20字以上本次完整来源捕获依据" /><el-button :disabled="v.busy" @click="v.create">保存本次完整来源草稿</el-button></template></fieldset><p v-if="v.formError" role="alert">{{ v.formError }}</p></template>
  </el-dialog>
 </section>
</template>
<script setup>
import {reactive} from 'vue';
import ResearchCohortRegistry from './ResearchCohortRegistry.vue';
import ResearchCohortCriteriaNode from './ResearchCohortCriteriaNode.vue';
import ResearchCohortCriteriaSummary from './ResearchCohortCriteriaSummary.vue';
import ResearchCohortOriginals from './ResearchCohortOriginals.vue';
import {useResearchCohortSources} from './useResearchCohortSources';
const props=defineProps({active:{type:Boolean,default:true},auditOnly:{type:Boolean,default:false}}),emit=defineEmits(['select','invalidate','source-changed']),v=reactive(useResearchCohortSources(props,emit)),states={draft:'草稿',published:'已技术发布',rejected:'已拒绝',revoked:'已撤销'},truth={true:'原记录条件匹配',false:'原记录条件不匹配',unknown:'未知'};
defineExpose({clear:v.closePrivate});
</script>
<style scoped>
section{min-width:0}.el-select,.el-input{width:100%;margin:8px 0}fieldset{border:1px solid #dcdfe6;padding:12px;margin:12px 0}[role=alert]{color:#b42318}
</style>
