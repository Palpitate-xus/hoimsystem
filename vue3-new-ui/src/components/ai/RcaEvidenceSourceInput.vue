<template>
 <section aria-label="事件RCA明确Case选择">
  <p v-if="!v.valid" role="alert">仅接受本项规范Case引用和明确原事件范围；不会转回旧RCA问答。</p><p v-else-if="!v.authorized" role="status">仅当前超级管理员可选择；仍须独立事件与患者用途。</p>
  <template v-else><el-button :disabled="!v.panelEvent||v.panelPatient===undefined||v.busy" @click="v.show">打开本事件Case目录</el-button><el-button v-if="v.preset||v.selected" :loading="v.busy" @click="v.reread">明确重读所选RCA Case</el-button><el-button v-if="v.selected" @click="v.clear({close:true})">清除RCA Case选择</el-button>
   <p v-if="v.selected" aria-label="RCA已核对Case锚">已选择事件资料 {{v.selected.case_id}}；关联范围已核对。</p><p v-else>请从事件资料目录选择一项，或核对传入的资料。</p><p v-if="v.error" role="alert">{{v.error}}</p>
   <div v-if="v.open"><el-button @click="v.clear({close:true})">关闭本事件Case目录</el-button><RcaEvidenceSources :event-id="v.panelEvent" :expected-patient-id="v.panelPatient" :active="active&&v.open" selectable @select="v.select" @invalidate="v.clear()" @source-changed="v.clear()"/></div>
  </template>
 </section>
</template>
<script setup>
import {reactive} from 'vue';import RcaEvidenceSources from './RcaEvidenceSources.vue';import {useRcaEvidenceSourceInput} from './useRcaEvidenceSourceInput';
const props=defineProps({initialReferences:{default:null},eventId:{default:null},expectedPatientId:{default:undefined},active:{type:Boolean,default:true}}),emit=defineEmits(['selection','availability','scope-change','invalidate']),v=reactive(useRcaEvidenceSourceInput(props,emit));defineExpose({state:v,clear:v.clear});
</script>
