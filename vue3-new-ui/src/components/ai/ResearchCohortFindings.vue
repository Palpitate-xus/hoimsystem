<template>
 <section aria-label="科研队列原记录结果与待核问题">
  <p v-if="!ready" role="status">正在核对本次队列资料与结果。</p>
  <template v-else>
   <p>以下匹配结果基于本次记录与条件；研究入组仍需另行审核。</p><details><summary>来源与任务核验详情</summary><p>已核对本次来源、研究范围、原文及Prompt版本。</p></details>
   <p>明确患者集合 {{ data.source.counts.declared_patients }}；原记录条件匹配 {{ data.source.counts.recorded_true }}；原记录条件不匹配 {{ data.source.counts.recorded_false }}；未知 {{ data.source.counts.unknown }}。</p>
   <details><summary>Prompt版本详情</summary><p>实际Prompt来源：{{ data.task.prompt_snapshot.origin==='packaged_catalog'?'随包默认版本（无数据库Prompt版本行）':'已保存不可变版本' }}；版本 {{ data.task.prompt_snapshot.prompt_version }}。</p></details>
   <template v-if="data.result"><p>本次提出 {{ data.result.question_draft.questions.length }} 项待核问题。</p><details><summary>任务摘要原文</summary><p v-if="noticeText(data.result.summary)">{{ noticeText(data.result.summary) }}</p></details><p v-if="!data.result.question_draft.questions.length">本次未返回待核问题。</p>
    <article v-for="(question,index) in data.result.question_draft.questions" :key="index" aria-label="模型部分待核问题"><h4>{{ question.title }}</h4><p>{{ question.observation }}</p><p>{{ question.clarification_question }}</p><el-button v-for="(citation,j) in question.citations" :key="j" @click="show(citation)">核对第{{ index+1 }}条问题的逐字引文{{ j+1 }}</el-button></article>
    <ul><li v-for="(text,index) in noticeList(data.result.limitations)" :key="index">{{ text }}</li></ul>
   </template><p v-else>任务尚无完整成功结果；未把排队、失败或未知用量视为模型完成。</p>
   <el-button @click="rawOpen=!rawOpen">{{ rawOpen?'收起任务技术详情':'任务技术详情' }}</el-button><template v-if="rawOpen"><pre aria-label="科研任务原始输入TEXT">{{ data.task.input_json }}</pre><pre aria-label="科研任务原始证据TEXT">{{ data.task.evidence_json }}</pre><pre aria-label="科研任务原始元数据TEXT">{{ data.task.context_metadata_json }}</pre><p>原SHA按各字符串UTF8逐字核对，未将重新序列化的对象称为原TEXT。</p></template>
  </template>
  <p v-if="error" role="alert">{{ error }}</p>
  <el-dialog :model-value="evidenceOpen" title="本次研究公开来源逐字引文" :close-on-click-modal="false" @update:model-value="value=>!value&&closeEvidence()"><template v-if="evidence"><p>引用位置按本次模型输入的Unicode码点计算。</p><blockquote>{{ evidence.quote }}</blockquote><pre>{{ evidence.target.text }}</pre><p>范围 [{{ evidence.start }}, {{ evidence.end }})；类型 {{ evidence.target.category }}。</p></template></el-dialog>
 </section>
</template>
<script setup>
import { noticeText, noticeList } from "@/utils/noticeText.cjs";
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
