<template>
 <section aria-label="药品说明书明确来源选择">
  <el-alert title="请选择已审核发布、经药师签署的说明书版本。" type="info" :closable="false" />
  <p v-if="!v.referencesValid||!v.scopeValid" role="alert">来源引用或实际目录药品范围无效；不会转为其它输入模式。</p>
  <p v-else-if="!v.authorized" role="status">仅当前药师或超级管理员可以选择本项来源。</p>
  <template v-else>
   <el-button :disabled="v.busy" @click="v.showSources">打开说明书来源目录</el-button>
   <el-button v-if="v.preset||v.selected" :loading="v.busy" @click="v.reread">重新核对明确来源</el-button>
   <el-button v-if="v.selected" @click="v.clear({close:true})">清除本次来源选择</el-button>
   <p v-if="v.selected" role="status">已明确选择目录 {{ v.selected.identity.pharmaceutical_id }}：{{ v.selected.identity.name===null?'名称未记录':v.selected.identity.name }}；来源 {{ v.selected.source_binding_id }}。</p>
   <p v-else>请从目录选择说明书来源。</p>
   <p v-if="v.error" role="alert">{{ v.error }}</p>
   <div v-if="v.open" aria-label="本次说明书来源目录"><el-button @click="v.closeSources">关闭本次来源目录</el-button><DrugLabelSources :pharmaceutical-id="v.panelPharmaceuticalId" :active="active&&v.open" :audit-only="false" @select="v.select" @invalidate="v.invalidate" @source-changed="v.sourceChanged" /></div>
  </template>
 </section>
</template>
<script setup>
import {reactive} from 'vue';
import DrugLabelSources from './DrugLabelSources.vue';
import {useDrugLabelSourceInput} from './useDrugLabelSourceInput';
const props=defineProps({pharmaceuticalId:{type:Number,default:null},initialReferences:{type:Object,default:null},active:{type:Boolean,default:true}}),emit=defineEmits(['scope-change','selection','availability','invalidate']),v=reactive(useDrugLabelSourceInput(props,emit));
defineExpose({clear:v.clear});
</script>
