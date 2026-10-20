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
</script>
<style scoped>.image-findings { margin: 16px 0; line-height: 1.7; overflow-wrap: anywhere; }</style>
