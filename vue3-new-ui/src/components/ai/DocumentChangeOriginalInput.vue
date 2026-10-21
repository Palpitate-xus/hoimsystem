<template>
  <section :aria-label="label">
    <h4>{{ label }}</h4>
    <p>只选择当前已发布且明确完成隐私与原意审核的完整原文；这里不生成或保存模型草稿。</p>
    <p v-if="v.error" role="alert">{{ v.error }}</p>
    <template v-if="v.authorized">
      <el-button :loading="v.busy" @click="v.loadPage(1)">刷新原文目录并清除选择</el-button>
      <el-table :data="v.directory?.items||[]" empty-text="当前页无原文，不会自动选择首项">
        <el-table-column prop="original_id" label="原件标识" min-width="260" /><el-table-column prop="title" label="声明标题" min-width="180" /><el-table-column prop="version" label="声明版本" width="110" />
        <el-table-column label="状态" width="100"><template #default="{row}">{{ states[row.status] }}</template></el-table-column>
        <el-table-column label="操作" width="180"><template #default="{row}"><el-button :disabled="v.busy||row.status!=='published'" @click="v.select(row.original_id,row)">选择并核对完整原件</el-button></template></el-table-column>
      </el-table>
      <el-pagination v-if="v.directory" :current-page="v.directory.page" :page-size="v.directory.page_size" :total="v.directory.total" layout="prev,pager,next,total" :disabled="v.busy" @current-change="v.loadPage" />
      <div v-if="v.original" role="status">已核对 {{ v.original.snapshot.metadata.title }} / {{ v.original.snapshot.metadata.version }}；原UTF8 {{ v.original.snapshot.raw_bytes_length }}字节。<el-button @click="v.clear">清除原件</el-button></div>
    </template>
  </section>
</template>
<script setup>
import {reactive} from 'vue';
import {documentEvidenceStates as states} from '@/api/ai/documentEvidence';
import {useDocumentExtractionInput} from './useDocumentExtractionInput';
const props=defineProps({active:{type:Boolean,default:true},label:{type:String,required:true}}),emit=defineEmits(['selection-change']);
const v=reactive(useDocumentExtractionInput({get active(){return props.active;},initialReferences:{}},emit));
</script>
<style scoped>
section{border:1px solid var(--el-border-color);padding:12px;border-radius:6px}p{line-height:1.6;overflow-wrap:anywhere}[role=alert]{color:var(--el-color-danger)}.el-pagination{margin-top:12px}
</style>
