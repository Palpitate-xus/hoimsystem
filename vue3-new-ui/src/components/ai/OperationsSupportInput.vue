<template>
 <section aria-label="明确运维材料集输入">
  <p v-if="!allowed||!entryValid">当前材料引用或会话无效，请重新选择运维材料。</p>
  <template v-else>
   <p>请选择完整的当前受审材料集，不自动选择首项。材料可读与允许模型处理是分别核验的条件。</p>
   <div v-if="initialReferences&&!entryCleared"><p>入口材料集：{{initialReferences.operations_case_id}}</p><el-button :disabled="busy" @click="choose(initialReferences)">核对入口指定材料集</el-button><el-button @click="forgetEntry">清除入口绑定，另选材料集</el-button></div>
   <p v-if="error" role="alert">{{error}}</p>
   <p v-if="selected">已选择材料集{{selected.operations_case_id}}，共{{metadata.source_count}}份已发布文档。</p><details v-if="selected"><summary>材料核验标识</summary><p>公开SHA：{{metadata.public_hash}}</p></details>
   <el-button v-if="selected" :disabled="busy" @click="choose(selected)">重新核对当前公开材料</el-button><el-button v-if="selected" @click="clear">清除所选材料集</el-button>
   <OperationsSupportSources v-for="instance in [sourceKey]" :key="instance" :active="allowed&&entryValid" :config-revision="configRevision" @select="choose" @invalidate="invalidateSource(instance)" @source-changed="invalidateSource(instance)" />
   <el-collapse v-if="source"><el-collapse-item title="本次完整公开材料（不是受控原件）" name="source"><article v-for="doc in source.documents" :key="doc.source_id"><h3>{{doc.title}}</h3><pre>{{doc.text}}</pre></article></el-collapse-item></el-collapse>
  </template>
 </section>
</template>
<script setup>
import {computed,ref,watch} from 'vue';
import OperationsSupportSources from './OperationsSupportSources.vue';
import {useOperationsSession} from './useOperationsSession';
import {getOperationsCase,getOperationsCasePart,verifyOperationsCaseMetadata,verifyOperationsCaseParts} from '@/api/ai/operationsSupportSources';
import {operationsReferencesValid} from '@/api/ai/operationsSupportTasks';
const props=defineProps({active:{type:Boolean,default:true},initialReferences:{type:Object,default:null},configRevision:{type:[String,Number],default:null}}),emit=defineEmits(['selection','availability','invalidate']);
const selected=ref(null),metadata=ref(null),source=ref(null),busy=ref(false),error=ref(''),entryCleared=ref(false),sourceKey=ref(0);
function reset(){selected.value=null;metadata.value=null;source.value=null;busy.value=false;error.value='';emit('selection',null);emit('availability',false);emit('invalidate');}
const session=useOperationsSession(props,()=>{reset();sourceKey.value++;}),allowed=session.allowed,entryValid=computed(()=>props.initialReferences===null||operationsReferencesValid(props.initialReferences));
function invalidateSelection(){session.advance();reset();}
function invalidateSource(instance){if(instance===sourceKey.value)invalidateSelection();}
function clear(){session.invalidate();}
function forgetEntry(){entryCleared.value=true;clear();}
async function choose(reference){
 if(!allowed.value||!entryValid.value||!operationsReferencesValid(reference)||busy.value)return;
 if(props.initialReferences!==null&&!entryCleared.value&&reference.operations_case_id!==props.initialReferences.operations_case_id){clear();error.value='本次来源与明确入口不同，请先清除入口绑定再选择其它材料集';return;}
 session.advance();reset();const t=session.ticket(),current=()=>session.current(t)&&entryValid.value;busy.value=true;
 try{
  const m=(await getOperationsCase(reference.operations_case_id)).data;if(!current()||!verifyOperationsCaseMetadata(m)||m.case_id!==reference.operations_case_id||!m.source_accessible)throw new Error('当前材料集不可用');
  const p=await getOperationsCasePart(m.case_id,'source');if(!current()||!await verifyOperationsCaseParts(m,{source:p},{current}))throw new Error('完整公开来源或当前版本无法核对');
  metadata.value=m;source.value=p.value;selected.value={operations_case_id:m.case_id};emit('selection',selected.value);emit('availability',true);
 }catch(e){if(current()){reset();error.value=e.message||'当前来源不可用';}}finally{if(current())busy.value=false;}
}
watch(()=>JSON.stringify(props.initialReferences),()=>{entryCleared.value=false;clear();},{flush:'sync'});
</script>
<style scoped>section{display:grid;gap:12px}pre{white-space:pre-wrap;overflow-wrap:anywhere;max-height:40vh;overflow:auto}</style>
