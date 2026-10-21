<template>
 <section aria-label="共享病例去标识任务完整分件">
  <p>模型只给出部分待核对候选，不保证完整识别或匿名；不会自动创建人工复核、替换正文、发布或导出。</p>
  <p v-if="!allowed" role="status">当前会话不可读取，旧原文、问题和候选已清除。</p>
  <template v-else>
   <el-button :disabled="busy||!validId" @click="load">按当前权限核对四份完整分件</el-button><el-button @click="close">关闭并清除本次任务正文</el-button>
   <p v-if="busy" role="status">正在独立读取完整分件并核对原UTF8字节…</p><p v-if="error" role="alert">{{ error }}</p>
   <template v-if="metadata">
    <p aria-label="共享去标识任务状态">任务 {{ metadata.run_id }}：{{ states[metadata.status] }}。</p>
    <p aria-label="共享去标识实际用量">输入 {{ shown(metadata.input_tokens) }}；输出 {{ shown(metadata.output_tokens) }}；{{ metadata.usage_receipt.model_call_attempted===null?'是否调用未知':metadata.usage_receipt.model_call_attempted?'已有实际调用回执':'已确认未调用模型' }}。{{ metadata.usage_receipt.complete?'两项用量均返回':'实际用量尚不完整，不补零' }}。</p>
    <template v-if="!bundle?.parts"><p aria-label="共享去标识仅技术范围">当前仅技术状态、实际用量和不透明SHA；未读取Source、私有范围、Task或Result，技术身份不恢复撤回的项目或逐患者用途。</p><pre aria-label="共享去标识不透明锚">{{ JSON.stringify(metadata.opaque_hashes,null,2) }}</pre></template>
    <el-button v-if="['queued','running'].includes(metadata.status)&&metadata.finish_time===null" :disabled="busy" @click="cancel">停止接收本次任务</el-button>
   </template>
   <template v-if="bundle?.parts">
    <p aria-label="共享去标识完整核验范围">已核对当前授权的四份独立原UTF8正文、完整所选来源、唯一公开投影、冻结Prompt/Provider/执行锚、原始三项JSON和服务器结果；服务端Audit回执不是浏览器独立数据库审计。</p>
    <p>所选 {{ source.documents.length }} 个完整文字字段；未选正文、全量姓名字典及组合风险不代表已经覆盖。{{ auditOnly?'超级管理员本次临床审计也经过当前项目与逐患者用途校验。':'' }}</p>
    <p v-if="result" aria-label="共享去标识部分候选">模型返回 {{ result.candidate_count }} 条未审核部分候选；零候选也不表示没有标识风险。</p><p v-else>当前没有已接收的模型候选结果。</p>
    <el-table v-if="result?.draft.candidates.length" :data="visibleCandidates" aria-label="共享去标识待核对候选">
     <el-table-column label="类别"><template #default="{row}">{{ categories[row.category] }}</template></el-table-column>
     <el-table-column label="原文码点区间"><template #default="{row}">[{{ row.start }}, {{ row.end }})</template></el-table-column><el-table-column prop="review_note" label="模型待核查说明"/>
     <el-table-column label="逐字证据"><template #default="{row}"><el-button @click="inspectQuote(row.ordinal)">按当前权限展开第{{ row.ordinal+1 }}条引文</el-button></template></el-table-column>
    </el-table>
    <el-pagination v-if="result&&result.candidate_count>10" v-model:current-page="candidatePage" :page-size="10" :total="result.candidate_count" layout="prev,pager,next"/>
    <el-button @click="originalOpen=!originalOpen">{{ originalOpen?'收起完整所选文字':'显式展开完整所选文字' }}</el-button><el-button @click="privateOpen=!privateOpen">{{ privateOpen?'收起私有Case':'显式展开私有Case' }}</el-button><el-button v-if="auditOnly" @click="rawOpen=!rawOpen">{{ rawOpen?'收起原始任务JSON':'显式展开原始三项任务JSON' }}</el-button>
    <div v-if="originalOpen"><article v-for="d in source.documents" :key="d.source_id"><p>{{ d.field }}：{{ d.text===null?'NULL（未记录）':d.text===''?'已记录空串':d.codepoint_length+'个码点 / '+d.utf8_bytes+' UTF8字节' }}</p><pre v-if="d.text!==null" aria-label="共享去标识完整原文字段">{{ d.text }}</pre></article></div>
    <pre v-if="privateOpen" aria-label="共享去标识私有Case原件">{{ JSON.stringify(bundle.parts.scope.value,null,2) }}</pre><pre v-if="rawOpen" aria-label="共享去标识原始任务JSON">{{ JSON.stringify(bundle.parts.task.value.raw_frozen_json,null,2) }}</pre>
    <template v-if="result&&!auditOnly"><el-select v-model="feedbackOutcome" aria-label="明确模型候选反馈"><el-option label="接受部分建议" value="accepted"/><el-option label="修改后使用" value="modified"/><el-option label="拒绝建议" value="rejected"/></el-select><el-input v-model="feedbackComment" type="textarea" aria-label="原样人工反馈说明"/><el-button :disabled="busy||!feedbackOutcome" @click="feedback">记录人工反馈</el-button><p v-if="feedbackSaved" role="status">人工反馈已记录；没有创建遮蔽、Review或ExportRelease。</p></template>
   </template>
  </template>
  <el-dialog :model-value="quoteOpen&&allowed" title="当前授权的逐字候选" append-to-body destroy-on-close @update:model-value="value=>{if(!value)closeQuote()}">
   <p v-if="quoteBusy">正在重新核对当前用途、完整原件和逐字位置…</p><template v-if="quote"><p>Unicode码点 [{{ quote.start }}, {{ quote.end }})</p><pre aria-label="共享去标识逐字引文">{{ quote.quote }}</pre><p>{{ quote.review_note }}</p></template>
  </el-dialog>
 </section>
