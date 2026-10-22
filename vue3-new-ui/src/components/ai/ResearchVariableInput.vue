<template>
 <section aria-label="科研变量明确来源输入">
  <p>仅明确选择完整变量批次；不会自动选择首项。项目、全部患者研究用途和外部模型处理权限仍由服务端逐次核验。</p>
  <p v-if="!v.initialValid" role="alert">初始引用必须只有规范 research_variable_batch_id；外域字段或显式null引用不可用。</p>
  <p v-else-if="!v.authorized" role="status">当前会话或读取范围不满足本项条件，旧来源已清除。</p>
  <template v-else><p v-if="v.pendingId&&!v.selected">待明确读取引用 {{ v.pendingId }}；引用本身不建立可用性。</p><el-button v-if="v.pendingId" :loading="v.reading" @click="v.read(v.pendingId)">显式重新读取引用完整批次</el-button><el-input v-model="v.manualId" aria-label="明确已授权批次引用" placeholder="仅明确已获授权的完整批次UUID，不是患者或病历标识" /><el-button :disabled="v.reading||!v.manualValid" @click="v.read(v.manualId)">读取明确已授权批次引用</el-button><el-button :disabled="v.reading" @click="v.open">打开完整变量来源目录</el-button><el-button v-if="v.selected" :disabled="v.reading" @click="v.close">清除本次选择</el-button><p v-if="v.selected" role="status">已明确选择完整批次 {{ v.selected.metadata.batch_id }}；来源字面值与当前分件已核对，尚未调用模型。</p></template>
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
