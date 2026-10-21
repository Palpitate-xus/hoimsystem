<template>
 <section aria-label="明确人工编辑表单">
  <p>按原文 Unicode codepoint 位置选择。不会自动采用 AI 候选、合并重叠区间或识别其他姓名。</p>
  <fieldset :disabled="busy">
   <el-form-item label="明确原文字段"><el-select v-model="field" aria-label="明确原文字段" placeholder="请明确选择"><el-option v-for="d in source.public_source.documents" :key="d.source_id" :label="d.field+' · '+(d.codepoint_length===null?'未记录':d.codepoint_length+' CP')" :value="d.source_id" /></el-select></el-form-item>
   <el-form-item label="起始 codepoint（含）"><el-input v-model="start" aria-label="起始codepoint" /></el-form-item>
   <el-form-item label="结束 codepoint（不含）"><el-input v-model="end" aria-label="结束codepoint" /></el-form-item>
   <el-form-item label="本次人工选择动作"><el-select v-model="action" aria-label="本次人工选择动作" placeholder="请明确选择"><el-option label="替换为固定[已遮蔽]" value="mask"/><el-option label="移除此段" value="remove"/></el-select></el-form-item>
   <p>由原文字段逐字取得的待选内容：</p><pre aria-label="待选逐字原文">{{ quote }}</pre>
   <el-button @click="add">加入明确编辑清单</el-button>
   <ol aria-label="明确人工编辑清单"><li v-for="(e,i) in edits" :key="i">{{ e.document_source_id }} [{{ e.start }},{{ e.end }}) {{ e.action==='mask'?'遮蔽':'移除' }}<pre>{{ e.quote }}</pre><el-button @click="remove(i)">移除此项选择</el-button></li></ol>
   <el-button @click="sort">按原文顺序整理明确编辑</el-button>
   <el-checkbox v-model="confirmed" aria-label="确认完整编辑清单">确认已逐项核对完整编辑清单，空清单表示明确保持原文</el-checkbox>
   <el-checkbox v-model="unselected" aria-label="确认未选字段不在范围">确认未选字段不在本次覆盖范围</el-checkbox>
   <el-form-item label="本次完整人工选择依据"><el-input v-model="note" type="textarea" aria-label="本次完整人工选择依据" /></el-form-item>
   <el-button @click="preview">预览本次明确人工编辑</el-button><el-button @click="submit">登记人工编辑草稿</el-button>
  </fieldset>
  <p v-if="error" role="alert">{{ error }}</p>
  <div v-if="output" aria-label="完整明确编辑预览"><p>完整选定输出仍有残余风险；没有匿名保证。</p><div v-for="d in output.documents" :key="d.source_id"><p>{{ d.field }}，{{ d.text===null?'未记录':d.codepoint_length+' CP' }}</p><pre>{{ d.text }}</pre></div></div>
 </section>
</template>
<script setup>
import {computed,onBeforeUnmount,ref,watch} from 'vue';
import {applyDeidentificationEdits,deidentificationRequestValid} from '@/api/ai/deidentificationSources';
import {tupleCompare} from '@/api/ai/deidentificationCore';
const props=defineProps({source:{type:Object,required:true},busy:Boolean}),emit=defineEmits(['submit','change']);
const field=ref(null),start=ref(''),end=ref(''),action=ref(null),edits=ref([]),confirmed=ref(false),unselected=ref(false),note=ref(''),error=ref(''),output=ref(null);let version=0;
const integer=s=>typeof s==='string'&&/^(0|[1-9]\d*)$/.test(s)&&Number.isSafeInteger(Number(s))?Number(s):null;
const doc=computed(()=>props.source.public_source.documents.find(d=>d.source_id===field.value)),quote=computed(()=>{const a=integer(start.value),b=integer(end.value),d=doc.value;return d?.text!==null&&typeof d?.text==='string'&&a!==null&&b!==null&&a<b&&b<=d.codepoint_length?Array.from(d.text).slice(a,b).join(''):'';});
function add(){if(props.busy)return;const d=doc.value,e={document_source_id:field.value,text_hash:d?.text_hash,start:integer(start.value),end:integer(end.value),quote:quote.value,action:action.value};if(!deidentificationRequestValid('SpanEdit',e)){error.value='请明确选择原文字段、有效CP区间和人工动作。';return;}edits.value.push(e);field.value=null;start.value='';end.value='';action.value=null;}
function remove(i){if(!props.busy)edits.value.splice(i,1);}
function sort(){if(!props.busy)edits.value.sort((a,b)=>tupleCompare([a.document_source_id,a.start,a.end],[b.document_source_id,b.start,b.end]));}
const body=()=>({case_id:props.source.case_id,expected_content_hash:props.source.content_hash,expected_governance_hash:props.source.governance_hash,edits:structuredClone(edits.value.map(e=>({...e}))),selection_confirmed:confirmed.value,unselected_fields_not_covered:unselected.value,basis_note:note.value});
async function preview(){if(props.busy)return;const t=++version;error.value='';output.value=null;try{const value=await applyDeidentificationEdits(props.source.public_source.documents,edits.value);if(t===version)output.value=value;}catch{if(t===version)error.value='逐字位置、整件SHA、排序或重叠编辑无法核对，请重新明确选择。';}}
async function submit(){if(props.busy)return;const value=body();if(!deidentificationRequestValid('ReviewCreate',value)){error.value='请确认完整清单和未选范围，并填写不少于20字的完整依据。';return;}const t=++version;try{await applyDeidentificationEdits(props.source.public_source.documents,value.edits);if(t===version)emit('submit',value);}catch{if(t===version)error.value='编辑区间重叠或逐字依据不符，未提交。';}}
watch([field,start,end,action,edits,confirmed,unselected,note],()=>{version++;output.value=null;error.value='';emit('change');},{deep:true,flush:'sync'});
onBeforeUnmount(()=>{version++;});
</script>
<style scoped>fieldset{border:1px solid #ddd;padding:12px}.el-input,.el-select{width:100%}pre{white-space:pre-wrap;overflow-wrap:anywhere;max-height:35vh;overflow:auto}.el-checkbox{display:flex;height:auto;white-space:normal;margin:12px 0}[role=alert]{color:#b42318}</style>
