<template>
  <div class="app-container ai-workbench">
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
.ai-workbench :deep(.el-card) { box-shadow: none !important; border: 1px solid var(--el-border-color-lighter); border-radius: 6px; }
</style>
