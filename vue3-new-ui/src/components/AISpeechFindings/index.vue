<template>
  <section v-if="findings?.audio_source" class="speech-findings">
    <h4>原录音资料与转写复核</h4><p>{{ findings.scope_note }}</p>
    <p>原录音标识：{{ source.asset_id }}；原格式：{{ source.media_type }}；解码时长：{{ seconds(source.duration_ms) }}秒。</p>
    <p>原录音时间：{{ source.recorded_at || '未记录，不以登记或上传时间代替' }}。本区展示任务资料中的原版本。</p>
    <el-button link @click="$emit('inspect', source.source_id)">核查原录音元数据依据</el-button>
    <ai-audio-player ref="player" :asset-id="source.asset_id" :extension="source.extension" />
    <template v-if="transcription">
      <p>模型报告：{{ transcription.speech_detected ? '检出语音' : '未检出可转写语音' }}，仍须听音核实。说话人标签仅表示模型分组，身份与职业未经核实。</p>
      <el-table :data="transcription.segments" empty-text="未返回可转写片段；请核对原音和模型适用范围">
        <el-table-column label="相对音频时间" width="125"><template #default="{ row }">{{ seconds(row.start_ms) }}–{{ seconds(row.end_ms) }}秒</template></el-table-column>
        <el-table-column label="说话人" width="125"><template #default="{ row }">{{ row.speaker }}<br />角色待核实</template></el-table-column>
        <el-table-column label="转写草稿" min-width="240"><template #default="{ row }"><p class="recorded-text">{{ row.text }}</p><p v-if="row.uncertain" class="data-gap">不确定：{{ row.uncertainty_note }}</p></template></el-table-column>
        <el-table-column label="核对" width="100"><template #default="{ row }"><el-button link @click="player?.seekTo(row.start_ms)">听此片段</el-button><el-button link @click="$emit('inspect', row.source_id)">原音依据</el-button></template></el-table-column>
      </el-table>
      <p>片段时间相对解码音频，不代表诊疗事件发生时间；不能据发言者标签认定医生意见、诊断或知情同意。</p>
      <el-button v-if="allowCopy" @click="$emit('copy')">复制转写草稿</el-button>
    </template>
  </section>
</template>
<script setup>
import { computed, ref } from "vue";
import AiAudioPlayer from "@/components/AIAudioPlayer/index.vue";
const props = defineProps({ findings: { type: Object, default: null }, transcription: { type: Object, default: null }, allowCopy: Boolean });
defineEmits(["inspect", "copy"]);
const player = ref(null), source = computed(() => props.findings?.audio_source || {});
const seconds = value => (value / 1000).toFixed(3);
</script>
<style scoped>
.speech-findings { line-height: 1.7; margin: 16px 0; }.recorded-text { white-space: pre-wrap; overflow-wrap: anywhere; margin: 0; }.data-gap { color: #9a6700; }
</style>
