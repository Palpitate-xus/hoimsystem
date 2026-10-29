<template>
 <section aria-label="科研变量来源治理">
  <el-alert title="请核对项目、变量定义和患者批次，并配置研究及模型处理许可。" type="info" :closable="false" />
  <p v-if="!v.authorized" role="status">当前会话、角色或模式不满足本项条件。</p>
  <template v-else>
   <template v-if="!auditOnly"><el-input v-model="v.manualScopeId" :disabled="v.busy" aria-label="已授权变量项目标识" placeholder="明确已授权的科研项目标识" /><el-button :disabled="v.busy||!v.scopeIdentifierValid" @click="v.chooseScopeIdentifier">读取授权变量项目</el-button><p>须具备本项目访问权、变量抽取用途及全部声明患者的当前研究许可。</p><el-button v-if="v.role!=='pharmacist'" :disabled="v.busy" @click="v.refreshProjects(1)">读取明确项目目录</el-button>
    <el-table v-if="v.projects.length" :data="v.projects" aria-label="明确项目候选目录"><el-table-column prop="scope_id" label="项目标识" /><el-table-column prop="status" label="原记录状态" /><el-table-column label="操作"><template #default="{row}"><el-button :disabled="v.busy" @click="v.chooseProject(row)">核对并明确本项目</el-button></template></el-table-column></el-table>
    <template v-if="v.scopeTotal"><el-button :disabled="v.busy||v.scopePage<=1" @click="v.refreshProjects(v.scopePage-1)">项目上一页</el-button><span>项目第{{ v.scopePage }}页，共{{ v.scopeTotal }}件</span><el-button :disabled="v.busy||v.scopePage*20>=v.scopeTotal" @click="v.refreshProjects(v.scopePage+1)">项目下一页</el-button></template>
    <p v-if="v.project">明确项目 {{ v.project.scope_id }}；用途已记录 research_variable_extraction。登记条件不授予患者正文或出站模型读取权限。</p><p v-else>请先核对并明确选择项目；不会自动选择第一项。</p>
   </template><p v-else>仅超级管理员技术元数据目录：不读取临床正文、不恢复当前项目或逐患者权限，不能执行模型。</p>
   <el-radio-group v-model="v.kind" aria-label="变量来源类型"><el-radio label="dictionary">变量字典</el-radio><el-radio label="batch">完整变量批次</el-radio></el-radio-group>
   <el-button :disabled="v.busy||!auditOnly&&!v.project" @click="v.refresh(1)">刷新变量来源目录</el-button><el-button v-if="!auditOnly&&v.kind==='dictionary'&&v.project" :disabled="v.busy" @click="v.openDictionary">登记明确变量字典</el-button>
   <el-table :data="v.rows" aria-label="变量来源技术目录"><el-table-column prop="record_id" label="来源标识" /><el-table-column label="状态"><template #default="{row}">{{ states[row.status] }}</template></el-table-column><el-table-column prop="created_at" label="登记UTC" /><el-table-column label="操作"><template #default="{row}"><el-button :disabled="v.busy" @click="v.inspect(row)">{{ auditOnly?'核对本件技术元数据':'按当前授权读取完整两件' }}</el-button></template></el-table-column></el-table>
   <p>请选择原件查看记录，核对字段值和时间。</p><el-button :disabled="v.busy||v.page<=1" @click="v.refresh(v.page-1)">来源上一页</el-button><span>来源第{{ v.page }}页，共{{ v.total }}件</span><el-button :disabled="v.busy||v.page*20>=v.total" @click="v.refresh(v.page+1)">来源下一页</el-button>
  </template>
  <p v-if="v.error" role="alert">{{ v.error }}</p><p v-if="v.notice" role="status">{{ v.notice }}</p>
  <el-dialog :model-value="v.detailOpen" title="变量来源完整核对" width="90%" :close-on-click-modal="false" :before-close="done=>{v.close();done();}" destroy-on-close @update:model-value="value=>!value&&v.detailOpen&&v.close()">
   <template v-if="v.detail"><p>来源 {{ v.detail.metadata.record_id }}；{{ states[v.detail.metadata.status] }}；版本 {{ v.detail.metadata.revision }}。</p>
    <p v-if="v.detail.technicalOnly">只有已核验的技术元数据。完整原件、临床正文和当前执行资格均未恢复。</p>
    <template v-else><p>两份完整分件、原件字面值、治理关系和末次元数据已核对；{{ v.detail.currentValidation.eligible?'当前来源条件满足':'当前来源条件不满足' }}。</p><template v-if="v.detail.metadata.record_kind==='batch'"><p>完整原记录 {{ v.detail.snapshot.snapshot.capture.records.length }} 条；原字段展示 {{ v.detail.source.documents.length }} 项。</p><details><summary>身份映射核验详情</summary><p>映射校验由服务器完成。</p></details></template>
     <p v-else>完整变量 {{ v.detail.definition.payload.variables.length }} 项；独立定义核查 {{ v.detail.metadata.definition_review_status }}。审核须由不同于原作者的当前本人执行，服务端再次核验。</p>
     <el-button @click="v.showOriginal=!v.showOriginal">{{ v.showOriginal?'收起完整来源原件':'显式展开完整来源原件' }}</el-button><template v-if="v.showOriginal"><template v-if="v.detail.source"><p>原字段逐项显示；null与空串分别保留，数值原文和无时区钟点不重新解释。</p><ol aria-label="变量来源原字面值"><li v-for="row in visibleLiterals" :key="row.field_token"><p>{{ row.variable_key }} · {{ row.value_kind }}</p><p v-if="row.literal===null">原字段为null</p><p v-else-if="row.literal===''">原明确为空串，与null不同</p><pre v-else>{{ row.literal }}</pre></li></ol><el-pagination v-if="v.detail.source.documents.length>20" v-model:current-page="literalPage" :page-size="20" :total="v.detail.source.documents.length" layout="prev,pager,next,total" /><p>分页仅影响显示；完整性核对包含全部字段与原记录。</p></template><pre aria-label="完整变量来源原件">{{ JSON.stringify(v.detail,null,2) }}</pre></template>
     <el-button v-if="v.detail.metadata.record_kind==='dictionary'&&v.detail.currentValidation.eligible&&!auditOnly" :disabled="v.busy" @click="v.openBatch">用本字典明确捕获患者批次</el-button><el-button v-if="v.canSelect" :disabled="v.busy" @click="v.select">明确选择本完整批次</el-button>
     <fieldset v-if="v.canManual||v.canReview||v.canRevoke" :disabled="v.writePending"><legend>本次明确治理</legend><el-select v-if="v.canManual||v.canReview" v-model="v.decision" aria-label="变量来源本次决定" placeholder="明确本次决定"><el-option v-if="v.canManual" value="recorded_reviewed" label="独立核查所提供变量定义" /><el-option v-if="v.canManual" value="not_confirmed" label="未能确认所提供变量定义" /><el-option v-if="v.canReview" value="publish" label="技术发布本件" /><el-option v-if="v.canReview" value="reject" label="拒绝本件" /></el-select><el-input v-model="v.basis" type="textarea" aria-label="变量来源本次完整依据" placeholder="20字以上；撤销最多1000个Unicode字符与4000UTF8字节" /><el-button v-if="v.canManual" :disabled="v.busy||!['recorded_reviewed','not_confirmed'].includes(v.decision)" @click="v.mutate('definition-review')">提交独立变量定义核查</el-button><el-button v-if="v.canReview" :disabled="v.busy||!['publish','reject'].includes(v.decision)" @click="v.mutate('review')">提交变量来源技术审核</el-button><el-button v-if="v.canRevoke" :disabled="v.busy" @click="v.mutate('revoke')">按原作者或超管权限撤销本件</el-button></fieldset>
    </template>
   </template>
  </el-dialog>
  <el-dialog :model-value="v.formOpen" :title="v.formKind==='dictionary'?'登记明确变量字典':'明确患者与完整变量批次'" width="90%" :close-on-click-modal="false" :before-close="done=>{v.close();done();}" destroy-on-close @update:model-value="value=>!value&&v.formOpen&&v.close()">
   <el-form v-if="v.formOpen&&v.project" label-position="top" @submit.prevent="v.create"><template v-if="v.formKind==='dictionary'"><ResearchVariableSourceEditor v-model="v.form" :families="v.project.original.payload.data_families" :disabled="v.writePending" /></template>
    <template v-else><p>明确字典 {{ v.dictionary.metadata.dictionary_id }}；患者只来自当前已核项目范围，不自动全选。</p><el-checkbox-group v-model="v.patientIds" aria-label="完整明确患者集合"><el-checkbox v-for="id in v.project.original.payload.patient_ids" :key="id" :label="id">项目患者 {{ id }}</el-checkbox></el-checkbox-group><p>须按原项目升序明确选择；不自动排序或去重。</p><el-button :disabled="v.busy" @click="v.readPreview">按当前授权预览完整批次</el-button><p v-if="v.preview">本次预览已核对全部 {{ v.preview.records.length }} 条原记录。来源变动、患者选择变化或关闭后须重读。</p><el-form-item label="完整批次捕获依据"><el-input v-model="v.batchBasis" type="textarea" aria-label="完整批次捕获依据" /></el-form-item></template>
    <el-button :disabled="v.busy" @click="v.create">提交完整来源草稿</el-button><p v-if="v.error" role="alert">{{ v.error }}</p>
   </el-form>
  </el-dialog>
 </section>
</template>
<script setup>
import {computed,reactive,ref,watch} from 'vue';
import ResearchVariableSourceEditor from './ResearchVariableSourceEditor.vue';
import {useResearchVariableSources} from './useResearchVariableSources';
const props=defineProps({active:{type:Boolean,default:true},auditOnly:{type:Boolean,default:false},selectable:{type:Boolean,default:false}}),emit=defineEmits(['select','invalidate','source-changed']),v=reactive(useResearchVariableSources(props,emit));
const states={draft:'草稿',published:'已技术发布',rejected:'已拒绝',revoked:'已撤销'};
const literalPage=ref(1),visibleLiterals=computed(()=>(v.detail?.source?.documents||[]).slice((literalPage.value-1)*20,literalPage.value*20));
watch(()=>v.detail?.metadata.record_id,()=>{literalPage.value=1;});
defineExpose({clear:v.close});
</script>
<style scoped>section{min-width:0}.el-select{width:100%}fieldset{border:1px solid #dcdfe6;margin:12px 0;padding:12px}pre{white-space:pre-wrap;overflow-wrap:anywhere;max-height:55vh;overflow:auto}[role=alert]{color:#b42318}</style>
