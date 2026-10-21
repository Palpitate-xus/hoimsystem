<template>
  <section aria-label="完整评价统计与部分主题结果">
    <p v-if="!allowed">当前会话不能读取评价结果。</p>
    <p v-if="checking" role="status">正在核对完整安全来源、原统计和逐字引文……</p>
    <p v-if="error" role="alert">{{ error }}</p>
    <article v-if="source" aria-label="已核对完整评价结果">
      <p>原记录日历 {{ source.safe_snapshot.date_from }} 至 {{ source.safe_snapshot.date_to }}，时区未知。{{ source.safe_snapshot.scope_kind === 'hospital_reviews' ? '全院已记录评价' : `显式有限医生集合（${source.safe_snapshot.doctor_cohort_size} 名），不是历史科室统计` }}。</p>
      <p>完整成员 {{ source.safe_snapshot.member_manifest.length }} 个评价及摘录版本根；原日期未知 {{ source.safe_snapshot.unknown_date_member_count }} 条，实际父链未能核实 {{ source.safe_snapshot.unresolved_parent_count }} 条。</p>
      <table aria-label="已记录评分精确统计"><thead><tr><th>原记录范围</th><th>评价条数</th><th>有效 1–5 评分</th><th>NULL 评分</th><th>异常评分</th><th>有效评分精确均分</th></tr></thead><tbody><tr v-for="[label,stats] in [['全部成员',source.safe_snapshot.all_member_statistics],['已知日期本期成员',source.safe_snapshot.known_period_statistics]]" :key="label"><th>{{ label }}</th><td>{{ stats.record_count }}</td><td>{{ stats.valid_score_count }}</td><td>{{ stats.null_score_count }}</td><td>{{ stats.invalid_score_count }}</td><td>{{ stats.mean_valid_score === null ? '未知（没有有效评分）' : `${stats.mean_valid_score.numerator}/${stats.mean_valid_score.denominator}` }}</td></tr></tbody></table>
      <p>全部成员原评分直方图：<span v-for="score in [1,2,3,4,5]" :key="score">{{ score }} 分 {{ source.safe_snapshot.all_member_statistics.histogram[String(score)] }} 条；</span></p>
      <p>评价条数不是去重人数、就诊次数或应答次数；不计算 NPS、应答率、投诉处理率或总体满意率。</p>
      <template v-if="result">
        <p>{{ result.summary }}</p>
        <h3>部分摘录主题，均待人工核查</h3>
        <p v-if="result.satisfaction_analysis.themes.length === 0">本次没有提出主题，不表示全部满意或没有问题。</p>
        <template v-else>
          <p>第 {{ themeIndex + 1 }} / {{ result.satisfaction_analysis.themes.length }} 项；逐字引文一致不证明解释、代表性或因果。</p>
          <article v-if="theme" aria-label="待人工核查摘录主题"><h4>{{ theme.title }}</h4><p>{{ theme.observation }}</p><p>待澄清：{{ theme.clarification_question }}</p><section v-for="(citation,index) in theme.citations" :key="index" aria-label="逐字摘录引用"><p>原摘录码点 [{{ citation.start }}, {{ citation.end }})；技术标识 {{ citation.excerpt_token }}</p><pre>{{ citation.quote }}</pre></section></article>
          <el-button :disabled="themeIndex === 0" @click="themeIndex--">上一项主题</el-button><el-button :disabled="themeIndex + 1 >= result.satisfaction_analysis.themes.length" @click="themeIndex++">下一项主题</el-button>
        </template>
        <ul aria-label="统计与主题限定"><li v-for="warning in result.warnings" :key="warning">{{ warning }}</li><li v-for="missing in result.missing_data" :key="missing">{{ missing }}</li></ul>
      </template>
      <p v-else>本任务尚无已接收的完整主题结果。</p>
      <el-button :loading="evidenceChecking" @click="openEvidence">核对本次安全冻结依据</el-button>
      <p>受保护原评论全文 SHA 是服务器核验的 opaque 锚；普通安全胶囊不能重建原评论，也不构成匿名保证。</p>
    </article>
    <el-dialog :model-value="evidence !== null || evidenceChecking" title="本次安全冻结依据" width="80%" @update:model-value="v => { if (!v) closeEvidence(); }">
      <article v-if="evidence" aria-label="已核对安全冻结依据"><p>{{ evidence.title }}</p><p>完整安全投影 SHA：{{ evidence.source.safe_projection_hash }}</p><p>原件治理状态 {{ evidence.case.status }}；原始发布投影保持冻结。受保护原评论未返回，原文 SHA 无法从安全视图重建。</p><section v-for="excerpt in shownExcerpts" :key="excerpt.excerpt_token"><p>实际受审摘录 {{ excerpt.excerpt_token }}</p><pre>{{ excerpt.text }}</pre></section><el-button :disabled="excerptPage === 0" @click="excerptPage--">上一页摘录</el-button><el-button :disabled="(excerptPage + 1) * 20 >= evidence.source.safe_snapshot.selected_excerpts.length" @click="excerptPage++">下一页摘录</el-button></article><template #footer><el-button @click="closeEvidence">关闭安全依据</el-button></template>
    </el-dialog>
  </section>
</template>
<script setup>
import{computed}from'vue';
import{useSatisfactionFindings}from'./useSatisfactionFindings';
const props=defineProps({packet:{type:Object,default:null},result:{type:Object,default:null},references:{type:Object,default:null},auditOnly:{type:Boolean,default:false},active:{type:Boolean,default:true}}),emit=defineEmits(['invalidate']);
const{allowed,source,result,checking,error,themeIndex,evidence,evidenceChecking,excerptPage,closeEvidence,openEvidence}=useSatisfactionFindings(props,emit);
const theme=computed(()=>result.value?.satisfaction_analysis.themes[themeIndex.value]||null),shownExcerpts=computed(()=>evidence.value?.source.safe_snapshot.selected_excerpts.slice(excerptPage.value*20,excerptPage.value*20+20)||[]);
</script>
<style scoped>
pre{white-space:pre-wrap;overflow-wrap:anywhere}table{border-collapse:collapse;width:100%}td,th{border:1px solid #dcdfe6;padding:6px;text-align:left}article{overflow-wrap:anywhere}
</style>
