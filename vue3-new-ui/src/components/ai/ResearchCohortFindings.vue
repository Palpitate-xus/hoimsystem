<template>
 <section aria-label="科研队列原记录结果与待核问题">
  <p v-if="!ready" role="status">尚未核对当前任务的独立完整来源、冻结Task与结果。</p>
  <template v-else>
   <p>当前完整Source、私有Case、原始TEXT和冻结Prompt版本已核对；技术审核不代表研究入组、伦理批准、因果或匿名认证。</p>
   <p>明确患者集合 {{ data.source.counts.declared_patients }}；原记录条件匹配 {{ data.source.counts.recorded_true }}；原记录条件不匹配 {{ data.source.counts.recorded_false }}；未知 {{ data.source.counts.unknown }}。</p>
   <p>实际Prompt来源：{{ data.task.prompt_snapshot.origin==='packaged_catalog'?'随包默认版本（无数据库Prompt版本行）':'已保存不可变版本' }}；版本 {{ data.task.prompt_snapshot.prompt_version }}。</p>
   <template v-if="data.result"><p>{{ data.result.summary }}</p><p v-if="!data.result.question_draft.questions.length">本次没有返回待核问题；这不证明所有记录或条件均已核实。</p>
    <article v-for="(question,index) in data.result.question_draft.questions" :key="index" aria-label="模型部分待核问题"><h4>{{ question.title }}</h4><p>{{ question.observation }}</p><p>{{ question.clarification_question }}</p><el-button v-for="(citation,j) in question.citations" :key="j" @click="show(citation)">核对第{{ index+1 }}条问题的逐字引文{{ j+1 }}</el-button></article>
    <ul><li v-for="(text,index) in data.result.limitations" :key="index">{{ text }}</li></ul>
   </template><p v-else>任务尚无完整成功结果；未把排队、失败或未知用量视为模型完成。</p>
   <el-button @click="rawOpen=!rawOpen">{{ rawOpen?'收起本任务原始TEXT':'显式展开本任务原始TEXT' }}</el-button><template v-if="rawOpen"><pre aria-label="科研任务原始输入TEXT">{{ data.task.input_json }}</pre><pre aria-label="科研任务原始证据TEXT">{{ data.task.evidence_json }}</pre><pre aria-label="科研任务原始元数据TEXT">{{ data.task.context_metadata_json }}</pre><p>原SHA按各字符串UTF8逐字核对，未将重新序列化的对象称为原TEXT。</p></template>
  </template>
  <p v-if="error" role="alert">{{ error }}</p>
  <el-dialog :model-value="evidenceOpen" title="本次研究公开来源逐字引文" :close-on-click-modal="false" @update:model-value="value=>!value&&closeEvidence()"><template v-if="evidence"><p>仅为本次公开证据字符串的Unicode码点切片，不声称已披露完整原临床字段。</p><blockquote>{{ evidence.quote }}</blockquote><pre>{{ evidence.target.text }}</pre><p>范围 [{{ evidence.start }}, {{ evidence.end }})；类型 {{ evidence.target.category }}。</p></template></el-dialog>
 </section>
</template>
<script setup>
import {computed,onActivated,onBeforeUnmount,onDeactivated,onMounted,ref,toRaw,watch} from 'vue';
import {useStore} from 'vuex';
import {supportCanonical as canonical} from '@/api/inpatientSupport';
import {verifyResearchTaskParts} from '@/api/ai/researchCohortTasks';
import {resolveResearchCitation} from '@/api/ai/researchCohortResults';
const props=defineProps({metadata:{type:Object,required:true},parts:{type:Object,required:true},auditOnly:{type:Boolean,default:false},active:{type:Boolean,default:true}}),emit=defineEmits(['invalidate']),store=useStore(),ready=ref(false),data=ref(null),error=ref(''),rawOpen=ref(false),evidenceOpen=ref(false),evidence=ref(null),kept=ref(true),blocked=ref(false);
const identity=computed(()=>canonical([store.state.user?.accessToken??null,store.state.user?.username??null,store.state.user?.permissions??null,props.auditOnly])),authorized=computed(()=>{const r=store.state.user?.permissions;return !blocked.value&&props.active&&kept.value&&typeof store.state.user?.accessToken==='string'&&store.state.user.accessToken.length>0&&Array.isArray(r)&&r.length>0&&new Set(r).size===r.length&&r.every(x=>['super_admin','admin','director'].includes(x))&&(!props.auditOnly||r.includes('super_admin'));});
let mounted=false,epoch=0,evidenceEpoch=0;function closeEvidence(){evidenceEpoch++;evidenceOpen.value=false;evidence.value=null;}function clear(){epoch++;ready.value=false;data.value=null;rawOpen.value=false;closeEvidence();error.value='';}
async function validate(){clear();if(!mounted||!authorized.value)return;const stamp=++epoch,subject=identity.value,metadataRef=props.metadata,partsRef=props.parts,metadata=structuredClone(toRaw(metadataRef)),parts=structuredClone(toRaw(partsRef)),current=()=>mounted&&authorized.value&&stamp===epoch&&subject===identity.value&&metadataRef===props.metadata&&partsRef===props.parts;try{if(!await verifyResearchTaskParts(metadata,parts,{auditOnly:props.auditOnly,current}))throw new Error('独立科研任务分件闭集或原文证明无效');if(!current())return;data.value=parts;ready.value=true;}catch{if(current()){clear();error.value='完整科研任务分件无法核对，未显示旧临床引文或结果。';emit('invalidate');}}}
async function show(citation){closeEvidence();if(!ready.value||!authorized.value)return;const stamp=++evidenceEpoch,version=epoch,subject=identity.value,current=()=>mounted&&authorized.value&&ready.value&&version===epoch&&stamp===evidenceEpoch&&subject===identity.value;evidenceOpen.value=true;const target=await resolveResearchCitation(citation,data.value.source,{current});if(!current()||!evidenceOpen.value)return;if(!target){closeEvidence();error.value='逐字引文无法核对。';return;}evidence.value={...citation,target};}
watch(identity,()=>{blocked.value=true;clear();emit('invalidate');},{flush:'sync'});watch([()=>props.active,kept],()=>{if(!props.active||!kept.value){blocked.value=true;clear();emit('invalidate');}},{flush:'sync'});watch([()=>props.metadata,()=>props.parts],()=>{blocked.value=false;validate();},{deep:true,flush:'sync'});onMounted(()=>{mounted=true;validate();});onActivated(()=>{kept.value=true;});onDeactivated(()=>{kept.value=false;clear();});onBeforeUnmount(()=>{mounted=false;clear();});
</script>
<style scoped>pre,blockquote{white-space:pre-wrap;overflow-wrap:anywhere;max-height:50vh;overflow:auto}article{border:1px solid #dcdfe6;padding:12px;margin:12px 0}[role=alert]{color:#b42318}</style>
