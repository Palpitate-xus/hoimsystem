<template>
 <section aria-label="事件RCA来源治理">
  <el-alert type="info" :closable="false" title="仅有限事件受审文字与人工时间线；登记、逐字引用和技术发布均不认证因果、责任或整改成效，不自动改写旧RCA或推进PDCA。" />
  <p v-if="!v.authorized" role="status">仅当前超级管理员可管理本项；仍须本人独立事件用途与实际关联患者用途许可。</p>
  <p v-if="v.error" role="alert">{{ v.error }}</p>
  <el-button v-if="v.error&&!v.authorized" @click="v.retryScope">显式重新核对当前用途</el-button>
  <template v-else>
   <p>实际事件 {{ eventId??'尚未绑定' }}；原关联患者 {{ expectedPatientId===undefined?'尚未绑定':expectedPatientId===null?'原明确无关联患者':expectedPatientId }}。不会读取全院事件正文或自动选择第一件。</p>
   <p v-if="!v.scopeValid">请从实际事件业务行进入并明确关联范围。</p>
   <el-radio-group v-model="v.kind" aria-label="RCA技术目录类型"><el-radio-button value="grants">独立用途许可</el-radio-button><el-radio-button value="originals">完整人工原件</el-radio-button><el-radio-button value="cases">有限完整Case</el-radio-button></el-radio-group>
   <el-button :loading="v.loading" @click="v.refresh">刷新本事件技术目录</el-button>
   <el-button :disabled="!v.scopeValid||!v.options||v.busy" @click="v.openCreate(v.kind)">{{ {grants:'登记明确用途许可',originals:'登记完整人工原件',cases:'捕获本事件完整Case'}[v.kind] }}</el-button>
   <p v-if="v.notice" role="status">{{ v.notice }}</p>
   <el-table :data="v.directory" aria-label="RCA当前完整技术目录"><el-table-column label="原件标识"><template #default="{row}">{{ row.grant_id||row.original_id||row.case_id }}</template></el-table-column><el-table-column prop="status" label="记录治理状态"/><el-table-column prop="revision" label="版本"/><el-table-column label="正文读取"><template #default="{row}"><el-button @click="v.inspect(row)">明确读取本件完整证明</el-button></template></el-table-column></el-table>
   <p>已核对完整分页，仅目录技术元数据不授予正文或模型执行资格。</p>
  </template>
  <el-dialog v-model="v.detailOpen" title="本件完整原件与实际签署" width="85%" :close-on-click-modal="false">
   <template v-if="v.detail">
    <p>完整content SHA：<code>{{ v.detail.content_hash }}</code></p><p>完整治理SHA：<code>{{ v.detail.governance_hash }}</code></p>
    <p>当前记录状态 {{ v.detail.governance.status }}；{{ v.detailKind==='grants'?(v.detail.current_scope?'当前许可范围满足':'许可已失效'):(v.detail.eligible?'本件满足当前来源条件':'当前不可用于新任务') }}。</p>
    <el-button @click="v.showBody=!v.showBody">{{ v.showBody?'收起本件完整原件':'显式展开本件完整原件' }}</el-button>
    <pre v-if="v.showBody" aria-label="RCA本件完整私有原件">{{ pretty(v.detailKind==='grants'?v.detail.identity:v.detail.immutable) }}</pre>
    <p>原naive时间保留“时区未提供”；登记和审核UTC6为服务器记录时钟，不冒充事件发生时刻。</p>
    <template v-if="v.detailKind!=='grants'&&v.detail.governance.status==='draft'">
     <fieldset><legend>逐项明确原文审核，不默认确认</legend>
      <el-select v-model="v.reviewForm.decision" aria-label="RCA明确审核决定" placeholder="明确发布或拒绝"><el-option label="发布这份提供稿" value="publish"/><el-option label="拒绝这份提供稿" value="reject"/></el-select>
      <el-select v-for="item in reviewFields" :key="item.key" v-model="v.reviewForm[item.key]" :aria-label="item.label" :placeholder="item.label"><el-option label="本人明确确认" value="confirmed"/><el-option label="本人未确认" value="not_confirmed"/><el-option label="未知" value="unknown"/></el-select>
      <el-input v-model="v.reviewForm.basis_note" type="textarea" aria-label="RCA本次审核依据"/><el-button :loading="v.busy" @click="v.mutate('review')">提交本件明确审核</el-button>
     </fieldset>
    </template>
    <fieldset v-if="v.detail.governance.status!=='revoked'"><legend>明确撤销本件</legend><el-input v-model="v.revokeNote" type="textarea" aria-label="RCA本次撤销依据"/><el-button type="danger" :loading="v.busy" @click="v.mutate('revoke')">撤销本件</el-button></fieldset>
    <template v-if="v.detailKind==='cases'&&v.detail.eligible"><el-button :loading="v.busy" @click="v.readPublic">明确读取并核对完整模型投影</el-button><pre v-if="v.publicSource" aria-label="RCA完整公开模型投影">{{ pretty(v.publicSource) }}</pre></template>
    <p v-if="v.formError" role="alert">{{ v.formError }}</p>
   </template>
   <template #footer><el-button v-if="selectable&&v.detailKind==='cases'&&v.detail?.eligible" :disabled="v.busy" @click="v.selectCase">明确选择本件当前Case</el-button><el-button @click="v.detailOpen=false">关闭本件原件</el-button></template>
  </el-dialog>
  <el-dialog v-model="v.createOpen" :title="{grants:'登记本件明确用途许可',originals:'登记完整人工原件',cases:'捕获完整有限Case'}[v.createKind]" width="85%" :close-on-click-modal="false">
   <p>当前实际事件 {{ eventId }}；原关联患者 {{ expectedPatientId===null?'原明确无关联患者':expectedPatientId }}。技术身份不代替独立用途或专业资格。</p>
   <template v-if="v.createKind==='cases'||v.createKind==='originals'">
    <el-button :loading="v.busy" @click="v.captureCurrent">明确读取本事件完整当前集合</el-button>
    <template v-if="v.capture"><p>全部旧RCA {{ v.capture.rcas.length }} 件；全部人工原件 {{ v.capture.originals.length }} 件；完整集合SHA：<code>{{ v.capture.collection_hash }}</code></p><el-button @click="v.showCapture=!v.showCapture">{{ v.showCapture?'收起完整集合':'显式展开完整捕获集合' }}</el-button><pre v-if="v.showCapture" aria-label="RCA当前完整捕获集合">{{ pretty(v.capture) }}</pre></template>
   </template>
   <el-form v-if="formSchema" label-position="top"><RcaEvidenceFields v-model="v.form" :schema="formSchema" :root="rootSchema" label="本次明确登记字段" :lookups="lookups" :fixed-keys="['expected_raw_hash']"/></el-form>
   <label v-if="v.createKind==='originals'">从完整UTF8原文件载入文字<input type="file" aria-label="载入RCA完整UTF8原文" accept=".txt,.md" @change="event=>{const file=event.target.files?.[0];event.target.value='';v.readTextFile(file);}"/></label>
   <p v-if="v.createKind==='originals'">文件载入保留BOM和CRLF；在文本控件重新编辑会形成新的人工录入文字，应重新核对本次完整提供稿。</p>
   <template v-if="v.createKind==='originals'&&v.form.provenance?.method==='human_declared_derivative'"><el-button :disabled="!v.capture||v.busy" @click="v.readWitness">读取所选完整旧原件并绑定其SHA</el-button><p v-if="v.witness">已核对完整旧原件SHA：{{ v.witness.raw_hash }}。人工提供稿仍须单独逐字审核。</p></template>
   <p>所有原文保留BOM、CRLF、空值与Unicode codepoint；单原文上限4MiB，完整请求/各响应8MiB，超限拒绝而不裁剪。不会自动发布、推断原因或调用模型。</p>
   <p v-if="v.formError" role="alert">{{ v.formError }}</p>
   <template #footer><el-button @click="v.createOpen=false">取消本次登记</el-button><el-button :loading="v.busy" :disabled="!v.createValid" @click="v.create">登记本次明确整件</el-button></template>
  </el-dialog>
 </section>
