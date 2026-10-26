<template>
 <section aria-label="受审运维资料来源">
  <el-alert title="提交前请核对材料中的敏感信息，系统不会自动脱敏。" type="info" :closable="false" />
  <p v-if="!v.allowed">当前身份或会话不可读取运维来源。</p>
  <template v-else>
   <div><el-button @click="v.changeTab('cases')">材料集目录</el-button><el-button @click="v.changeTab('releases')">审核版本目录</el-button><el-button v-if="v.canGovern" @click="v.changeTab('originals')">受控原件目录</el-button><el-button :loading="v.busy" @click="v.refresh">读取当前目录</el-button><el-button v-if="v.canGovern" @click="v.beginOriginal">登记完整原件</el-button></div>
   <p role="alert" v-if="v.error">{{v.error}}</p>
   <p v-if="v.directory">第{{v.directory.page}}页，每页{{v.directory.size}}项；共{{v.directory.total}}个技术目录项。目录分页不代表材料截断。</p>
   <table v-if="v.directory"><thead><tr><th>明确版本</th><th>状态</th><th>完整读取</th></tr></thead><tbody><tr v-for="row in v.directory.items" :key="row.case_id||row.release_id||row.original_id">
    <td>{{row.case_id||row.release_id||row.original_id}}</td><td>{{row.status||'当前正文不可读'}}</td><td><el-checkbox v-if="v.tab==='releases'" :model-value="v.selected.includes(row.release_id)" :disabled="!row.source_accessible||v.busy" @change="value=>v.toggle(row,value)">纳入材料集</el-checkbox><el-button :disabled="v.busy" @click="v.inspect(row)">核对本条完整来源</el-button></td>
   </tr></tbody></table>
   <div v-if="v.directory"><el-button :disabled="v.page<=1||v.busy" @click="v.page--;v.refresh()">上一页</el-button><el-button :disabled="v.page*20>=v.directory.total||v.busy" @click="v.page++;v.refresh()">下一页</el-button></div>
   <el-button v-if="v.tab==='releases'" :disabled="!v.selected.length||v.selected.length>128||v.busy" @click="v.assemble">以明确选中的{{v.selected.length}}个发布版本建立材料集</el-button>
  </template>
  <el-dialog :model-value="v.viewOpen" title="完整受审运维来源" width="80%" :before-close="done=>{v.closeDetail();done();}" :close-on-click-modal="false">
   <template v-if="v.detail">
    <p>明确来源标识：<code>{{v.detail.case_id||v.detail.release_id||v.detail.original_id}}</code></p>
    <p>技术状态：{{v.detail.status}}；版本{{v.detail.revision}}。原件及审计摘要不会凭空恢复缺失正文。</p>
    <p v-if="v.detail.source_accessible===false">当前来源已失效，仅显示技术元数据，不读取原件或公开文本。</p>
    <template v-if="v.source"><article v-for="doc in v.source.value.documents||[v.source.value]" :key="doc.source_id"><h3>{{doc.title}}</h3><p>{{doc.kind}}；组件{{doc.declared_component??'未知'}}；声明版本{{doc.declared_version??'未知'}}</p><pre>{{doc.text}}</pre></article></template>
    <template v-if="v.original"><h3>受控原件，尚未自动遮盖</h3><p>原文码点{{Array.from(v.original.content_text).length}}；登记时钟不证明故障发生时间。</p><pre>{{v.original.content_text}}</pre></template>
    <template v-if="v.draft"><h3>明确码点变换后的完整草稿</h3><pre>{{v.draft.released_text}}</pre></template>
    <el-button v-if="v.canGovern&&v.detail.case_id&&v.source&&!v.protectedPart" :disabled="v.busy" @click="v.openProtected">核对受控原件与完整投影</el-button>
    <pre v-if="v.protectedPart">{{v.canonical(v.protectedPart.value)}}</pre>
    <el-button v-if="!governance&&v.detail.case_id" :disabled="!v.detail.source_accessible||!v.source||v.busy" @click="v.selectCase">选择本条当前材料集</el-button>
    <el-button v-if="v.canGovern&&v.original&&!v.draft" :disabled="v.busy" @click="v.beginRelease">建立人工遮盖草稿</el-button>
    <el-button v-if="v.canGovern&&v.releaseMetadata?.status==='draft'" :disabled="v.busy" @click="v.beginReview">独立人工核查与发布</el-button>
    <el-button v-if="v.canGovern&&v.detail.status!=='revoked'" :disabled="v.busy" @click="v.beginRevoke">撤回本条来源</el-button>
   </template>
  </el-dialog>
  <el-dialog :model-value="!!v.form" title="明确运维来源登记与治理" width="80%" :close-on-click-modal="false" :before-close="done=>{v.closeForm();done();}">
   <template v-if="v.form">
    <template v-if="v.form.kind==='original'">
     <label>原件类别<el-select v-model="v.form.body.kind" aria-label="原件类别" placeholder="明确选择"><el-option label="诊断日志" value="diagnostic_log"/><el-option label="运维手册" value="runbook"/><el-option label="参考文档" value="reference_document"/></el-select></label>
     <label>原件标题<el-input v-model="v.form.body.title" aria-label="原件标题" /></label><label>来源说明<el-input v-model="v.form.body.origin_note" aria-label="来源说明" type="textarea" /></label>
     <label>声明组件（未知留空）<el-input v-model="v.form.body.declared_component" aria-label="声明组件" /></label><label>声明版本（未知留空）<el-input v-model="v.form.body.declared_version" aria-label="声明版本" /></label>
     <label>完整原文<el-input v-model="v.form.body.content_text" aria-label="完整原文" type="textarea" :rows="10" /></label>
    </template>
    <template v-else-if="v.form.kind==='release'">
     <label>发布标题<el-input v-model="v.form.body.released_title" aria-label="发布标题" /></label><label>发布声明组件<el-input v-model="v.form.body.released_component" aria-label="发布声明组件" /></label><el-checkbox :model-value="v.form.body.released_component===null" @change="value=>v.form.body.released_component=value?null:''">发布组件未知</el-checkbox><label>发布声明版本<el-input v-model="v.form.body.released_version" aria-label="发布声明版本" /></label><el-checkbox :model-value="v.form.body.released_version===null" @change="value=>v.form.body.released_version=value?null:''">发布版本未知</el-checkbox><p>原件UUID和完整SHA已绑定，不能更换为其它材料。遮盖位置使用Unicode码点，左闭右开。</p>
     <el-button @click="v.form.body.redactions.push({start_codepoint:0,end_codepoint:0,method:'mask'})">添加明确遮盖范围</el-button>
     <div v-for="(span,index) in v.form.body.redactions" :key="index"><label>起始码点<el-input-number v-model="span.start_codepoint" :min="0" :precision="0" :aria-label="'起始码点'+index" /></label><label>结束码点<el-input-number v-model="span.end_codepoint" :min="0" :precision="0" :aria-label="'结束码点'+index" /></label><el-select v-model="span.method" :aria-label="'遮盖方式'+index"><el-option label="固定遮盖" value="mask"/><el-option label="删除原片段" value="remove"/></el-select><el-button @click="v.form.body.redactions.splice(index,1)">移除此范围</el-button></div>
     <el-checkbox v-if="!v.form.body.redactions.length" v-model="v.form.noRedactions">我已逐字核对，本草稿无需遮盖</el-checkbox><h3>完整变换预览</h3><pre v-if="v.proposalPreview!==null">{{v.proposalPreview}}</pre><p v-else>请修正重叠、逆序或超出原文的范围。</p>
    </template>
    <template v-else-if="v.form.kind==='review'">
     <p>必须由当前独立超级管理员核查，原件登记者及草稿作者不可代签。后端仍核验真实当前身份。</p>
     <label>核查决定<el-select v-model="v.form.body.decision" aria-label="核查决定" placeholder="明确选择"><el-option label="发布" value="publish"/><el-option label="拒绝" value="reject"/></el-select></label>
     <el-checkbox v-model="v.form.body.privacy_reviewed">已人工核查隐私</el-checkbox><el-checkbox v-model="v.form.body.faithfulness_reviewed">已核查变换忠实性</el-checkbox><el-checkbox v-model="v.form.body.applicability_reviewed">已核查适用性声明</el-checkbox><el-checkbox v-model="v.form.body.model_processing_allowed">明确允许本版本模型处理</el-checkbox>
     <label>核查依据<el-input v-model="v.form.body.basis" aria-label="核查依据" type="textarea" /></label>
    </template>
    <label v-else>本次撤回理由<el-input v-model="v.form.body.reason" aria-label="本次撤回理由" type="textarea" /></label>
    <el-button :disabled="!v.formValid" :loading="v.busy" @click="v.save">提交明确登记或治理</el-button><el-button @click="v.closeForm">关闭并清除本次草稿</el-button>
   </template>
  </el-dialog>
 </section>
</template>
<script setup>
import {reactive} from 'vue';
import {useOperationsSources} from './useOperationsSources';
const props=defineProps({active:{type:Boolean,default:true},governance:{type:Boolean,default:false},configRevision:{type:[String,Number],default:null}}),emit=defineEmits(['select','source-changed','invalidate']);
const v=reactive(useOperationsSources(props,emit));
</script>
<style scoped>
section{display:grid;gap:12px}pre{white-space:pre-wrap;overflow-wrap:anywhere;max-height:50vh;overflow:auto;border:1px solid #ddd;padding:12px}table{width:100%;border-collapse:collapse}th,td{text-align:left;border-bottom:1px solid #ddd;padding:8px}label{display:block;margin:12px 0}article{border-bottom:1px solid #ddd}
</style>
