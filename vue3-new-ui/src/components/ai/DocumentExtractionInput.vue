<template>
  <section aria-label="条款草稿抽取原文选择">
    <el-alert v-if="!v.referencesValid" title="原文引用范围无效" description="这里只接受原文ID；不接受患者、住院、居家、问题或其他来源引用。" type="error" :closable="false" />
    <el-alert v-else-if="!v.authorized" title="仅当前超级管理员可核对抽取原文" type="info" :closable="false" />
    <p v-if="v.error" role="alert">{{ v.error }}</p>
    <template v-if="v.authorized">
      <el-alert title="选择未核实逐字草稿抽取的原文" description="只选择当前已发布且明确完成隐私与原意审核的完整原件。不会自动选首条、登记候选或发布知识；来源声明不代表官方来源或临床已验证。" type="info" :closable="false" />
      <p>原文登记支持4MiB；模型任务仍须对完整输入、Prompt与结果逐项核对65535字节存储上限。原始字节较小也不保证任务可运行，超限不会截断原文。</p>
      <el-button :loading="v.busy" @click="v.loadPage(1)">刷新原文目录并清除选择</el-button>
      <p v-if="v.preset">预置原文ID：<code>{{ v.preset }}</code> <el-button :disabled="v.busy" @click="v.selectPreset">核对预置原件</el-button>；预置引用尚未自动建立选择。</p>
      <el-table :data="v.directory?.items||[]" :empty-text="v.directory?'本页暂无原件':'尚未读取目录'" aria-label="抽取原文元数据目录">
        <el-table-column prop="title" label="声明标题" min-width="200" /><el-table-column prop="version" label="声明版本" width="120" /><el-table-column label="治理状态" width="140"><template #default="{row}">{{ documentEvidenceStates[row.status] }}</template></el-table-column>
        <el-table-column label="操作" width="180"><template #default="{row}"><el-button :disabled="v.busy||row.status!=='published'" @click="v.select(row.original_id,row)">选择并核对完整原件</el-button></template></el-table-column>
      </el-table>
      <el-pagination v-if="v.directory" :current-page="v.directory.page" :page-size="v.directory.page_size" :total="v.directory.total" layout="prev,pager,next,total" :disabled="v.busy" @current-change="v.loadPage" />
      <el-button v-if="v.original||v.busy" @click="v.clear">清除并关闭原件核对</el-button>
      <div v-if="v.original" aria-label="已核对抽取原件">
        <p role="status">原件已完整核对；仅建立原件引用，仍须由服务器核对完整任务容量与当前权限。</p>
        <p>声明标题与版本：{{ v.original.snapshot.metadata.title }} / {{ v.original.snapshot.metadata.version }}</p>
        <p>原文ID：<code>{{ v.original.snapshot.original_id }}</code>；原UTF8 {{ v.original.snapshot.raw_bytes_length }}字节；Unicode codepoint {{ v.original.snapshot.codepoint_length }}。</p>
        <p>原字节SHA256：<code>{{ v.original.snapshot.raw_bytes_hash }}</code>；原件SHA256：<code>{{ v.original.content_hash }}</code>；治理SHA256：<code>{{ v.original.governance_hash }}</code>。</p>
        <p>登记UTC：{{ v.original.snapshot.recorded_at }}；实际审核UTC：{{ v.original.governance.reviewed_at }}。原可得UTC：{{ v.original.snapshot.metadata.source_available_at??'未记录' }}。</p>
        <el-alert v-if="v.largeOriginal" title="原件原UTF8已达到或超过65535字节" description="4MiB原件登记能力不等于模型任务容量。完整任务还需保存Prompt、身份与输出；服务器会整件核对并拒绝超限，不会裁剪、摘要替换或补写原文。" type="warning" :closable="false" />
        <el-button v-if="!v.rawOpen" @click="v.rawOpen=true">展开已核对完整原文</el-button>
        <pre v-if="v.rawOpen" aria-label="抽取所选完整原文">{{ v.original.snapshot.text }}</pre>
      </div>
    </template>
  </section>
</template>
<script setup>
import {reactive} from 'vue';
import {documentEvidenceStates} from '@/api/ai/documentEvidence';
import {useDocumentExtractionInput} from './useDocumentExtractionInput';
const props=defineProps({active:{type:Boolean,default:true},initialReferences:{type:Object,default:()=>({})}}),emit=defineEmits(['selection-change']),v=reactive(useDocumentExtractionInput(props,emit));
</script>
<style scoped>
.el-alert{margin:10px 0}.el-pagination{margin-top:12px}pre{white-space:pre-wrap;overflow-wrap:anywhere;max-height:45vh;overflow:auto;padding:12px;border:1px solid #dcdfe6}code{overflow-wrap:anywhere}[role=alert]{color:#b42318}
</style>