</template>
<script setup>
import{computed,onActivated,onBeforeUnmount,onDeactivated,onMounted,ref,watch}from'vue';import{useStore}from'vuex';
import{loadDeidentificationSharedBundle,cancelDeidentificationSharedTask,feedbackDeidentificationSharedTask}from'@/api/ai/deidentificationSharedTasks';
import{deidentificationPolicy}from'@/api/ai/deidentificationSources';import{deidentificationCandidateCategories as categories}from'@/api/ai/deidentificationResults';
import{deidentificationCanonical as canonical,deidentificationId as uuid,same}from'@/api/ai/deidentificationCore';
const props=defineProps({runId:{type:String,default:null},scope:{type:Object,default:null},patientId:{type:Number,default:null},references:{type:Object,default:null},expectedInput:{type:Object,default:null},auditOnly:{type:Boolean,default:false},active:{type:Boolean,default:true},configRevision:{type:[Number,String],default:null}}),emit=defineEmits(['invalidate','close','metadata','ready']),store=useStore(),kept=ref(true),busy=ref(false),metadata=ref(null),bundle=ref(null),error=ref(''),originalOpen=ref(false),privateOpen=ref(false),rawOpen=ref(false),candidatePage=ref(1),quoteOpen=ref(false),quoteBusy=ref(false),quote=ref(null),feedbackOutcome=ref(null),feedbackComment=ref(''),feedbackSaved=ref(false);let epoch=0,quoteEpoch=0,alive=true,mounted=false;
const roles=computed(()=>store.state.user?.permissions),allowed=computed(()=>alive&&props.active&&kept.value&&!!store.state.user?.accessToken&&Array.isArray(roles.value)&&roles.value.every(x=>typeof x==='string')&&roles.value.some(x=>deidentificationPolicy.source_roles.includes(x))&&(!props.auditOnly||roles.value.includes('super_admin'))),validId=computed(()=>uuid(props.runId)),source=computed(()=>bundle.value?.parts?.source.value??null),result=computed(()=>bundle.value?.parts?.result.value??null),visibleCandidates=computed(()=>(result.value?.draft.candidates||[]).slice((candidatePage.value-1)*10,candidatePage.value*10).map((v,i)=>({...v,ordinal:(candidatePage.value-1)*10+i})));
const states={queued:'排队中',running:'执行中',succeeded:'部分候选已接收，未审核',failed:'任务失败',cancelled:'已停止接收'},shown=v=>v===null?'未知':String(v),identity=()=>canonical([props.runId,props.scope,props.patientId,props.references,props.expectedInput,props.auditOnly,props.active,props.configRevision,store.state.user?.accessToken,store.state.user?.username,roles.value]),current=t=>mounted&&allowed.value&&t.epoch===epoch&&t.identity===identity();
const expected=()=>({...props.scope===null?{}:{scope:props.scope},...props.patientId===null?{}:{patientId:props.patientId},...props.references===null?{}:{references:props.references},...props.expectedInput===null?{}:{input:props.expectedInput}});
function closeQuote(){quoteEpoch++;quoteOpen.value=false;quoteBusy.value=false;quote.value=null;}
function clear(){epoch++;busy.value=false;metadata.value=null;bundle.value=null;originalOpen.value=false;privateOpen.value=false;rawOpen.value=false;candidatePage.value=1;feedbackOutcome.value=null;feedbackComment.value='';feedbackSaved.value=false;error.value='';closeQuote();}
async function load(){clear();if(!allowed.value||!validId.value)return;const t={epoch:++epoch,identity:identity()};busy.value=true;try{const value=await loadDeidentificationSharedBundle(props.runId,{auditOnly:props.auditOnly,expected:expected(),current:()=>current(t)});if(!current(t))return;metadata.value=value.metadata;bundle.value=value;emit('metadata',value.metadata);emit('ready',!!value.parts);}catch{if(current(t)){clear();error.value='当前用途、原始完整分件或任务绑定无法核对；旧全文与候选已清除。';emit('invalidate');}}finally{if(current(t))busy.value=false;}}
async function inspectQuote(index){if(!allowed.value||!bundle.value?.parts)return;const original=result.value?.draft.candidates[index];if(!original)return;closeQuote();quoteOpen.value=true;quoteBusy.value=true;const q=++quoteEpoch,t={epoch,identity:identity()},check=()=>current(t)&&q===quoteEpoch&&quoteOpen.value;try{const value=await loadDeidentificationSharedBundle(props.runId,{auditOnly:props.auditOnly,expected:expected(),current:check});if(!check())return;const actual=value.parts?.result.value?.draft.candidates[index];if(!actual||!same(actual,original))throw new Error();bundle.value=value;metadata.value=value.metadata;quote.value=actual;}catch{if(check()){clear();error.value='当前引文读取失效，旧正文和候选已清除。';emit('invalidate');}}finally{if(check())quoteBusy.value=false;}}
async function cancel(){if(!allowed.value||!metadata.value)return;const t={epoch,identity:identity()};busy.value=true;try{await cancelDeidentificationSharedTask(props.runId);if(current(t))await load();}catch{if(current(t)){clear();error.value='当前停止请求未获确认；未假定零用量。';}}finally{if(current(t))busy.value=false;}}
async function feedback(){if(!allowed.value||!result.value||props.auditOnly)return;const t={epoch,identity:identity()};busy.value=true;try{const value=await loadDeidentificationSharedBundle(props.runId,{expected:expected(),current:()=>current(t)});if(!current(t))return;if(!value.parts?.result.value)throw new Error();await feedbackDeidentificationSharedTask(props.runId,feedbackOutcome.value,feedbackComment.value);if(current(t))feedbackSaved.value=true;}catch{if(current(t)){clear();error.value='当前反馈或用途无法确认，未保留旧候选。';emit('invalidate');}}finally{if(current(t))busy.value=false;}}
function close(){clear();emit('close');}
watch([()=>props.scope,()=>props.patientId,()=>props.references,()=>props.expectedInput,()=>props.auditOnly,()=>props.active,()=>props.configRevision,()=>store.state.user?.accessToken,()=>store.state.user?.username,roles,kept],clear,{deep:true,flush:'sync'});watch(()=>props.runId,()=>{clear();if(mounted&&allowed.value&&validId.value)load();},{flush:'post'});onMounted(()=>{mounted=true;if(allowed.value&&validId.value)load();});onActivated(()=>{kept.value=true;});onDeactivated(()=>{kept.value=false;});onBeforeUnmount(()=>{alive=false;mounted=false;clear();});defineExpose({clear,load});
</script>
<style scoped>section{display:grid;gap:12px}pre{white-space:pre-wrap;overflow-wrap:anywhere;max-height:360px;overflow:auto}</style>
