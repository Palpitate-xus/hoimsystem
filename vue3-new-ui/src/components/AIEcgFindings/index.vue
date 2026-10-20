<template>
  <section v-if="source" class="ecg-findings" aria-label="心电原始依据与候选复核">
    <h4>原始心电依据与模型候选</h4><p>{{ findings.scope_note }}</p>
    <p>本区为任务当时原版本 {{ source.revision }}，原文件标识 {{ source.asset_id }}；采集时刻 {{ source.recorded_at || '未记录，不用登记时刻补写' }}。</p>
    <p>采样率 {{ source.signal_metadata.sample_rate_hz }}Hz，原样本数 {{ source.signal_metadata.sample_count }}；导联顺序 {{ source.signal_metadata.leads.map(lead => lead.name).join('、') }}。</p>
    <p v-for="item in findings.missing_data || []" :key="item" class="data-gap">{{ item }}</p>
    <el-button link @click="$emit('inspect', source.source_id)">核查原心电元数据依据</el-button>
    <el-table :data="source.signal_metadata.leads" max-height="260">
      <el-table-column prop="name" label="原导联" width="85" /><el-table-column prop="gain" label="声明增益" min-width="110" /><el-table-column prop="baseline" label="原基线ADC" width="115" /><el-table-column prop="unit" label="声明物理单位" width="115" /><el-table-column prop="missing_samples" label="缺失采样数" width="110" /><el-table-column label="数值观察" min-width="180"><template #default="{ row }">{{ row.constant_observed_values == null ? '无可用采样' : row.constant_observed_values ? '可用值恒定，原因未确定' : '可用值有变化，非诊断结论' }}</template></el-table-column>
    </el-table>
    <template v-if="analysis">
      <p>服务报告覆盖原样本 {{ analysis.processing.processed_original_sample_count }}/{{ analysis.processing.input_sample_count }}；实际使用导联 {{ analysis.processing.used_leads.join('、') }}。完整输入报告不证明识别准确或临床已验证。</p>
      <p>缺失处理：{{ analysis.processing.missing_sample_handling === 'masked' ? '模型报告使用掩码，仍需核对适用性' : '模型报告无缺失样本' }}。</p>
      <p v-for="(item, index) in analysis.processing.preprocessing_notes" :key="index" class="recorded-text">模型预处理说明：{{ item }}</p>
      <el-table :data="analysis.findings" empty-text="未返回候选不表示正常，仍须结合原波形和医生复核">
        <el-table-column label="模型候选（待复核）" min-width="180"><template #default="{ row }">{{ row.label }}</template></el-table-column>
        <el-table-column label="原导联与定位" min-width="180"><template #default="{ row }">{{ row.leads.join('、') }}<br />{{ row.location === 'recording' ? '全记录级，未提供局部定位' : `原样本${row.start_sample}–${row.end_sample_exclusive}（结束不含）` }}</template></el-table-column>
        <el-table-column label="模型原始分数" width="130"><template #default="{ row }">{{ row.score == null ? '未提供' : row.score }}<br />非患病概率</template></el-table-column>
        <el-table-column label="说明" min-width="240"><template #default="{ row }"><p class="recorded-text">{{ row.description }}</p></template></el-table-column>
        <el-table-column label="核对" width="105"><template #default="{ row }"><el-button link @click="locate(row)">查看原波形</el-button><el-button link @click="$emit('inspect', row.source_id)">原始依据</el-button></template></el-table-column>
      </el-table>
      <p>候选不等于确诊；模型分数不是患病概率，不自动修改诊断、报告或签署。全记录候选未提供局部定位，当前视窗仅显示所选区间。</p>
      <el-button v-if="allowCopy" @click="$emit('copy')">复制心电候选草稿</el-button>
    </template>
    <ai-ecg-viewer ref="viewer" :source="source" allow-download />
  </section>
</template>
<script setup>
import { computed, ref } from "vue";
import AiEcgViewer from "@/components/AIEcgViewer/index.vue";
const props = defineProps({ findings: { type: Object, default: null }, analysis: { type: Object, default: null }, allowCopy: Boolean });
defineEmits(["inspect", "copy"]);
const viewer = ref(null), source = computed(() => props.findings?.ecg_source || null);
function locate(row) { if (row.location === "sample_interval") viewer.value?.seekTo(row.start_sample, row.end_sample_exclusive, row.leads); else viewer.value?.showRecording(); }
</script>
<style scoped>
.ecg-findings { margin: 16px 0; line-height: 1.7; }.recorded-text { white-space: pre-wrap; overflow-wrap: anywhere; }.data-gap { color: #8b5d12; }
</style>
