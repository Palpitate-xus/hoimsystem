<template>
<fieldset><legend>{{ label }}</legend>
 <label>{{label}}状态<select :aria-label="label+'状态'" :value="modelValue.mode" @change="choose($event.target.value)"><option value="" disabled>明确已知、未知或不适用</option><option value="known">明确原量</option><option value="unknown">未知</option><option value="not_applicable">明确不适用</option></select></label>
 <template v-if="modelValue.mode==='known'&&modelValue.amount">
  <label>原数值文本<input :aria-label="label+'原数值文本'" v-model="modelValue.amount.value" inputmode="decimal" placeholder="保留原文本；零须明确输入0"></label>
  <template v-if="kind==='quantity'"><label>原计量单位<input :aria-label="label+'原计量单位'" v-model="modelValue.amount.original_unit_text"></label></template>
  <template v-else><label>原币种<input :aria-label="label+'原币种'" v-model="modelValue.amount.currency_text"></label><label>原费用单位<input :aria-label="label+'原费用单位'" v-model="modelValue.amount.original_cost_unit_text"></label></template>
  <label>原单位核实<select :aria-label="label+'原单位核实'" v-model="modelValue.amount.unit_review"><option value="" disabled>明确核实状态</option><option value="confirmed">明确确认</option><option value="not_confirmed">明确不确认</option><option value="unknown">未知</option></select></label>
 </template>
</fieldset>
</template>
<script setup>
const props=defineProps({modelValue:{type:Object,required:true},label:{type:String,required:true},kind:{type:String,default:'quantity'}}),emit=defineEmits(['update:modelValue']);
function choose(mode){emit('update:modelValue',{mode,amount:mode==='known'?{value:'',absent_reason:null,...props.kind==='quantity'?{original_unit_text:'',unit_review:''}:{currency_text:'',original_cost_unit_text:'',unit_review:''}}:null});}
</script>
<style scoped>fieldset{border:1px solid #ddd;padding:10px;margin:10px 0}label{display:block;margin:7px 0}input,select{display:block;box-sizing:border-box;width:100%;padding:7px;border:1px solid #bbb;background:#fff;color:#222}</style>
