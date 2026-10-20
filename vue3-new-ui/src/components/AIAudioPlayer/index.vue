<template>
  <div v-if="assetId" class="audio-player" aria-label="原录音播放器">
    <div class="audio-actions"><el-button :loading="loading" @click="load">加载原录音</el-button><el-button :loading="loading" @click="download">下载原录音</el-button></div>
    <audio v-if="objectUrl" ref="player" :src="objectUrl" controls preload="metadata" @error="playbackError = true" />
    <p v-if="playbackError">当前浏览器无法播放此编码，可由有权限人员下载至受控环境听音核对。</p>
  </div>
</template>
<script setup>
import { nextTick, onBeforeUnmount, onDeactivated, ref, watch } from "vue";
import { ElMessage } from "element-plus";
import { getAIAudioContent } from "@/api/ai";
const props = defineProps({ assetId: { type: String, default: "" }, extension: { type: String, default: ".audio" } });
const objectUrl = ref(""), player = ref(null), loading = ref(false), playbackError = ref(false);
let version = 0, pending = null;
function release() { version += 1; player.value?.pause(); if (objectUrl.value) URL.revokeObjectURL(objectUrl.value); objectUrl.value = ""; pending = null; loading.value = false; playbackError.value = false; }
async function load() {
  if (objectUrl.value) return objectUrl.value;
  if (pending) return pending;
  const current = version; loading.value = true;
  pending = (async () => {
    try { const blob = await getAIAudioContent(props.assetId); if (current !== version) return; objectUrl.value = URL.createObjectURL(blob); await nextTick(); return objectUrl.value; }
    finally { if (current === version) { loading.value = false; pending = null; } }
  })();
  return pending;
}
async function seekTo(milliseconds) {
  const current = version;
  if (!await load() || !player.value || current !== version) return;
  const audio = player.value;
  try { audio.currentTime = Math.max(0, milliseconds / 1000); await audio.play(); }
  catch { ElMessage.info("原音已加载，请点击播放器播放并核对相应片段"); }
}
async function download() {
  const current = version;
  const url = await load(); if (!url || current !== version) return;
  const link = document.createElement("a"); link.href = url; link.download = `audio-${props.assetId}${props.extension}`; link.click();
}
watch(() => props.assetId, release);
onDeactivated(release); onBeforeUnmount(release);
defineExpose({ seekTo });
</script>
<style scoped>
.audio-player { margin: 12px 0; }.audio-actions { display: flex; gap: 8px; margin-bottom: 8px; } audio { width: 100%; }
</style>
