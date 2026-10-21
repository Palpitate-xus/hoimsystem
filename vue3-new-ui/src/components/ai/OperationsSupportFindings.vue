<template>
 <section aria-label="完整运维材料任务核对与草稿">
  <p>本任务只阅读明确受审材料，不观察实时环境，不执行命令，不把模型假设当作故障或兼容性结论。</p>
  <el-button v-if="allowed" :disabled="busy||!operationsId(runId)" @click="refresh">重新核对当前任务</el-button>
  <p v-if="busy" role="status">正在核对当前权限、完整四分件与实际回执。</p><p v-if="error" role="alert">{{error}}</p>
  <template v-if="allowed&&bundle">
   <p aria-label="运维任务状态">任务{{bundle.metadata.run_id}}：{{bundle.metadata.status}}；{{bundle.metadata.preview?'超级管理员预览任务':'明确业务任务'}}。</p>
   <p aria-label="运维实际用量">输入：{{shown(bundle.metadata.usage?.input_tokens)}}；输出：{{shown(bundle.metadata.usage?.output_tokens)}}；{{bundle.metadata.usage?.model_call_attempted===true?'已尝试模型调用':bundle.metadata.usage?.model_call_attempted===false?'已确认未调用模型':'是否调用未知'}}。{{bundle.metadata.receipt_pending?'原在途调用实际回执尚未返回。':''}}</p>
   <p v-if="!bundle.parts" aria-label="运维仅技术范围">当前仅显示技术状态与实际已记录用量，不读取原件、公开材料、Prompt、RAW3或结果。超级管理员身份不能恢复已撤回来源。</p>
   <template v-else>
    <p>完整公开Source、实际Prompt版本、原始TEXT与具体回执主键已核对；隐藏原件与终态SQL摘要仍是服务端不透明锚。</p>
    <p>目标：{{objectives[bundle.metadata.binding.objective]}}；材料{{source.documents.length}}件；{{source.action_basis==='missing_reviewed_runbook'?'缺少受审排查手册，不能从日志生成操作指令。':'操作参考仍须管理员核查当前环境与影响。'}}</p>
    <template v-if="result">
     <h3>待人工核实的模型草稿</h3>
     <article v-for="(row,i) in result.observations" :key="'o'+i" aria-label="材料观察"><h4>{{row.title}}</h4><p>{{row.explanation}}</p><el-button v-for="(span,j) in row.evidence" :key="j" @click="show(span)">核对观察{{i+1}}的逐字引文{{j+1}}</el-button></article>
     <article v-for="(row,i) in result.hypotheses" :key="'h'+i" aria-label="未核实故障假设"><h4>{{row.title}}</h4><p>{{row.explanation}}</p><p>未核实假设，需管理员复核。</p><el-button v-for="(span,j) in row.evidence" :key="j" @click="show(span)">核对假设{{i+1}}的逐字引文{{j+1}}</el-button></article>
     <article v-for="(row,i) in result.manual_checks" :key="'c'+i" aria-label="手册原操作参考"><p>{{row.purpose}}</p><p>仅受审手册原引用，不自动执行；当前适用性与影响尚未核实。</p><el-button @click="show(row.instruction_reference)">核对检查{{i+1}}的手册原文</el-button></article>
     <ul aria-label="明确资料缺口"><li v-for="(gap,i) in result.gaps" :key="i">{{gap.kind}}：{{gap.explanation}}</li></ul>
     <el-form aria-label="运维草稿人工反馈" label-position="top"><el-form-item label="人工复核结论"><el-select v-model="outcome" aria-label="人工复核结论"><el-option label="接受此草稿供人工使用" value="accepted"/><el-option label="修改后使用" value="modified"/><el-option label="拒绝此草稿" value="rejected"/></el-select></el-form-item><el-form-item label="复核说明"><el-input v-model="comment" aria-label="复核说明" type="textarea"/></el-form-item><el-button :disabled="!feedbackReady||busy" @click="feedback">记录本任务人工反馈</el-button><p v-if="feedbackId">本任务反馈回执：{{feedbackId}}。这不证明当前环境或兼容性。</p></el-form>
    </template><p v-else>尚无完整成功草稿；排队、在途、取消和失败状态不等于模型完成。</p>
    <el-button :disabled="busy" @click="openRaw">显式核对本任务原始TEXT与Prompt</el-button>
   </template>
   <el-button v-if="['queued','running'].includes(bundle.metadata.status)" :disabled="busy" @click="cancel">停止接收本任务结果</el-button>
  </template>
  <el-dialog :model-value="evidenceOpen" title="当前运维材料逐字引文" :close-on-click-modal="false" :before-close="done=>{closeEvidence();done();}"><template v-if="evidence"><p>{{evidence.document.title}}；原Unicode码点范围[{{evidence.start_codepoint}}, {{evidence.end_codepoint}})。</p><blockquote>{{evidence.quote}}</blockquote><pre>{{evidence.document.text}}</pre></template></el-dialog>
  <el-dialog :model-value="rawOpen" title="本任务完整原始TEXT与冻结Prompt" :close-on-click-modal="false" :before-close="done=>{closeRaw();done();}"><template v-if="rawTask"><p>以下均为原分件字符串，未把重新序列化对象称为原TEXT。Source撤回后不能借审计恢复。</p><pre v-for="(text,key) in rawTask.raw" :key="key" :aria-label="key">{{text}}</pre><pre aria-label="原始Prompt快照TEXT">{{rawTask.prompt_snapshot_json}}</pre><pre aria-label="原始执行快照TEXT">{{rawTask.execution_snapshot_json}}</pre></template></el-dialog>
 </section>
