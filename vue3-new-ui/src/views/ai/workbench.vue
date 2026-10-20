<template>
  <div class="app-container"><vab-page-header title="AI 业务助手" description="按当前角色和诊疗关系使用辅助能力，查看依据并记录人工复核" /><el-card><ai-assistant :initial-feature="initialFeature" :patient-id="patientId" :encounter-ref="encounterRef" /></el-card></div>
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
