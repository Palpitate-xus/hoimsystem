<template>
  <div>
    <el-form-item :label="`${label}原量状态`">
      <el-select :model-value="modelValue.state" :aria-label="`${label}原量状态`" :disabled="disabled" placeholder="明确选择，未填写不补零" @update:model-value="set('state',$event)">
        <el-option v-if="allowKnown" label="原数量明确已知" value="known" />
        <el-option label="原数量未知（unknown）" value="unknown" />
        <el-option label="原数量未记录（not_recorded）" value="not_recorded" />
      </el-select>
    </el-form-item>
    <el-form-item v-if="modelValue.state==='known'" :label="label">
      <el-input :model-value="modelValue.value??''" :aria-label="label" :disabled="disabled" inputmode="numeric" maxlength="10" :placeholder="`原整数${unit}，明确的0保留为已知原量`" @update:model-value="set('value',$event)" />
    </el-form-item>
  </div>
</template>

<script setup>
const props=defineProps({modelValue:{type:Object,default:()=>({state:'',value:''})},label:{type:String,required:true},unit:{type:String,default:'床'},disabled:{type:Boolean,default:false},allowKnown:{type:Boolean,default:true}});
const emit=defineEmits(['update:modelValue']);
function set(key,value){emit('update:modelValue',{...props.modelValue,[key]:value});}
</script>
