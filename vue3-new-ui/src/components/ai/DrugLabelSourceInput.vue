<template>
 <section aria-label="药品说明书明确来源选择">
  <el-alert title="只选择已释放、药师本人独立签署并经技术发布的完整提供版本；不代表官方说明书覆盖、执照验证或临床用药规则。" type="info" :closable="false" />
  <p v-if="!v.referencesValid||!v.scopeValid" role="alert">来源引用或实际目录药品范围无效；不会转为其它输入模式。</p>
  <p v-else-if="!v.authorized" role="status">仅当前药师或超级管理员可以选择本项来源。</p>
  <template v-else>
   <el-button :disabled="v.busy" @click="v.showSources">打开说明书来源目录</el-button>
   <el-button v-if="v.preset||v.selected" :loading="v.busy" @click="v.reread">重新核对明确来源</el-button>
   <el-button v-if="v.selected" @click="v.clear({close:true})">清除本次来源选择</el-button>
   <p v-if="v.selected" role="status">已明确选择目录 {{ v.selected.identity.pharmaceutical_id }}：{{ v.selected.identity.name===null?'名称未记录':v.selected.identity.name }}；来源 {{ v.selected.source_binding_id }}。已清除完整正文和私有复核依据，仅保留本次身份、原件与签署哈希锚。</p>
   <p v-else>尚未建立可用来源选择；不会自动选择第一项。</p>
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
