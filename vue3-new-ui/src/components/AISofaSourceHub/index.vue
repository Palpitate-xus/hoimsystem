<template>
  <section aria-label="SOFA独立原资料入口">
    <p>此入口按本次原住院独立登记与核对完整24小时清单，不依赖上方旧观测窗。</p>
    <sofa-input :patient-id="patientId" :admission-id="admissionId" :active="!disabled" :disabled="disabled" @selection="select" @availability="ready=$event" />
    <el-button type="primary" :disabled="disabled||!ready||!references" @click="open=true">打开本条SOFA辅助核对</el-button>
    <el-dialog v-model="open" title="SOFA固定计算与原依据核对" width="min(1150px,96vw)" destroy-on-close><ai-assistant v-if="open&&references&&!disabled" :feature-keys="['sepsis_risk']" :patient-id="patientId" :encounter-ref="admissionId" :initial-input="references" /></el-dialog>
  </section>
</template>
<script setup>
import {defineAsyncComponent,ref,watch,onDeactivated,onBeforeUnmount} from "vue";
import {useStore} from "vuex";
const props=defineProps({patientId:{type:Number,required:true},admissionId:{type:String,required:true},disabled:{type:Boolean,default:false}}),store=useStore(),references=ref(null),ready=ref(false),open=ref(false);
const SofaInput=defineAsyncComponent(()=>import("@/components/AISofaInput/index.vue")),AiAssistant=defineAsyncComponent(()=>import("@/components/AIAssistant/index.vue"));
function select(value){open.value=false;references.value=value;}
function clear(){open.value=false;references.value=null;ready.value=false;}
watch([()=>props.patientId,()=>props.admissionId,()=>props.disabled,()=>store.state.user.accessToken,()=>JSON.stringify(store.getters["user/permissions"])],clear,{flush:"sync"});onDeactivated(clear);onBeforeUnmount(clear);
</script>
