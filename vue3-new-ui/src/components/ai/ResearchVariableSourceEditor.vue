<template>
 <fieldset :disabled="disabled" aria-label="变量字典类型表单"><legend>明确变量字典原件</legend>
  <el-form-item label="字典标题"><el-input :model-value="modelValue.title??''" aria-label="字典标题" @update:model-value="set('title',$event)" /></el-form-item>
  <el-form-item label="完整研究用途"><el-input :model-value="modelValue.purpose??''" type="textarea" aria-label="完整研究用途" @update:model-value="set('purpose',$event)" /></el-form-item>
  <el-button :disabled="variables.length>=64" @click="add">添加明确变量</el-button>
  <fieldset v-for="(v,index) in variables" :key="index"><legend>变量 {{ index+1 }}</legend>
   <el-form-item label="变量键"><el-input :model-value="v.variable_key??''" :aria-label="'变量键 '+(index+1)" @update:model-value="field(index,'variable_key',$event)" /></el-form-item>
   <el-form-item label="变量显示名称"><el-input :model-value="v.label??''" :aria-label="'变量显示名称 '+(index+1)" @update:model-value="field(index,'label',$event)" /></el-form-item>
   <el-form-item label="明确原记录族"><el-select :model-value="v.family" :aria-label="'明确原记录族 '+(index+1)" @update:model-value="family(index,$event)"><el-option v-for="name in families" :key="name" :value="name" :label="labels[name]||name" /></el-select></el-form-item>
   <el-form-item label="明确原字段"><el-select :model-value="v.field" :aria-label="'明确原字段 '+(index+1)" :disabled="!v.family" @update:model-value="column(index,$event)"><el-option v-for="(type,name) in fixed.variable_fields[v.family]||{}" :key="name" :value="name" :label="name+' · '+type" /></el-select></el-form-item>
   <p>原字段类型：{{ v.value_kind??'待明确原字段' }}。保留原字面值，不作单位转换。</p>
   <template v-if="v.family&&v.family!=='patient_demographics'"><el-form-item label="原记录窗口首日"><el-input :model-value="v.record_window?.date_from??''" :aria-label="'原记录窗口首日 '+(index+1)" @update:model-value="windowField(index,'date_from',$event)" /></el-form-item><el-form-item label="原记录窗口末日"><el-input :model-value="v.record_window?.date_to??''" :aria-label="'原记录窗口末日 '+(index+1)" @update:model-value="windowField(index,'date_to',$event)" /></el-form-item><p>原历史日期的时区未知，不转换为UTC或声称当时已知。</p></template>
   <p v-else-if="v.family==='patient_demographics'">静态字段没有事件时钟，窗口明确为 null。</p>
   <el-form-item label="原声明单位"><el-radio-group :model-value="v.declared_unit===null?'unknown':typeof v.declared_unit==='string'?'recorded':null" :aria-label="'单位声明状态 '+(index+1)" @update:model-value="field(index,'declared_unit',$event==='unknown'?null:'')"><el-radio label="unknown">未知，保留null</el-radio><el-radio v-if="v.value_kind==='verbatim_text'" label="recorded">明确填写声明原文</el-radio></el-radio-group><el-input v-if="typeof v.declared_unit==='string'" :model-value="v.declared_unit" :aria-label="'原声明单位 '+(index+1)" @update:model-value="field(index,'declared_unit',$event)" /></el-form-item>
   <el-form-item label="完整抽取口径与依据"><el-input :model-value="v.extraction_instruction??''" type="textarea" :aria-label="'完整抽取口径与依据 '+(index+1)" @update:model-value="field(index,'extraction_instruction',$event)" /></el-form-item>
   <el-button @click="remove(index)">删除变量 {{ index+1 }}</el-button>
  </fieldset>
  <p>变量键须按升序且不重复；全部原记录候选保留，不自动选择最新或有利记录。</p>
  <el-form-item label="完整字典登记依据"><el-input :model-value="modelValue.basis_note??''" type="textarea" aria-label="完整字典登记依据" @update:model-value="set('basis_note',$event)" /></el-form-item>
 </fieldset>
</template>
<script setup>
import {computed} from 'vue';
import {researchVariableFixed as fixed} from '@/api/ai/researchVariableProofs';
const props=defineProps({modelValue:{type:Object,required:true},families:{type:Array,required:true},disabled:{type:Boolean,default:false}}),emit=defineEmits(['update:modelValue']),variables=computed(()=>props.modelValue.variables||[]);
const labels={patient_demographics:'有限人口学原字段',registrations:'挂号原记录',admissions:'住院原记录',medical_records:'门诊病历原记录',structured_medical_records:'结构化病历原记录'};
const set=(key,value)=>emit('update:modelValue',{...props.modelValue,[key]:value});
function field(index,key,value){const rows=variables.value.map(v=>({...v}));rows[index][key]=value;set('variables',rows);}
function add(){if(variables.value.length>=64)return;set('variables',[...variables.value,{record_policy:'all_recorded_candidates_no_automatic_winner',unit_policy:'preserve_original_literal_no_conversion',missingness_policy:'explicit_literal_evidence_else_unknown'}]);}
function remove(index){set('variables',variables.value.filter((_,n)=>n!==index));}
function family(index,name){if(!props.families.includes(name))return;const rows=variables.value.map(v=>({...v})),v=rows[index];v.family=name;delete v.field;delete v.value_kind;delete v.declared_unit;v.record_window=name==='patient_demographics'?null:{time_basis:'legacy_naive_calendar_dates_timezone_unknown'};v.temporal_policy=name==='patient_demographics'?'static_subject_field_without_event_clock':'explicit_recorded_window_unknown_clock_separate';set('variables',rows);}
function column(index,name){const v=variables.value[index],type=fixed.variable_fields[v.family]?.[name];if(!type)return;const rows=variables.value.map(v=>({...v}));rows[index]={...v,field:name,value_kind:type};delete rows[index].declared_unit;set('variables',rows);}
function windowField(index,key,value){field(index,'record_window',{...variables.value[index].record_window,[key]:value});}
</script>
<style scoped>fieldset{border:1px solid #dcdfe6;padding:12px;margin:12px 0}.el-select{width:100%}</style>
