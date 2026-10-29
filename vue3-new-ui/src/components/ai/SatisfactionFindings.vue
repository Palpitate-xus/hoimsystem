<template>
  <section aria-label="完整评价统计与部分主题结果">
    <p v-if="!allowed">当前会话不能读取评价结果。</p>
    <p v-if="checking" role="status">正在核对完整安全来源、原统计和逐字引文……</p>
    <p v-if="error" role="alert">{{ error }}</p>
    <article v-if="source" aria-label="已核对完整评价结果">
      <p>原记录日历 {{ source.safe_snapshot.date_from }} 至 {{ source.safe_snapshot.date_to }}，时区未知。{{ source.safe_snapshot.scope_kind === 'hospital_reviews' ? '全院已记录评价' : `显式有限医生集合（${source.safe_snapshot.doctor_cohort_size}名），科室采用当前档案` }}。</p>
      <p>已核对 {{ source.safe_snapshot.member_manifest.length }} 项评价及摘录版本；日期未知 {{ source.safe_snapshot.unknown_date_member_count }} 条，关联未核实 {{ source.safe_snapshot.unresolved_parent_count }} 条。</p>
      <table aria-label="已记录评分精确统计"><thead><tr><th>原记录范围</th><th>评价条数</th><th>有效 1–5 评分</th><th>NULL 评分</th><th>异常评分</th><th>有效评分精确均分</th></tr></thead><tbody><tr v-for="[label,stats] in [['全部成员',source.safe_snapshot.all_member_statistics],['已知日期本期成员',source.safe_snapshot.known_period_statistics]]" :key="label"><th>{{ label }}</th><td>{{ stats.record_count }}</td><td>{{ stats.valid_score_count }}</td><td>{{ stats.null_score_count }}</td><td>{{ stats.invalid_score_count }}</td><td>{{ stats.mean_valid_score === null ? '未知（没有有效评分）' : `${stats.mean_valid_score.numerator}/${stats.mean_valid_score.denominator}` }}</td></tr></tbody></table>
      <p>全部成员原评分直方图：<span v-for="score in [1,2,3,4,5]" :key="score">{{ score }} 分 {{ source.safe_snapshot.all_member_statistics.histogram[String(score)] }} 条；</span></p>
      <p>统计单位为评价记录条数。</p>
      <template v-if="result">
        <details><summary>任务摘要原文</summary><p>{{ result.summary }}</p></details>
        <h3>部分摘录主题，均待人工核查</h3>
        <p v-if="result.satisfaction_analysis.themes.length === 0">本次未生成评价主题。</p>
        <template v-else>
          <p>第 {{ themeIndex + 1 }} / {{ result.satisfaction_analysis.themes.length }} 项，请结合引用核对主题。</p>
          <article v-if="theme" aria-label="待人工核查摘录主题"><h4>{{ theme.title }}</h4><p>{{ theme.observation }}</p><p>待澄清：{{ theme.clarification_question }}</p><section v-for="(citation,index) in theme.citations" :key="index" aria-label="逐字摘录引用"><details><summary>引文位置</summary><p>原摘录码点 [{{ citation.start }}, {{ citation.end }})；技术标识 {{ citation.excerpt_token }}</p></details><pre>{{ citation.quote }}</pre></section></article>
          <el-button :disabled="themeIndex === 0" @click="themeIndex--">上一项主题</el-button><el-button :disabled="themeIndex + 1 >= result.satisfaction_analysis.themes.length" @click="themeIndex++">下一项主题</el-button>
        </template>
        <ul aria-label="统计与主题限定"><li v-for="warning in noticeList(result.warnings)" :key="warning">{{ warning }}</li><li v-for="missing in noticeList(result.missing_data)" :key="missing">{{ missing }}</li></ul>
      </template>
      <p v-else>本任务尚无已接收的完整主题结果。</p>
      <el-button :loading="evidenceChecking" @click="openEvidence">核对本次安全冻结依据</el-button>
      <details><summary>来源核验详情</summary><p>原评论摘要用于核对来源，全文保存在院内。</p></details>
    </article>
    <el-dialog :model-value="evidence !== null || evidenceChecking" title="本次安全冻结依据" width="80%" @update:model-value="v => { if (!v) closeEvidence(); }">
      <article v-if="evidence" aria-label="已核对安全冻结依据"><p>{{ evidence.title }}</p><details><summary>来源核验标识</summary><p>完整安全投影 SHA：{{ evidence.source.safe_projection_hash }}</p></details><p>原件治理状态 {{ evidence.case.status }}；原始发布投影保持冻结。受保护原评论未返回，原文 SHA 无法从安全视图重建。</p><section v-for="excerpt in shownExcerpts" :key="excerpt.excerpt_token"><p>实际受审摘录 {{ excerpt.excerpt_token }}</p><pre>{{ excerpt.text }}</pre></section><el-button :disabled="excerptPage === 0" @click="excerptPage--">上一页摘录</el-button><el-button :disabled="(excerptPage + 1) * 20 >= evidence.source.safe_snapshot.selected_excerpts.length" @click="excerptPage++">下一页摘录</el-button></article><template #footer><el-button @click="closeEvidence">关闭安全依据</el-button></template>
    </el-dialog>
  </section>
</template>
<script setup>
import { noticeText, noticeList } from "@/utils/noticeText.cjs";
import{computed}from'vue';
import{useSatisfactionFindings}from'./useSatisfactionFindings';
const props=defineProps({packet:{type:Object,default:null},result:{type:Object,default:null},references:{type:Object,default:null},auditOnly:{type:Boolean,default:false},active:{type:Boolean,default:true}}),emit=defineEmits(['invalidate']);
const{allowed,source,result,checking,error,themeIndex,evidence,evidenceChecking,excerptPage,closeEvidence,openEvidence}=useSatisfactionFindings(props,emit);
const theme=computed(()=>result.value?.satisfaction_analysis.themes[themeIndex.value]||null),shownExcerpts=computed(()=>evidence.value?.source.safe_snapshot.selected_excerpts.slice(excerptPage.value*20,excerptPage.value*20+20)||[]);
</script>
<style scoped>
pre{white-space:pre-wrap;overflow-wrap:anywhere}table{border-collapse:collapse;width:100%}td,th{border:1px solid #dcdfe6;padding:6px;text-align:left}article{overflow-wrap:anywhere}
</style>