</template>
<script setup>
import {computed,reactive} from 'vue';
import {useRcaEvidenceSources} from './useRcaEvidenceSources';
import RcaEvidenceFields from './RcaEvidenceFields.vue';
import {rcaSchemaDefinition} from '@/api/ai/rcaEvidenceSources';
const props=defineProps({eventId:{type:Number,default:null},expectedPatientId:{default:undefined},active:{type:Boolean,default:true},selectable:{type:Boolean,default:false}}),emit=defineEmits(['source-changed','invalidate','select']),v=reactive(useRcaEvidenceSources(props,emit));
const reviewFields=[{key:'privacy_review',label:'本件隐私复核'},{key:'faithfulness_review',label:'本件提供稿忠实性复核'},{key:'provenance_review',label:'本件来源依据复核'}],pretty=value=>JSON.stringify(value,null,2);
const rootSchema=computed(()=>rcaSchemaDefinition(v.createModel)),formSchema=computed(()=>{const root=rootSchema.value;if(!root)return null;const omit=new Set(['event_id','expected_event_patient_id','expected_collection_hash']);return {...root,properties:Object.fromEntries(Object.entries(root.properties).filter(([key])=>!omit.has(key))),required:root.required?.filter(key=>!omit.has(key))};});
const lookups=computed(()=>({grantee_id:v.users.map(u=>({label:`${u.username}（实际用户${u.user_id}）`,value:u.user_id})),witness_id:v.capture?(v.form.provenance?.witness_kind==='legacy_event'?[{label:`实际事件${v.capture.event.event_id}`,value:v.capture.event.event_id}]:v.capture.rcas.map(row=>({label:`实际同事件RCA${row.rca_id}`,value:row.rca_id}))):[]}));
defineExpose({state:v});
</script>
<style scoped>
.el-select,.el-input{width:100%;margin:8px 0}fieldset{margin:12px 0;padding:12px;border:1px solid #dcdfe6}pre{white-space:pre-wrap;overflow-wrap:anywhere;max-height:45vh;overflow:auto;padding:12px;border:1px solid #dcdfe6}code{overflow-wrap:anywhere}[role=alert]{color:#b42318}
</style>
