<template>
  <section v-if="source" aria-label="影像原始依据与候选复核" class="image-findings">
    <h4>原始影像依据与模型候选</h4><p>{{ findings.scope_note }}</p>
    <p>任务当时原版本 {{ source.revision }}；原记录 {{ source.asset_id }}；实际申请 {{ source.imaging_order_id }}；原采集时刻 {{ source.recorded_at || '未知，不用上传时刻补写' }}。</p>
    <p v-for="item in findings.missing_data || []" :key="item">{{ item }}</p>
    <el-button link @click="$emit('inspect', source.source_id)">核查原像素元数据依据</el-button>
    <template v-if="analysis">
      <p>原矩阵 {{ analysis.processing.input_columns }} × {{ analysis.processing.input_rows }}；实际处理帧 {{ analysis.processing.processed_frames.join('、') }}。</p>
      <p>实际分析范围：原坐标 x={{ analysis.processing.analysis_region.x }}，y={{ analysis.processing.analysis_region.y }}，宽{{ analysis.processing.analysis_region.width }}，高{{ analysis.processing.analysis_region.height }}。裁剪区外未分析，单张影像不代表完整检查。</p>
      <p v-for="(item, index) in analysis.processing.preprocessing_notes" :key="index">模型预处理说明：{{ item }}</p>
      <section v-if="localRuntime" class="local-runtime" aria-label="本地影像研究模型运行记录">
        <h4>本地影像研究模型运行记录</h4>
        <el-descriptions :column="1" border>
          <el-descriptions-item label="运行引擎">{{ localRuntime.engine }}；<span v-for="(version, engine) in localRuntime.engine_versions" :key="engine">{{ engine }} {{ version }} </span></el-descriptions-item>
          <el-descriptions-item label="模型来源版本">{{ localRuntime.model_repository }} · {{ localRuntime.model_revision }}</el-descriptions-item>
          <el-descriptions-item label="模型文件摘要"><span class="recorded-text">{{ localRuntime.model_digest }}</span></el-descriptions-item>
          <el-descriptions-item label="运行环境摘要"><span class="recorded-text">{{ localRuntime.runtime_digest }}</span></el-descriptions-item>
          <el-descriptions-item label="预处理摘要"><span class="recorded-text">{{ localRuntime.preprocessing_digest }}</span></el-descriptions-item>
          <el-descriptions-item label="研究预处理配置">{{ localRuntime.profile }}</el-descriptions-item>
          <el-descriptions-item label="实际输入范围"><pre class="recorded-text">{{ JSON.stringify(localRuntime.preprocessing?.input_profile || {}, null, 2) }}</pre></el-descriptions-item>
          <el-descriptions-item label="实际预处理声明"><pre class="recorded-text">{{ JSON.stringify(localRuntime.preprocessing || {}, null, 2) }}</pre></el-descriptions-item>
          <el-descriptions-item label="模型原始标签">{{ localRuntime.labels?.join('、') }}</el-descriptions-item>
          <el-descriptions-item label="Prompt 处理方式">{{ localRuntime.prompt_handling }}：仅所选原像素参与分类；Prompt 不改变固定分类算法，不补造影像或临床信息。</el-descriptions-item>
          <el-descriptions-item label="人群适用性">{{ localRuntime.population_applicability }}：未核实采集时人群及本模型适用性。</el-descriptions-item>
          <el-descriptions-item label="临床验证">{{ localRuntime.clinical_validation }}：未提供临床验证，不代表已验证的临床准确性。</el-descriptions-item>
        </el-descriptions>
        <el-descriptions v-if="localPreprocessing" :column="1" border>
          <el-descriptions-item label="实际归一化最大存储值">{{ localPreprocessing.normalization_maxval }}（由原BitsStored确定，不是本图最大值）</el-descriptions-item>
          <el-descriptions-item label="原输入像素数">{{ localPreprocessing.input_pixel_count }}；输入数不等于已分析整张图像。</el-descriptions-item>
          <el-descriptions-item label="裁剪与舍弃">实际裁剪 {{ localPreprocessing.cropped_pixel_count }} 个；裁剪外舍弃 {{ localPreprocessing.discarded_pixel_count }} 个，未分析。</el-descriptions-item>
          <el-descriptions-item label="原填充背景数量">原输入 {{ localPreprocessing.padding_pixels_in_input }} 个；实际裁剪内 {{ localPreprocessing.padding_pixels_in_crop }} 个。模型按原背景路径保留，不补值、不视为病灶。</el-descriptions-item>
          <el-descriptions-item label="裁剪内有效像素">{{ localPreprocessing.valid_pixels_in_crop }} 个；有效值数量不证明信号或诊断质量。</el-descriptions-item>
          <el-descriptions-item label="实际模型张量">{{ localPreprocessing.prepared_shape?.join('×') }}；实际范围 {{ localPreprocessing.prepared_min }} 至 {{ localPreprocessing.prepared_max }}。</el-descriptions-item>
        </el-descriptions>
        <p>研究管线按原 BitsStored 可表示范围归一化，MONOCHROME1 只反转一次，再按原作者中心方形裁剪、224×224双线性抗锯齿缩放。裁剪区外未分析。</p>
        <p>模型不应用DICOM VOI显示窗、不自动minmax或旋转；不声称与原训练预处理等价。下方查看器继续使用独立的DICOM显示窗，不影响已冻结模型分数。</p>
        <p>各标签为单图独立原始分数，非患病概率、诊断阈值或正常结论；未提供病灶框，单图不能代表完整序列或检查。</p>
      </section>
      <el-table :data="analysis.findings" empty-text="未返回候选不表示影像正常">
        <el-table-column prop="label" label="模型候选（待复核）" min-width="160" />
        <el-table-column label="原坐标定位" min-width="200"><template #default="{ row }">{{ row.location === 'image' ? '图像级，未提供病灶定位' : `x=${row.region.x}，y=${row.region.y}，宽${row.region.width}，高${row.region.height}（半开矩形）` }}</template></el-table-column>
        <el-table-column label="模型原始分数" width="150"><template #default="{ row }">{{ row.score == null ? '未提供' : row.score }}<br />非患病概率</template></el-table-column>
        <el-table-column prop="description" label="候选说明" min-width="220" />
        <el-table-column label="依据" width="100"><template #default="{ row }"><el-button link @click="$emit('inspect', row.source_id)">核对来源</el-button></template></el-table-column>
      </el-table>
      <p>不自动写入诊断或签署报告。图像级模型未提供位置；病灶定位须结合原像素人工核对。</p>
      <el-button v-if="allowCopy" @click="$emit('copy')">复制影像候选草稿</el-button>
    </template>
    <ai-image-viewer :asset="source" />
  </section>
</template>
<script setup>
import { computed } from "vue";
import AiImageViewer from "@/components/AiImageViewer.vue";
const props = defineProps({ findings: { type: Object, default: null }, analysis: { type: Object, default: null }, allowCopy: Boolean });
defineEmits(["inspect", "copy"]);
const source = computed(() => props.findings?.image_source || null);
const localRuntime = computed(() => props.analysis?.processing?.local_runtime || null);
const localPreprocessing = computed(() => props.analysis?.processing?.local_preprocessing || null);
</script>
<style scoped>.image-findings { margin: 16px 0; line-height: 1.7; overflow-wrap: anywhere; }.recorded-text { white-space: pre-wrap; overflow-wrap: anywhere; }.local-runtime { margin: 16px 0; }</style>
