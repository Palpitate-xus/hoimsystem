<template>
  <el-form label-position="top" aria-label="原执行明确映射的安全忙时登记">
    <p>业务原执行 {{ binding.legacy_schedule_id }}，明确物理资源 {{ binding.resource_id }}，参与位置 {{ binding.participant_kind }}。这些锚点由业务父页面明确提供，服务器核对原记录与映射后生成保护见证。</p>
    <p>下面填写经人工核实的UTC区间、连续性与工时原声明。旧无时区时钟不会自动加Z；不要求操作人手填原件或见证SHA。</p>
    <SurgeryFields :schema="editable" :root="schema" label="本次旧时钟映射与核算原声明" v-model="values" />
    <p role="status">{{ valid?'本条映射类型完整，等待服务器核原执行及保护见证。':'明确时钟、缺项或原核算声明尚不完整。' }}</p>
  </el-form>
</template>
<script setup>
import {computed,ref,watch} from 'vue';
import SurgeryFields from './SurgeryFields.vue';
import {surgeryFormSchema,surgeryRequestValid} from '@/api/ai/surgerySources';
const props=defineProps({poolId:{type:String,required:true},binding:{type:Object,required:true}}),emit=defineEmits(['validity']);
const schema=surgeryFormSchema('ProtectedCapsuleCreate'),fixed=['pool_id','resource_id','legacy_schedule_id','participant_kind','assistant_doctor_id','room_alias_id'];
const editable={...schema,properties:Object.fromEntries(Object.entries(schema.properties).filter(([key])=>!fixed.includes(key))),required:schema.required.filter(key=>!fixed.includes(key))},values=ref({});
const request=computed(()=>({...values.value,pool_id:props.poolId,...Object.fromEntries(fixed.filter(key=>key!=='pool_id').map(key=>[key,props.binding[key]]))})),valid=computed(()=>surgeryRequestValid('ProtectedCapsuleCreate',request.value));
watch(()=>[props.poolId,JSON.stringify(props.binding)],()=>{values.value={};},{immediate:true});
watch([request,valid],()=>emit('validity',{valid:valid.value,request:valid.value?JSON.parse(JSON.stringify(request.value)):null}),{deep:true,immediate:true});
</script>
