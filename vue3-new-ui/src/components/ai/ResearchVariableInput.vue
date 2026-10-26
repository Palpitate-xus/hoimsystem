<template>
 <section aria-label="科研变量明确来源输入">
  <p>请从来源目录选择已授权的变量批次。研究与模型处理权限将在使用时重新核对。</p>
  <p v-if="!v.initialValid" role="alert">传入的批次引用无效，请从来源目录重新选择。</p>
  <p v-else-if="!v.authorized" role="status">当前会话或读取范围不满足本项条件，旧来源已清除。</p>
  <template v-else><p v-if="v.pendingId&&!v.selected">待核对批次：{{ v.pendingId }}</p><el-button v-if="v.pendingId" :loading="v.reading" @click="v.read(v.pendingId)">核对传入批次</el-button><el-button :disabled="v.reading" @click="v.open">选择变量来源</el-button><details><summary>使用已知批次标识</summary><el-input v-model="v.manualId" aria-label="明确已授权批次引用" placeholder="粘贴已获授权的批次UUID" /><el-button :disabled="v.reading||!v.manualValid" @click="v.read(v.manualId)">读取已知批次</el-button></details><el-button v-if="v.selected" :disabled="v.reading" @click="v.close">清除本次选择</el-button><p v-if="v.selected" role="status">已选择批次 {{ v.selected.metadata.batch_id }}；资料已核对，尚未调用模型。</p></template>
  <p v-if="v.error" role="alert">{{ v.error }}</p>
  <el-dialog :model-value="v.panelOpen" title="明确选择变量来源" width="95%" :close-on-click-modal="false" :before-close="done=>{v.close();done();}" destroy-on-close @update:model-value="value=>!value&&v.panelOpen&&v.close()"><ResearchVariableSources v-if="v.panelOpen" :active="active" :selectable="true" @select="v.choose" @invalidate="v.invalidate" @source-changed="v.invalidate" /></el-dialog>
 </section>
</template>
<script setup>
import {reactive} from 'vue';
import ResearchVariableSources from './ResearchVariableSources.vue';
import {useResearchVariableInput} from './useResearchVariableInput';
const props=defineProps({active:{type:Boolean,default:true},initialReferences:{type:Object,default:()=>({})}}),emit=defineEmits(['selection-change']),v=reactive(useResearchVariableInput(props,emit));
defineExpose({clear:v.close});
</script>
<style scoped>[role=alert]{color:#b42318}section{min-width:0}</style>