</template>
<script setup>
import{computed,ref,watch}from'vue';
import{useOperationsSession}from'./useOperationsSession';
import{loadOperationsTaskBundle,operationsObjectives,resolveOperationsCitation,feedbackOperationsTask,cancelOperationsTask,verifyOperationsCancelAck}from'@/api/ai/operationsSupportTasks';
import{operationsId,operationsKeys,operationsScalar,operationsBytes}from'@/api/ai/operationsSupportCore';
const props=defineProps({runId:{type:String,default:null},selection:{type:Object,default:null},auditOnly:{type:Boolean,default:false},active:{type:Boolean,default:true},configRevision:{type:[String,Number],default:null}}),emit=defineEmits(['invalidate','status']),bundle=ref(null),busy=ref(false),error=ref(''),evidenceOpen=ref(false),evidence=ref(null),rawOpen=ref(false),rawTask=ref(null),outcome=ref(null),comment=ref(''),feedbackId=ref(null),objectives=operationsObjectives;
let viewEpoch=0,timer=null;
function stop(){clearTimeout(timer);timer=null;}
function closeEvidence(){viewEpoch++;evidenceOpen.value=false;evidence.value=null;schedule();}
function closeRaw(){viewEpoch++;rawOpen.value=false;rawTask.value=null;schedule();}
function reset(){stop();viewEpoch++;bundle.value=null;busy.value=false;error.value='';evidenceOpen.value=false;evidence.value=null;rawOpen.value=false;rawTask.value=null;outcome.value=null;comment.value='';feedbackId.value=null;}
const session=useOperationsSession(props,()=>{reset();emit('invalidate');}),allowed=session.allowed,source=computed(()=>bundle.value?.parts?.source.value),result=computed(()=>bundle.value?.parts?.result.value),shown=v=>v===null||v===undefined?'未知':String(v);
const feedbackReady=computed(()=>!!result.value&&['accepted','modified','rejected'].includes(outcome.value)&&operationsScalar(comment.value)&&Array.from(comment.value).length<=2000&&operationsBytes(comment.value)<=8000&&(outcome.value!=='modified'||Array.from(comment.value).length>=3));
function schedule(){stop();if(allowed.value&&bundle.value&&['queued','running'].includes(bundle.value.metadata.status)&&!evidenceOpen.value&&!rawOpen.value&&!busy.value)timer=setTimeout(refresh,1200);}
async function readCurrent(t){return loadOperationsTaskBundle(props.runId,{selection:props.selection,auditOnly:props.auditOnly,current:()=>session.current(t)});}
async function refresh(){stop();session.advance();reset();if(!allowed.value||!operationsId(props.runId))return;const t=session.ticket();busy.value=true;try{const next=await readCurrent(t);if(!session.current(t))return;bundle.value=next;emit('status',next.metadata);}catch(e){if(session.current(t)){reset();error.value=e.message||'当前任务无法核对';emit('invalidate');}}finally{if(session.current(t)){busy.value=false;schedule();}}}
async function freshView(){if(!bundle.value?.parts||!allowed.value||busy.value)return null;stop();const t=session.ticket(),version=++viewEpoch;const fresh=await readCurrent(t);if(!session.current(t)||version!==viewEpoch||!fresh.parts)return null;bundle.value=fresh;return{fresh,current:()=>session.current(t)&&version===viewEpoch};}
async function show(span){closeEvidence();if(!allowed.value||!bundle.value?.parts)return;evidenceOpen.value=true;try{const read=await freshView();if(!read||!read.current()||!evidenceOpen.value)return;const found=await resolveOperationsCitation(span,read.fresh.parts.source.value,{current:()=>read.current()&&evidenceOpen.value});if(!read.current()||!evidenceOpen.value)return;if(!found)throw new Error('逐字引文无法核对');evidence.value=found;}catch(e){if(allowed.value&&evidenceOpen.value){session.invalidate();error.value=e.message||'当前来源不可用';emit('invalidate');}}}
async function openRaw(){closeRaw();if(!allowed.value||!bundle.value?.parts)return;rawOpen.value=true;try{const read=await freshView();if(read?.current()&&rawOpen.value)rawTask.value=read.fresh.parts.task.value;}catch(e){if(allowed.value&&rawOpen.value){session.invalidate();error.value=e.message||'当前原始TEXT不可用';emit('invalidate');}}}
async function feedback(){if(!feedbackReady.value||busy.value)return;const t=session.ticket(),run=props.runId,chosen=outcome.value,note=comment.value;busy.value=true;stop();try{const fresh=await readCurrent(t);if(!session.current(t)||!fresh.parts?.result.value)return;const response=(await feedbackOperationsTask(run,chosen,note)).data;if(!session.current(t)||chosen!==outcome.value||note!==comment.value)return;if(!operationsKeys(response,['feedback_id'])||!operationsId(response.feedback_id))throw new Error('反馈回执无法核对');feedbackId.value=response.feedback_id;}catch(e){if(session.current(t)){session.invalidate();error.value=e.message||'当前反馈不能提交';emit('invalidate');}}finally{if(session.current(t)){busy.value=false;schedule();}}}
async function cancel(){if(busy.value||!bundle.value||!['queued','running'].includes(bundle.value.metadata.status))return;const t=session.ticket();busy.value=true;stop();try{const response=(await cancelOperationsTask(props.runId)).data;if(!session.current(t))return;if(!verifyOperationsCancelAck(response,{runId:props.runId}))throw new Error('实际取消回执无法核对');await refresh();}catch(e){if(session.current(t)){session.invalidate();error.value=e.message||'当前任务不可取消';emit('invalidate');}}finally{if(session.current(t))busy.value=false;}}
watch([()=>props.runId,()=>props.selection],refresh,{immediate:true,deep:true,flush:'post'});
</script>
<style scoped>section{display:grid;gap:12px}article{border:1px solid #dcdfe6;padding:12px}pre,blockquote{white-space:pre-wrap;overflow-wrap:anywhere;max-height:45vh;overflow:auto}</style>
