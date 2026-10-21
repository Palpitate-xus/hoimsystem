<template>
 <fieldset :aria-label="'条件节点'+path"><legend>条件 {{ path }}</legend>
  <el-select :model-value="modelValue?.op??null" :aria-label="'条件类型'+path" placeholder="明确选择条件类型" @update:model-value="changeType"><el-option value="recorded_scalar_equal" label="原记录整数相等" /><el-option value="recorded_date_compare" label="原记录日历日期比较" /><el-option value="recorded_text_contains" label="原文包含明确字面量" /><el-option v-if="depth<8" value="all" label="全部条件满足" /><el-option v-if="depth<8" value="any" label="任一条件满足" /><el-option v-if="depth<8" value="not" label="条件取反，未知仍为未知" /></el-select>
  <template v-if="modelValue&&['all','any'].includes(modelValue.op)"><ResearchCohortCriteriaNode v-for="(child,index) in modelValue.children" :key="index" :model-value="child" :depth="depth+1" :path="path+'.'+index" @update:model-value="value=>changeChild(index,value)" /><el-button :disabled="modelValue.children.length>=63" @click="addChild">添加一个子条件</el-button><el-button v-if="modelValue.children.length>1" @click="removeLast">移除末项子条件</el-button></template>
  <ResearchCohortCriteriaNode v-else-if="modelValue?.op==='not'" :model-value="modelValue.child" :depth="depth+1" :path="path+'.not'" @update:model-value="value=>patch({child:value})" />
  <template v-else-if="modelValue">
   <el-select :model-value="modelValue.family" :aria-label="'记录族'+path" placeholder="明确选择记录族" @update:model-value="value=>patch({family:value,field:null})"><el-option v-for="family in availableFamilies" :key="family" :value="family" :label="families[family]" /></el-select>
   <el-select :model-value="modelValue.field" :aria-label="'记录字段'+path" placeholder="明确选择原记录字段" @update:model-value="value=>patch({field:value})"><el-option v-for="field in fields" :key="field" :value="field" :label="fieldLabels[field]||field" /></el-select>
   <el-input-number v-if="modelValue.op==='recorded_scalar_equal'" :model-value="modelValue.expected" :min="-2147483648" :max="2147483647" :precision="0" :aria-label="'明确原记录整数'+path" @update:model-value="value=>patch({expected:value??null})" />
   <template v-else-if="modelValue.op==='recorded_date_compare'"><el-select :model-value="modelValue.comparison" :aria-label="'日期比较'+path" placeholder="明确选择比较" @update:model-value="value=>patch({comparison:value})"><el-option value="before" label="早于" /><el-option value="on" label="同一天" /><el-option value="after" label="晚于" /></el-select><el-input :model-value="modelValue.expected" :aria-label="'明确日历日期'+path" placeholder="YYYY-MM-DD，不推断历史时区" @update:model-value="value=>patch({expected:value})" /></template>
   <el-input v-else :model-value="modelValue.literal" type="textarea" :aria-label="'明确原文字面量'+path" placeholder="逐字输入需核对的文本，保留否定和换行" @update:model-value="value=>patch({literal:value})" />
   <el-select :model-value="modelValue.quantifier" :aria-label="'记录量词'+path" placeholder="明确选择记录量词" @update:model-value="value=>patch({quantifier:value})"><el-option value="any_record" label="至少一条记录符合" /><el-option value="every_record" label="全部所列记录符合，空集合保持未知" /></el-select>
  </template>
 </fieldset>
</template>
<script setup>
import {computed} from 'vue';
import {researchCohortPolicy} from '@/api/ai/researchCohortSources';
const props=defineProps({modelValue:{type:Object,default:null},depth:{type:Number,default:1},path:{type:String,default:'root'}}),emit=defineEmits(['update:modelValue']);
const families={patient_demographics:'有限人口学字段',registrations:'挂号记录',admissions:'住院记录',medical_records:'门诊病历',structured_medical_records:'结构化病历'},fieldLabels={sex:'原记录性别编码',birthday:'原记录出生日期',symptom:'原记录症状',result:'原记录诊断结果',status:'原记录状态编码',specialist:'原记录专科标志',time:'原记录时间',admission_time:'入院时间',discharge_time:'出院时间',create_time:'创建时间',consultation_time:'就诊时间',sign_time:'签署时间',update_time:'更新时间',chief_complaint:'主诉',present_illness:'现病史',past_history:'既往史',personal_history:'个人史',family_history:'家族史',physical_exam:'体格检查',auxiliary_exam:'辅助检查',diagnosis:'诊断',treatment_plan:'治疗计划',admission_diagnosis:'入院诊断',discharge_diagnosis:'出院诊断',admission_type:'入院类型编码',record_type:'病历类型编码'};
const table=computed(()=>props.modelValue?.op==='recorded_scalar_equal'?researchCohortPolicy.scalar_fields:props.modelValue?.op==='recorded_date_compare'?researchCohortPolicy.date_fields:researchCohortPolicy.text_fields),availableFamilies=computed(()=>Object.keys(table.value)),fields=computed(()=>table.value[props.modelValue?.family]||[]);
const clone=v=>JSON.parse(JSON.stringify(v));
function changeType(op){if(['all','any'].includes(op))emit('update:modelValue',{op,children:[null]});else if(op==='not')emit('update:modelValue',{op,child:null});else if(op==='recorded_scalar_equal')emit('update:modelValue',{op,family:null,field:null,expected:null,quantifier:null});else if(op==='recorded_date_compare')emit('update:modelValue',{op,family:null,field:null,comparison:null,expected:'',quantifier:null,time_basis:'legacy_naive_calendar_dates_timezone_unknown'});else if(op==='recorded_text_contains')emit('update:modelValue',{op,family:null,field:null,literal:'',quantifier:null});}
function patch(value){emit('update:modelValue',{...clone(props.modelValue),...clone(value)});}
function changeChild(index,value){const children=clone(props.modelValue.children);children[index]=clone(value);patch({children});}
function addChild(){if(props.modelValue.children.length<63)patch({children:[...clone(props.modelValue.children),null]});}
function removeLast(){if(props.modelValue.children.length>1)patch({children:clone(props.modelValue.children.slice(0,-1))});}
</script>
<style scoped>
fieldset{border:1px solid #dcdfe6;margin:10px 0;padding:10px}.el-select,.el-input{width:100%;margin:6px 0}
</style>
