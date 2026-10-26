<template>
 <section aria-label="明确脱敏来源选择">
  <p v-if="!v.referencesValid" role="alert">资料引用无效，请重新选择。</p>
  <p v-else-if="!v.scopeRequest" role="status">请先选择项目和患者。</p>
  <p v-else-if="!v.authorized" role="status">当前会话或用途读取条件不足，全文与选择已清除。</p>
  <template v-else>
   <p>本次资料仅用于去标识复核；模型处理和导出需分别取得许可。</p>
   <p v-if="v.pending&&!v.anchor">待核对引用 {{ v.pending }}，尚未读取或选中。</p>
   <el-button v-if="v.pending" :disabled="v.busy" @click="v.readPending">显式重读所引用完整来源</el-button>
   <el-button :disabled="v.busy" @click="v.openSources">打开当前范围来源与人工复核</el-button>
   <el-button @click="v.clear">清除本次来源选择</el-button>
   <p v-if="v.anchor" aria-label="已核对最小来源锚">已明确选择 {{ v.anchor.case_id }}；完整来源和当前条件已重读。</p>
   <DeidentificationSources v-if="v.sourceOpen" :scope="scope" :patient-id="patientId" :active="active" :audit-only="false" @select="v.choose" @invalidate="v.invalidate" @source-changed="v.invalidate"/>
  </template><p v-if="v.error" role="alert">{{ v.error }}</p>
 </section>
</template>
<script setup>
import{reactive}from'vue';import{useDeidentificationInput}from'./useDeidentificationInput';import DeidentificationSources from'./DeidentificationSources.vue';
const props=defineProps({scope:{type:Object,default:null},patientId:{type:Number,default:null},initialReferences:{type:Object,default:null},active:{type:Boolean,default:true}}),emit=defineEmits(['selection','availability','invalidate']),v=reactive(useDeidentificationInput(props,emit));defineExpose({clear:v.clear});
</script>
