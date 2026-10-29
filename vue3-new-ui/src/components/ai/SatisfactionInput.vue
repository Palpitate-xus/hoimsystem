<template>
  <section aria-label="受审评价证据输入">
    <p v-if="!allowed">当前身份不能读取评价证据。</p>
    <template v-else>
      <p>请选择已审核的评价资料。模型接收评分统计和选定的人工摘录。</p>
      <p v-if="error" role="alert">{{ error }}</p><p v-if="checking" role="status">正在核对本次评价资料。</p>
      <template v-if="!initialMalformed">
        <el-button @click="refresh" :loading="checking">重新核对当前评价引用</el-button><el-button v-if="selected || checking" @click="clearSelection">清除评价证据选择</el-button>
        <article v-if="selected" aria-label="已选择受审评价证据"><p>{{ selected.source_id }}；{{ selected.safe_snapshot.all_member_statistics.record_count }} 条评价记录、{{ selected.safe_snapshot.member_manifest.length }} 项评价及摘录版本。</p><p>日期 {{ selected.date_from }} 至 {{ selected.date_to }}；原存储时区未知。</p><details><summary>来源核验详情</summary><p>原件 SHA 为受保护全文锚，客户端只重算完整安全投影与成员摘要。</p></details></article>
        <satisfaction-source-panel :key="childKey" :active="active" :audit-only="false" :selectable="true" @scope-change="scopeChanged" @select="selectCase" @source-changed="sourceChanged" @invalidate="sourceUnavailable" />
      </template>
    </template>
  </section>
</template>
<script setup>
import {defineAsyncComponent} from 'vue';
import {useSatisfactionInput} from './useSatisfactionInput';
const SatisfactionSourcePanel=defineAsyncComponent(()=>import('./SatisfactionSourcePanel.vue'));
const props=defineProps({initialReferences:{type:Object,default:null},active:{type:Boolean,default:true}});
const emit=defineEmits(['scope-change','selection','availability','invalidate']);
const{allowed,initialMalformed,selected,checking,error,childKey,selectCase,scopeChanged,sourceChanged,sourceUnavailable,clearSelection,refresh}=useSatisfactionInput(props,emit);
</script>
<style scoped>p{line-height:1.7;overflow-wrap:anywhere}.el-button{margin:5px}</style>
