<template>
  <section v-if="source" class="ecg-findings" aria-label="心电原始依据与候选复核">
    <h4>原始心电依据与模型候选</h4><p v-if="noticeText(findings.scope_note)">{{ noticeText(findings.scope_note) }}</p>
    <p>本区为任务当时原版本 {{ source.revision }}，原文件标识 {{ source.asset_id }}；采集时刻 {{ source.recorded_at || '未记录，不用登记时刻补写' }}。</p>
    <p>采样率 {{ source.signal_metadata.sample_rate_hz }}Hz，原样本数 {{ source.signal_metadata.sample_count }}；导联顺序 {{ source.signal_metadata.leads.map(lead => lead.name).join('、') }}。</p>
    <p v-for="item in noticeList(findings.missing_data || [])" :key="item" class="data-gap">{{ item }}</p>
    <el-button link @click="$emit('inspect', source.source_id)">核查原心电元数据依据</el-button>
    <el-table :data="source.signal_metadata.leads" max-height="260">
      <el-table-column prop="name" label="原导联" width="85" /><el-table-column prop="gain" label="声明增益" min-width="110" /><el-table-column prop="baseline" label="原基线ADC" width="115" /><el-table-column prop="unit" label="声明物理单位" width="115" /><el-table-column prop="missing_samples" label="缺失采样数" width="110" /><el-table-column label="数值观察" min-width="180"><template #default="{ row }">{{ row.constant_observed_values == null ? '无可用采样' : row.constant_observed_values ? '可用值恒定，原因未确定' : '可用值有变化，非诊断结论' }}</template></el-table-column>
    </el-table>
    <template v-if="analysis">
      <p>服务报告覆盖原样本 {{ analysis.processing.processed_original_sample_count }}/{{ analysis.processing.input_sample_count }}；实际使用导联 {{ analysis.processing.used_leads.join('、') }}。</p>
      <p>缺失处理：{{ analysis.processing.missing_sample_handling === 'masked' ? '模型报告使用掩码，仍需核对适用性' : '模型报告无缺失样本' }}。</p>
      <p v-for="(item, index) in analysis.processing.preprocessing_notes" :key="index" class="recorded-text">模型预处理说明：{{ item }}</p>
      <section v-if="localRuntime" class="local-runtime" aria-label="本地心电研究模型运行记录">
        <h4>本地心电研究模型运行记录</h4>
        <el-descriptions :column="1" border>
          <el-descriptions-item label="运行引擎">{{ localRuntime.engine }}；<span v-for="(version, engine) in localRuntime.engine_versions" :key="engine">{{ engine }} {{ version }} </span></el-descriptions-item>
          <el-descriptions-item label="模型来源版本">{{ localRuntime.model_repository }} · {{ localRuntime.model_revision }}</el-descriptions-item>
          <el-descriptions-item label="模型文件摘要"><span class="recorded-text">{{ localRuntime.model_digest }}</span></el-descriptions-item>
          <el-descriptions-item label="运行环境摘要"><span class="recorded-text">{{ localRuntime.runtime_digest }}</span></el-descriptions-item>
          <el-descriptions-item label="预处理摘要"><span class="recorded-text">{{ localRuntime.preprocessing_digest }}</span></el-descriptions-item>
          <el-descriptions-item label="固定输入">原始 {{ localRuntime.required_leads.join('、') }} 导联；{{ localRuntime.sample_rate_hz }} Hz，每导联 {{ localRuntime.samples_per_lead }} 个样本，{{ localRuntime.samples_per_lead / localRuntime.sample_rate_hz }} 秒</el-descriptions-item>
          <el-descriptions-item label="缺失样本策略">{{ localRuntime.missing_sample_policy }}：拒绝缺失样本；不滤波、不重采样、不填补或补零、不裁剪原始输入。</el-descriptions-item>
          <el-descriptions-item label="模型训练标签">{{ localRuntime.labels.join('、') }}</el-descriptions-item>
          <el-descriptions-item label="Prompt 处理方式">{{ localRuntime.prompt_handling }}：仅对所选原始信号分类，Prompt 不能补造导联、波形或临床信息。</el-descriptions-item>
          <el-descriptions-item label="人群适用性">{{ localRuntime.population_applicability }}：未核实采集时人群及本模型适用性。</el-descriptions-item>
          <el-descriptions-item label="临床验证">{{ localRuntime.clinical_validation }}：尚无验证记录。</el-descriptions-item>
        </el-descriptions>
        <p>以下为各标签的全记录模型分数，诊断阈值尚未配置。</p>
      </section>
      <el-table :data="analysis.findings" empty-text="本次未返回心电候选">
        <el-table-column label="模型候选（待复核）" min-width="180"><template #default="{ row }">{{ noticeText(row.label) }}</template></el-table-column>
        <el-table-column label="原导联与定位" min-width="180"><template #default="{ row }">{{ row.leads.join('、') }}<br />{{ row.location === 'recording' ? '全记录级，未提供局部定位' : `原样本${row.start_sample}–${row.end_sample_exclusive}（结束不含）` }}</template></el-table-column>
        <el-table-column label="模型原始分数" width="130"><template #default="{ row }">{{ row.score == null ? '未提供' : row.score }}</template></el-table-column>
        <el-table-column label="说明" min-width="240"><template #default="{ row }"><p class="recorded-text" v-if="noticeText(row.description)">{{ noticeText(row.description) }}</p></template></el-table-column>
        <el-table-column label="核对" width="105"><template #default="{ row }"><el-button link @click="locate(row)">查看原波形</el-button><el-button link @click="$emit('inspect', row.source_id)">原始依据</el-button></template></el-table-column>
      </el-table>
      <p>全记录候选没有局部定位，点击“查看原波形”核对。</p>
      <el-button v-if="allowCopy" @click="$emit('copy')">复制心电候选草稿</el-button>
    </template>
    <ai-ecg-viewer ref="viewer" :source="source" allow-download />
  </section>
</template>
<script setup>
import { noticeText, noticeList } from "@/utils/noticeText.cjs";
import { computed, ref } from "vue";
import AiEcgViewer from "@/components/AIEcgViewer/index.vue";
const props = defineProps({ findings: { type: Object, default: null }, analysis: { type: Object, default: null }, allowCopy: Boolean });
defineEmits(["inspect", "copy"]);
const viewer = ref(null), source = computed(() => props.findings?.ecg_source || null);
const localRuntime = computed(() => props.analysis?.processing?.local_runtime || null);
function locate(row) { if (row.location === "sample_interval") viewer.value?.seekTo(row.start_sample, row.end_sample_exclusive, row.leads); else viewer.value?.showRecording(); }
</script>
<style scoped>
.ecg-findings { margin: 16px 0; line-height: 1.7; }.recorded-text { white-space: pre-wrap; overflow-wrap: anywhere; }.data-gap { color: #8b5d12; }.local-runtime { margin: 16px 0; }
</style>
