<template>
 <section aria-label="科研任务独立分件审计">
  <p>科研审计不授予临床正文权限；当前项目及逐患者授权撤回后，超级管理员也只能查看技术状态、实际付费用量和不透明哈希。</p>
  <template v-if="allowed&&bundle">
   <p v-if="bundle.incomplete" aria-label="科研持久件缺失技术目录">原目录技术记录：{{ bundle.metadata.status }}；原能力标记 {{ bundle.metadata.feature_key }}；完整持久分件缺失，未核对执行正文或完整溯源。关闭或刷新目录后须重新明确读取。</p>
   <template v-else><p aria-label="科研审计任务状态">{{ bundle.metadata.status }}；{{ bundle.metadata.cancellation_pending?'原在途调用回执待返回':'当前技术状态已核对' }}。</p>
   <p aria-label="科研审计实际用量">输入：{{ shown(bundle.metadata.usage.input_tokens) }}；输出：{{ shown(bundle.metadata.usage.output_tokens) }}；{{ bundle.metadata.usage.model_call_attempted===null?'是否调用未知':bundle.metadata.usage.model_call_attempted?'已尝试模型调用':'已确认未调用模型' }}。</p></template>
   <p v-if="!bundle.parts" aria-label="科研安全技术审计范围">当前仅技术metadata与不透明SHA；原哈希是服务端锚，浏览器未重建隐去正文。未读取临床原文、模型待核问题、Task或RAW3。</p>
   <pre v-if="!bundle.parts&&!bundle.incomplete" aria-label="科研不透明服务端锚">{{ opaqueAnchors }}</pre>
   <ResearchCohortFindings v-if="bundle.parts" :metadata="bundle.metadata" :parts="bundle.parts" :active="active" audit-only @invalidate="emit('invalidate')"/>
  </template>
 </section>
</template>
<script setup>
import{computed}from'vue';import{useStore}from'vuex';import ResearchCohortFindings from'./ResearchCohortFindings.vue';
const props=defineProps({bundle:{type:Object,required:true},active:{type:Boolean,default:true}}),emit=defineEmits(['invalidate']),store=useStore(),allowed=computed(()=>props.active&&typeof store.state.user?.accessToken==='string'&&store.state.user.accessToken.length>0&&Array.isArray(store.state.user.permissions)&&store.state.user.permissions.includes('super_admin')),shown=v=>v===null?'未知':String(v),opaqueAnchors=computed(()=>({run_id:props.bundle.metadata.run_id,research_cohort_case_id:props.bundle.metadata.research_cohort_case_id,scope_id:props.bundle.metadata.scope_id,source_projection_hash:props.bundle.metadata.source_projection_hash,source_binding_hash:props.bundle.metadata.source_binding_hash}));
</script>
