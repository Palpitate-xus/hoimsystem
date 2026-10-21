<template>
 <section aria-label="运维原生任务技术目录">
  <p>目录为有界分页技术记录，不代表已授权读取材料或结果；每次打开均重新核对当前来源。</p>
  <el-button :disabled="!allowed||busy" @click="load">读取当前任务目录</el-button><p v-if="error" role="alert">{{error}}</p>
  <el-table v-if="allowed&&directory" :data="directory.items" empty-text="暂无当前目录项"><el-table-column prop="run_id" label="原任务"/><el-table-column prop="status" label="技术状态"/><el-table-column label="实际已报告用量"><template #default="{row}">{{shown(row.usage?.input_tokens)}} / {{shown(row.usage?.output_tokens)}}</template></el-table-column><el-table-column label="操作"><template #default="{row}"><el-button @click="inspect(row)">核对本条完整任务</el-button></template></el-table-column></el-table>
  <template v-if="directory"><el-button :disabled="busy||page===1" @click="page--;load()">上一页</el-button><span>第{{page}}页</span><el-button :disabled="busy||!directory.has_more" @click="page++;load()">下一页</el-button></template>
  <el-dialog :model-value="opened" title="本条运维任务与当前来源" :close-on-click-modal="false" :before-close="done=>{close();done();}"><OperationsSupportFindings v-if="opened&&runId" :key="runId" :run-id="runId" :active="allowed&&opened" :expected-case-id="caseId" :config-revision="configRevision" @invalidate="close"/></el-dialog>
 </section>
</template>
<script setup>
import{ref,toRaw,watch}from'vue';import{useOperationsSession}from'./useOperationsSession';import OperationsSupportFindings from'./OperationsSupportFindings.vue';import{getOperationsTasks,verifyOperationsTaskDirectory,verifyOperationsTaskMetadata}from'@/api/ai/operationsSupportTasks';import{operationsCanonical,operationsId}from'@/api/ai/operationsSupportCore';
const props=defineProps({caseId:{type:String,default:null},active:{type:Boolean,default:true},configRevision:{type:[String,Number],default:null}}),directory=ref(null),page=ref(1),busy=ref(false),error=ref(''),opened=ref(false),runId=ref(null);let listed=new WeakMap();
function close(){opened.value=false;runId.value=null;}
function reset(){directory.value=null;busy.value=false;error.value='';listed=new WeakMap();close();}
const session=useOperationsSession(props,reset),allowed=session.allowed,shown=v=>v===undefined||v===null?'未知':String(v);
async function load(){if(!allowed.value||busy.value||props.caseId!==null&&!operationsId(props.caseId))return;session.advance();reset();const t=session.ticket();busy.value=true;try{const value=(await getOperationsTasks({caseId:props.caseId,page:page.value,size:20})).data;if(!session.current(t))return;if(!verifyOperationsTaskDirectory(value,{page:page.value,size:20}))throw new Error('当前技术任务目录无法核对');directory.value=value;listed=new WeakMap(value.items.map(v=>[v,operationsCanonical(v)]));}catch(e){if(session.current(t)){reset();error.value=e.message||'任务目录不可用';}}finally{if(session.current(t))busy.value=false;}}
function inspect(row){if(!allowed.value||listed.get(toRaw(row))!==operationsCanonical(row)||!verifyOperationsTaskMetadata(row))return;close();runId.value=row.run_id;opened.value=true;}
watch(()=>props.caseId,()=>{session.invalidate();page.value=1;},{flush:'sync'});
</script>
