<template>
 <section aria-label="脱敏来源与受控输出管理">
  <el-alert title="仅处理明确项目和单个患者选定的完整文字字段。候选、人工遮蔽和技术发布都不能保证匿名；Super角色也不代替当前项目和逐患者授权。" type="info" :closable="false" />
  <p v-if="!v.scopeValid" role="status">请先明确项目三锚和真实患者，再读取本领域资料；不会自动选择全院、首个项目或患者。</p>
  <p v-else-if="!v.authorized" role="status">当前会话或本用途读取条件不足，原文和引文未保留。</p>
  <template v-if="v.scopeValid">
   <p>用途：脱敏候选及输出复核（deidentification_review）。项目 {{ scope.scope_id }}；明确患者 {{ patientId }}。</p>
   <p v-if="auditOnly">技术冻结核对：不恢复当前研究用途、模型或导出资格。</p>
   <el-button :disabled="!v.authorized||v.busy||v.loading" @click="v.refresh">刷新完整技术目录</el-button>
   <el-button :disabled="!v.authorized||auditOnly||v.busy||v.loading" @click="v.openCapture">明确选择原文字段登记来源</el-button>
   <el-button @click="v.retryAccess">重新核对当前权限</el-button>
   <el-table :data="v.rows" aria-label="完整来源技术目录">
    <el-table-column prop="case_id" label="来源标识"/><el-table-column label="状态"><template #default="{row}">{{ states[row.status] }}</template></el-table-column><el-table-column prop="recorded_at" label="记录UTC6"/><el-table-column label="操作"><template #default="{row}"><el-button :disabled="!v.authorized||v.busy" @click="v.inspect(row)">显式读取本件完整来源</el-button></template></el-table-column>
   </el-table>
   <p>目录 {{ v.rows.length }} 件，仅提供完整技术定位；没有读取未选原文，也不据目录执行模型。</p>
   <fieldset :disabled="!v.authorized||v.busy"><legend>重读明确已有的人工复核或放行件</legend><el-select v-model="v.lookupKind" aria-label="明确已有原件类型" placeholder="请明确选择"><el-option value="review" label="人工编辑及残余风险复核"/><el-option value="release" label="单件导出放行"/></el-select><el-input v-model="v.manualId" aria-label="明确已有原件标识" placeholder="粘贴实际登记回执的规范标识"/><el-button @click="v.inspectChild">显式读取明确复核或放行件</el-button></fieldset>
  </template>
  <el-button v-if="v.busy||v.loading" @click="v.close">取消本次读取与清空资料</el-button>
  <p v-if="v.error" role="alert">{{ v.error }}</p><p v-if="v.notice" role="status">{{ v.notice }}</p><p v-if="v.formError&&!v.detailOpen&&!v.createOpen" role="alert">{{ v.formError }}</p>
  <el-dialog :model-value="v.createOpen" title="明确完整原文字段与来源登记" width="88%" :close-on-click-modal="false" @update:model-value="value=>!value&&v.close()">
   <template v-if="v.createOpen">
    <p>只选择当前目录中的完整文字字段。NULL、空串及未知时间保留；父件或时间未闭合的字段不能登记。</p>
    <fieldset :disabled="v.busy||v.loading"><legend>完整字段目录</legend><el-checkbox-group v-model="v.selected" aria-label="明确完整原文字段集合"><div v-for="e in v.fields?.items||[]" :key="v.choiceKey(e)"><el-checkbox :label="v.choiceKey(e)" :disabled="e.parent_binding.status!=='patient_bound'||e.window_status!=='recorded_calendar_in_scope'">{{ families[e.family] }} · {{ e.record_id }} · {{ e.field }} · {{ e.text_state==='not_recorded'?'未记录NULL':e.text_state==='recorded_empty'?'记录为空串':e.codepoint_length+' CP／'+e.utf8_bytes+' UTF8字节' }} · {{ e.window_status==='unknown_clock'?'时间依据未知':'原日历在范围内' }}</el-checkbox></div></el-checkbox-group><el-button :disabled="!v.captureRequest" @click="v.previewCapture">核对本次完整选定原文预览</el-button></fieldset>
    <div v-if="v.preview" aria-label="本次完整选定原文预览"><p>完整候选集合 {{ v.preview.capture.member_manifest.length }} 根，选定 {{ v.preview.capture.selected_documents.length }} 个完整字段。非选原文仅保留 opaque SHA，不宣称已重建全文。</p><div v-for="d in v.preview.capture.selected_documents" :key="d.document.source_id"><p>{{ d.document.field }}，{{ d.document.text===null?'未记录NULL':d.document.codepoint_length+' CP' }}</p><pre>{{ d.document.text }}</pre></div></div>
    <el-form-item label="完整来源登记依据"><el-input v-model="v.basisNote" type="textarea" aria-label="完整来源登记依据" :disabled="v.busy"/></el-form-item><el-button :disabled="v.busy||!v.preview" @click="v.submitCase">登记本次完整来源草稿</el-button><p v-if="v.formError" role="alert">{{ v.formError }}</p>
   </template>
  </el-dialog>
  <el-dialog :model-value="v.detailOpen" title="脱敏来源、独立复核与受控单件输出" width="90%" :close-on-click-modal="false" @update:model-value="value=>!value&&v.close()">
   <template v-if="v.detail&&v.currentRow">
    <p>{{ {case:'来源',review:'人工复核',release:'单件放行'}[v.detail.kind] }} {{ v.currentRow[v.detail.kind+'_id'] }}；{{ states[v.currentRow.status] }}，版本{{ v.currentRow.revision }}；{{ v.currentRow.eligible?'当前条件已闭合':'当前条件尚未闭合' }}。</p>
    <p v-if="v.detail.source.snapshot!==null">可见完整原件、UTF8、CP、选定投影及输出已逐项核对；来源自身未披露的审核备注仅按服务器治理SHA锚保留，没有从摘要重建隐去原文。</p>
    <p v-if="v.detail.source.snapshot===null" role="status">仅技术元数据和opaque SHA；当前项目及逐患者用途不允许读取正文，没有冻结正文旁路。</p>
    <template v-else>
     <el-button @click="v.showOriginal=!v.showOriginal">{{ v.showOriginal?'收起完整原件与输出':'显式展开完整原件与输出' }}</el-button>
     <div v-if="v.showOriginal" aria-label="完整原件与选定输出">
      <div v-for="d in v.detail.source.public_source.documents" :key="d.source_id"><p>原文字段 {{ d.field }} · {{ d.text===null?'未记录NULL':d.codepoint_length+' CP／'+d.utf8_bytes+' UTF8字节' }}</p><pre>{{ d.text }}</pre></div>
      <details><summary>院内完整来源及授权捕获原件</summary><pre>{{ JSON.stringify(v.detail.source.snapshot,null,2) }}</pre></details>
      <template v-if="v.detail.review?.original"><p>人工明确编辑后的完整选定输出；残余风险{{ v.detail.review.manual_status==='reviewed_residual_risk_remains'?'已明确记录仍存在':'尚未独立确认' }}。</p><div v-for="d in v.detail.review.output.documents" :key="d.source_id"><p>{{ d.field }}</p><pre>{{ d.text }}</pre></div><details><summary>完整人工选择与独立签署依据</summary><pre>{{ JSON.stringify({original:v.detail.review.original,manual_review:v.detail.review.manual_review},null,2) }}</pre></details></template>
      <template v-if="v.detail.release?.original"><p>已记录下载{{ v.detail.release.download_count }}次，最多{{ v.detail.release.maximum_downloads }}次。导出依据与收件范围不代授研究读取或模型权限。</p><details><summary>完整单件导出依据与独立签署</summary><pre>{{ JSON.stringify({original:v.detail.release.original,manual_review:v.detail.release.manual_review},null,2) }}</pre></details></template>
     </div>
     <div v-if="!auditOnly">
      <el-button v-if="v.detail.source.eligible&&v.detail.kind==='case'" :disabled="v.busy" @click="v.openEditor('human')">逐项明确人工遮蔽或移除</el-button>
      <el-button v-if="v.detail.review?.eligible&&v.detail.kind==='review'" :disabled="v.busy" @click="v.openEditor('release')">登记独立单件导出依据</el-button>
      <el-button v-if="v.detail.kind==='case'&&v.detail.source.eligible" :disabled="v.busy" @click="v.select">明确选择此当前来源</el-button>
      <el-button v-if="v.detail.release?.eligible&&v.detail.kind==='release'" :disabled="v.busy" @click="v.download">显式下载本件受控输出</el-button>
     </div>
     <DeidentificationHumanEdits v-if="v.editor==='human'&&!auditOnly" :key="v.formKey" :source="v.detail.source" :busy="v.busy" @submit="v.submitHuman" @change="v.formChanged"/>
     <DeidentificationReleaseForm v-if="v.editor==='release'&&!auditOnly" :key="v.formKey" :review="v.detail.review" :busy="v.busy" @submit="v.submitRelease" @change="v.formChanged"/>
    </template>
    <fieldset v-if="!auditOnly&&(v.currentRow.can_manual_review||v.currentRow.can_review||v.currentRow.can_revoke)" :disabled="v.busy"><legend>独立人工核查与技术治理分别提交</legend>
     <template v-if="v.currentRow.can_manual_review"><el-select v-model="v.decision" aria-label="独立人工复核决定" placeholder="请明确选择"><el-option label="已核查且仍有残余风险" value="reviewed_residual_risk_remains"/><el-option label="未能确认" value="not_confirmed"/></el-select><el-input v-model="v.risks" type="textarea" aria-label="逐行完整残余风险记录" placeholder="每行一项明确残余风险，最多64项"/></template>
     <el-select v-if="v.currentRow.can_review" v-model="v.decision" aria-label="本件技术审核决定" placeholder="请明确选择"><el-option label="技术发布" value="publish"/><el-option label="技术拒绝" value="reject"/></el-select>
     <el-input v-model="v.governanceBasis" type="textarea" aria-label="本次完整核查或治理依据" placeholder="至少20字；撤销最多1000 Unicode码点且4000 UTF8字节"/>
     <el-button v-if="v.currentRow.can_manual_review" @click="v.mutate('manual')">提交独立人工复核</el-button><el-button v-if="v.currentRow.can_review" @click="v.mutate('review')">提交本件技术审核</el-button><el-button v-if="v.currentRow.can_revoke" @click="v.mutate('revoke')">撤销本件</el-button>
    </fieldset>
    <p v-if="v.formError" role="alert">{{ v.formError }}</p>
   </template>
  </el-dialog>
 </section>
</template>
<script setup>
import{reactive}from'vue';import{useDeidentificationSources}from'./useDeidentificationSources';import DeidentificationHumanEdits from'./DeidentificationHumanEdits.vue';import DeidentificationReleaseForm from'./DeidentificationReleaseForm.vue';
const props=defineProps({scope:{type:Object,default:null},patientId:{type:Number,default:null},active:{type:Boolean,default:true},auditOnly:{type:Boolean,default:false}}),emit=defineEmits(['source-changed','invalidate','select']),v=reactive(useDeidentificationSources(props,emit));
const states={draft:'待审核草稿',published:'已技术发布',rejected:'已技术拒绝',revoked:'已撤销'},families={medical_records:'门诊病历',admissions:'住院记录',structured_medical_records:'结构化病历'};
defineExpose({clear:v.clear});
</script>
<style scoped>section{min-width:0}.el-input,.el-select{width:100%;margin:6px 0}fieldset{margin:14px 0;padding:12px;border:1px solid #dcdfe6}pre{white-space:pre-wrap;overflow-wrap:anywhere;max-height:45vh;overflow:auto;border:1px solid #ddd;padding:10px}[role=alert]{color:#b42318}.el-checkbox{height:auto;white-space:normal}</style>
