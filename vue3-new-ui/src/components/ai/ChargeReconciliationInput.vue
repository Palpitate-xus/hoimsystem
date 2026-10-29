<template>
 <section aria-label="完整住院账目核对入口">
  <p v-if="!allowed">当前身份不能使用完整账目核对。</p>
  <template v-else>
   <p>请选择患者、本次住院和一份已发布的完整账目。</p>
   <p v-if="!scopeReady">请从已授权患者的真实住院记录进入，不能猜测患者或住院标识。</p>
   <template v-else>
    <el-button @click="refresh" :loading="checking">重新核对账目范围</el-button><el-button v-if="selected" @click="clearSelection">清除账目选择</el-button>
    <p v-if="error" role="alert">{{error}}</p><p v-if="checking" role="status">正在核对完整账目、原件哈希与当前授权。</p>
    <p v-if="selected" aria-label="已选择完整住院账目">已明确原件 {{selected.source_id}}；完整{{selected.snapshot.collection.member_manifest.length}}个成员；捕获时刻{{selected.snapshot.collection.captured_at}}。</p>
    <charge-reconciliation-source-panel :key="childKey" :patient-id="patientId" :admission-id="admissionId" :active="active" :audit-only="false" @select="select" @source-changed="sourceChanged" @invalidate="unavailable"/>
   </template>
  </template>
 </section>
</template>
<script setup>
import{defineAsyncComponent}from'vue';
import{useChargeReconciliationInput}from'./useChargeReconciliationInput';
const ChargeReconciliationSourcePanel=defineAsyncComponent(()=>import('./ChargeReconciliationSourcePanel.vue'));
const props=defineProps({patientId:{type:Number,default:null},admissionId:{type:String,default:null},initialReferences:{type:Object,default:()=>({})},active:{type:Boolean,default:true}}),emit=defineEmits(['scope-change','selection','availability','invalidate']);
const{allowed,scopeReady,selected,checking,error,childKey,select,refresh,clearSelection,sourceChanged,unavailable}=useChargeReconciliationInput(props,emit);
</script>
<style scoped>p{line-height:1.7;overflow-wrap:anywhere}.el-button{margin:6px}</style>
