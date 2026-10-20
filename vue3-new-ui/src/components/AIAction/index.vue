<template>
  <el-button size="small" :disabled="disabled" @click="visible = true">{{ label }}</el-button>
  <el-drawer v-model="visible" :title="title" size="min(900px, 96vw)" append-to-body destroy-on-close>
    <ai-assistant v-if="visible" :feature-keys="featureKeys" :initial-feature="initialFeature" :patient-id="patientId || null" :encounter-ref="encounterRef || ''" :initial-input="initialInput" />
  </el-drawer>
</template>

<script setup>
import { ref } from "vue";
import AiAssistant from "@/components/AIAssistant/index.vue";
defineProps({ label: { type: String, default: "AI 辅助" }, title: { type: String, default: "AI 业务辅助" }, featureKeys: { type: Array, default: () => [] }, initialFeature: { type: String, default: "" }, patientId: { type: Number, default: null }, encounterRef: { type: String, default: "" }, initialInput: { type: Object, default: () => ({}) }, disabled: { type: Boolean, default: false } });
const visible = ref(false);
</script>
