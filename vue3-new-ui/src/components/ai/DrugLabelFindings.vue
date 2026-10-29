<template>
 <section aria-label="说明书逐字字段结果" class="drug-label-findings">
  <el-alert v-if="!v.sessionAllowed" title="仅当前药师或超级管理员可读取已授权说明书任务" type="warning" :closable="false" />
  <el-button v-if="v.closed&&v.sessionAllowed&&active" @click="v.reread">重新读取本次说明书任务</el-button>
  <template v-if="v.authorized">
   <el-button @click="v.close">关闭并清除说明书结果</el-button>
   <p v-if="v.busy" role="status">正在核对说明书来源与结果…</p>
   <p v-if="v.error" role="alert">{{ v.error }}</p>
   <template v-if="v.proof">
    <el-alert title="字段草稿待药师复核，请结合完整说明书判断含义和适用条件" type="warning" :closable="false" />
    <p v-if="auditOnly" aria-label="说明书冻结审计">冻结审计只读；当前失效来源未恢复执行、签署或发布资格。</p>
    <p aria-label="说明书读取范围">目录 {{ v.record.snapshot.identity.pharmaceutical_id }}：{{ v.source.sku.name===null?'名称未记录':v.source.sku.name }}；提交者声明版本 {{ v.source.declared_version }}。</p>
    <details><summary>来源核验详情</summary><p>原文 {{ v.source.raw_bytes_length }} UTF8字节 / {{ v.source.codepoint_length }} Unicode码点；未归一化、改写或截断。</p><p aria-label="说明书核验范围">{{ v.proofNote }}</p><p v-if="v.proof.run">Run原时钟为旧表秒级naive ISO，Artifact创建/接收时钟另保留UTC6。</p></details>
    <p>签署针对当前提供的说明书版本；正式采用前仍需核对官方版本和适用性。</p>
    <p v-if="v.proof.run" aria-label="说明书任务状态">{{ states[v.proof.run.status] }}</p>
    <p v-if="v.proof.run" aria-label="说明书实际用量">输入用量：{{ shown(v.proof.run.input_tokens) }}；输出用量：{{ shown(v.proof.run.output_tokens) }}；{{ v.receipt===null?'实际调用与用量回执待返回':v.receipt.model_call_attempted===null?'是否实际调用未知':v.receipt.model_call_attempted?'模型已调用':'已确认模型未调用' }}。</p>
    <template v-if="v.result">
     <p>已整理 {{ v.rows.length }} 段待复核引文。</p><details><summary>任务摘要原文</summary><p aria-label="说明书模型摘要" v-if="noticeText(v.result.summary)">{{ noticeText(v.result.summary) }}</p></details>
     <p>{{ coverageNote }}</p>
     <p v-if="!v.rows.length">本次未生成字段草稿。</p>
     <el-table v-if="v.rows.length" :data="v.visibleRows" aria-label="说明书逐字字段表">
      <el-table-column label="模型类别（未核实）"><template #default="{row}">{{ labels[row.field] }}</template></el-table-column>
      <el-table-column label="原文位置"><template #default="{row}">[{{ row.start }}, {{ row.end }})</template></el-table-column>
      <el-table-column prop="review_question" label="待药师复核问题" />
      <el-table-column label="逐字依据"><template #default="{row}"><el-button @click="v.inspect(row)">查看第{{ row.fieldIndex+1 }}项第{{ row.spanIndex+1 }}段引文</el-button></template></el-table-column>
     </el-table>
     <el-pagination v-if="v.rows.length>10" v-model:current-page="v.page" :page-size="10" :total="v.rows.length" layout="prev,pager,next" aria-label="说明书引文分页" />
    </template>
    <p v-else>此状态没有已接收字段草稿；未改写药品目录、知识或临床规则。</p>
    <div><el-button @click="v.showOriginal">{{ v.rawOpen?'收起完整说明书原文':'展开完整说明书原文' }}</el-button><el-button @click="v.showPrivate">{{ v.privateOpen?'收起来源核验资料':'来源核验资料' }}</el-button></div>
    <pre v-if="v.rawOpen" aria-label="任务完整说明书原文">{{ v.source.text }}</pre>
    <pre v-if="v.privateOpen" aria-label="任务完整来源治理原件">{{ JSON.stringify(v.record,null,2) }}</pre>
    <p>未知或未提供：{{ v.source.missing_catalog_or_authority_evidence.join('、') }}。条款须审核后另行保存或发布。</p>
   </template>
  </template>
  <el-dialog :model-value="v.authorized&&v.quote!==null" title="本次原文逐字区间" append-to-body destroy-on-close @update:model-value="open=>{if(!open)v.quote=null}">
   <template v-if="v.quote"><p>原文位置 [{{ v.quote.start }}, {{ v.quote.end }})；类别待药师复核。</p><pre aria-label="说明书字段逐字引文">{{ v.quote.quote }}</pre><p>{{ v.quote.review_question }}</p></template>
  </el-dialog>
 </section>
</template>
<script setup>
import { noticeText, noticeList } from "@/utils/noticeText.cjs";
import {reactive} from 'vue';
import {drugLabelCoverageNote as coverageNote} from '@/api/ai/drugLabelResults';
import {useDrugLabelFindings} from './useDrugLabelFindings';
const props=defineProps({run:{type:Object,default:null},trace:{type:Object,default:null},preview:{type:Object,default:null},references:{type:Object,default:null},pharmaceuticalId:{type:Number,default:null},expectedRunId:{type:String,default:null},active:{type:Boolean,default:true},auditOnly:{type:Boolean,default:false},configRevision:{type:[Number,String],default:null}}),emit=defineEmits(['invalidate','reload','inspect']),v=reactive(useDrugLabelFindings(props,emit));
const states={queued:'排队中',running:'执行中',succeeded:'逐字字段草稿已接收，未审核',failed:'任务失败',cancelled:'任务已取消'},shown=x=>x===null?'未知':String(x);
const labels={product_name:'药名原文字段',composition:'成分原文字段',strength:'规格原文字段',dosage_form:'剂型原文字段',indications:'适应症原文字段',contraindications:'禁忌原文字段',dosage_administration:'用法原文字段',precautions:'注意事项原文字段',interactions:'相互作用原文字段',adverse_reactions:'不良反应原文字段',special_populations:'特殊人群原文字段',storage:'储存原文字段',manufacturer:'厂家原文字段',authorization:'批准信息原文字段',other:'其它原文字段'};
</script>
<style scoped>
.drug-label-findings{display:grid;gap:12px}pre{white-space:pre-wrap;overflow-wrap:anywhere;max-height:360px;overflow:auto}
</style>
