<template><rule-provider-check mode="qsofa" :target="target" :providers="providers" @close="emit('close')" @edit-model="emit('edit-model',$event)" /></template>
<script setup>
import RuleProviderCheck from "@/components/AIRuleProviderCheck/index.vue";
defineProps({target:{type:Object,default:null},providers:{type:Array,default:()=>[]}});
const emit=defineEmits(["close","edit-model"]);
</script>
