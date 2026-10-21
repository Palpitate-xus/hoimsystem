<template>
 <research-cohort-assistant v-if="compatible" :key="configuration" :initial-references="initialInput" :active="active" />
 <p v-else role="status">当前功能配置或来源引用不属于有限科研队列任务，请重新明确选择。</p>
</template>
<script setup>
import {computed} from 'vue';
import {useStore} from 'vuex';
import {supportCanonical} from '@/api/inpatientSupport';
import ResearchCohortAssistant from './ResearchCohortAssistant.vue';
import {researchCohortReferencesValid} from './useResearchCohortSourceInput';
const props=defineProps({feature:{type:Object,default:null},featureKey:{type:String,default:''},initialInput:{type:Object,default:()=>({})},patientId:{type:Number,default:null},encounterRef:{type:String,default:''},pharmaceuticalId:{type:Number,default:null},active:{type:Boolean,default:true}});
const store=useStore(),configuredRoles=computed(()=>props.feature?.allowed_roles),actorAllowed=computed(()=>{const r=store.state.user?.permissions;return typeof store.state.user?.accessToken==='string'&&store.state.user.accessToken.length>0&&Array.isArray(r)&&r.length>0&&new Set(r).size===r.length&&r.every(x=>['super_admin','admin','director'].includes(x))&&Array.isArray(configuredRoles.value)&&(r.includes('super_admin')||r.some(x=>configuredRoles.value.includes(x)));});
const compatible=computed(()=>props.featureKey==='research_cohort'&&props.feature?.key==='research_cohort'&&props.feature?.input_mode==='research_cohort_evidence'&&props.feature?.engine==='llm'&&props.feature?.scope==='hospital'&&props.patientId===null&&(props.encounterRef===''||props.encounterRef===null)&&props.pharmaceuticalId===null&&Number.isSafeInteger(props.feature?.revision)&&props.feature.revision>0&&props.feature.enabled===true&&props.feature.provider_configured===true&&props.feature.validation_status==='validated'&&actorAllowed.value&&Array.isArray(props.feature.allowed_roles)&&new Set(props.feature.allowed_roles).size===props.feature.allowed_roles.length&&props.feature.allowed_roles.every(r=>['super_admin','admin','director','doctor','nurse','cashier','pharmacist','guide','patient','lab_technician','registrar'].includes(r))&&props.initialInput!==null&&researchCohortReferencesValid(props.initialInput));
const configuration=computed(()=>supportCanonical([props.feature,props.initialInput,props.patientId,props.encounterRef,props.pharmaceuticalId,props.active,store.state.user?.accessToken,store.state.user?.username,store.state.user?.permissions]));
</script>
