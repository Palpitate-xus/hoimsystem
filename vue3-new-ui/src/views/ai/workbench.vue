<template>
  <div class="app-container ai-workbench">
    <header class="ai-page-heading"><h1>AI 业务助手</h1><p>选择要处理的任务，确认资料后生成结果。</p></header>
    <el-card shadow="never" class="workbench-content"><ai-assistant :initial-feature="initialFeature" :patient-id="patientId" :encounter-ref="encounterRef" /></el-card>
  </div>
</template>

<script setup>
import { computed } from "vue";
import { useRoute } from "vue-router";
import AiAssistant from "@/components/AIAssistant/index.vue";
const route = useRoute();
const initialFeature = computed(() => typeof route.query.feature === "string" ? route.query.feature : "");
const patientId = computed(() => { const value = Number(route.query.patient_id); return Number.isInteger(value) && value > 0 ? value : null; });
const encounterRef = computed(() => typeof route.query.encounter_ref === "string" ? route.query.encounter_ref : "");
</script>

<style scoped>
.ai-page-heading { margin-bottom: 20px; }
.ai-page-heading h1 { margin: 0 0 8px; font-size: 24px; font-weight: 600; color: var(--el-text-color-primary); }
.ai-page-heading p { margin: 0; color: var(--el-text-color-secondary); line-height: 1.6; }
.ai-workbench :deep(.el-card) { box-shadow: none !important; border: 1px solid var(--el-border-color-lighter); border-radius: 6px; }
</style>
