<template>
  <section v-if="binding" class="forecast-findings" aria-label="挂号记录数统计预测依据">
    <h4>每日挂号原记录数 · {{ analysis ? '统计预测与回溯评估' : '冻结历史来源' }}</h4>
    <p>目标为每日所有状态挂号记录数（条/日），不代表实际到诊、独立患者或临床风险。覆盖与原无时区钟点解释由超级管理员声明，未独立核实外部完整性；本次计算不证明运营效果已验证，也不自动排班。</p>
    <p>{{ binding.scope === 'hospital' ? '全院' : `科室 #${binding.department_id}` }} · 原历史 {{ binding.date_from }} 至 {{ binding.date_to }} · 原钟点时区解释 {{ binding.timezone }}；没有转换既有数据库钟点。</p>
    <p class="hash">来源 {{ binding.source_id }}<br />内容摘要 {{ binding.content_hash }}<br />原登记摘要 {{ binding.registration_digest }}<br />覆盖依据摘要 {{ binding.coverage_note_hash }}</p><p>覆盖声明时间 {{ binding.coverage_attested_at }}；无法分日而排除的无时间记录 {{ binding.unassigned_time_records }} 条。</p>
    <el-button link @click="$emit('inspect', binding.source_id)">核对冻结挂号来源依据</el-button>
    <p v-for="note in findings?.missing_data || []" :key="note">{{ note }}</p>
    <el-collapse><el-collapse-item title="查看原始冻结历史"><p>以下仅展示保存来源中的值；确认的0保留为0，缺失值保持未知，不补零。</p><el-table :data="source?.observations || []" max-height="300" aria-label="原始冻结历史" empty-text="本任务未保留可展示的逐日原历史"><el-table-column prop="date" label="原日期" /><el-table-column label="原记录数"><template #default="{ row }">{{ row.value ?? '未知' }}</template></el-table-column></el-table></el-collapse-item></el-collapse>
    <template v-if="analysis && matches">
      <p>固定算法：近4周同星期均值（weekday_mean_4w），未通过回测择优选模。自历史末日次日起算 {{ analysis.forecast[0]?.date }} 至 {{ analysis.forecast.at(-1)?.date }}，{{ analysis.horizon_days }} 天；旧窗口可能只是在过去日期外推，并非默认从今天开始。</p>
      <p>区间为名义90%的经验误差区间，不保证未来90%覆盖；时序相关及数据变化会影响覆盖。校准分位值是绝对误差半径，不是概率。</p>
      <el-table :data="analysis.forecast" aria-label="每日点预测与经验区间"><el-table-column prop="date" label="预测日期" width="115" /><el-table-column prop="lead_days" label="提前天数" width="90" /><el-table-column prop="point" label="点预测（条）" /><el-table-column prop="lower" label="经验下界" /><el-table-column prop="upper" label="经验上界" /><el-table-column prop="calibration_n" label="校准样本数" /><el-table-column prop="calibration_order" label="排序位次（从1起）" /><el-table-column prop="calibration_quantile" label="绝对误差半径" /><el-table-column prop="calibration_last_target_date" label="校准末目标日" width="125" /></el-table>
      <h4>当前快照的回溯评估</h4><p>基于当前确认快照的回溯评估，并非当时可得数据回放（{{ analysis.backtest.data_basis }}）。{{ analysis.backtest.origin_count }} 折，原点 {{ analysis.backtest.origin_from }} 至 {{ analysis.backtest.origin_to }}；{{ analysis.backtest.forecast_pair_count }} 个“原点×提前天数”预测对，只有 {{ analysis.backtest.unique_target_dates }} 个不同目标日期，目标日期重叠，不能当独立样本。</p>
      <el-table :data="comparisons" aria-label="回测算法与误差分母"><el-table-column prop="name" label="算法" min-width="180" /><el-table-column prop="metrics.n" label="预测对数n" width="100" /><el-table-column prop="metrics.mae" label="MAE（条）" /><el-table-column prop="metrics.rmse" label="RMSE（条）" /><el-table-column label="WAPE"><template #default="{ row }">{{ wape(row.metrics) }}</template></el-table-column><el-table-column prop="metrics.wape_numerator_abs_error" label="绝对误差合计（分子）" /><el-table-column prop="metrics.wape_denominator_actual" label="实际量合计（分母）" /><el-table-column label="MASE"><template #default="{ row }">{{ mase(row.metrics) }}</template></el-table-column></el-table>
      <p>WAPE=绝对误差合计÷实际量合计，表中比率乘100%显示；实际量合计为0时不可计算。MASE按各原点之前的7日滞后绝对差均值缩放，任一原点尺度为0则整体未知；不是0误差。</p>
      <p>主算法MASE：已缩放 {{ analysis.backtest.primary_metrics.mase_scaled_pairs }} 对，零尺度 {{ analysis.backtest.primary_metrics.mase_zero_scale_pairs }} 对。</p>
      <p>经验区间回溯覆盖 {{ analysis.backtest.intervals.covered_count }}/{{ analysis.backtest.intervals.evaluated_count }} 个预测对（{{ percentage(analysis.backtest.intervals.empirical_coverage) }}），不同目标日期 {{ analysis.backtest.intervals.unique_target_dates }}；平均宽度 {{ analysis.backtest.intervals.mean_width }} 条，校准样本数 {{ analysis.backtest.intervals.calibration_n_min }} 至 {{ analysis.backtest.intervals.calibration_n_max }}。不保证未来覆盖。</p>
      <el-collapse><el-collapse-item title="逐提前天数误差与区间分母"><el-table :data="leads" max-height="380" aria-label="逐提前天数误差与区间分母"><el-table-column prop="lead_days" label="提前天数" /><el-table-column prop="metrics.n" label="预测对数" /><el-table-column prop="metrics.mae" label="MAE" /><el-table-column prop="metrics.rmse" label="RMSE" /><el-table-column label="WAPE"><template #default="{ row }">{{ wape(row.metrics) }}</template></el-table-column><el-table-column label="MASE"><template #default="{ row }">{{ mase(row.metrics) }}</template></el-table-column><el-table-column label="区间覆盖/分母"><template #default="{ row }">{{ row.interval?.covered_count ?? '未知' }}/{{ row.interval?.evaluated_count ?? '未知' }} · {{ percentage(row.interval?.empirical_coverage) }}</template></el-table-column></el-table></el-collapse-item><el-collapse-item title="核对算法、逐原点尺度与运行指纹"><pre>{{ JSON.stringify({ source_binding: analysis.source_binding, backtest: analysis.backtest, local_runtime: analysis.local_runtime, instructions_digest: analysis.instructions_digest }, null, 2) }}</pre></el-collapse-item></el-collapse>
    </template>
    <p v-else-if="analysis" role="alert">预测与原来源绑定不一致，不展示数值结果；请核查任务。</p>
  </section>
</template>
<script setup>
import { computed } from "vue";
const props = defineProps({ findings: { type: Object, default: null }, analysis: { type: Object, default: null } });
defineEmits(["inspect"]);
const source = computed(() => props.findings?.forecast_source), binding = computed(() => source.value ?? props.analysis?.source_binding);
const matches = computed(() => {
  if (!source.value) return true;
  const { observations, ...expected } = source.value, actual = props.analysis?.source_binding;
  return !!actual && Object.keys(expected).length === Object.keys(actual).length && Object.keys(expected).every(key => expected[key] === actual[key]);
});
const recipes = { weekday_mean_4w: "近4周同星期均值（主算法）", seasonal_naive_7d: "7日季节朴素基线", rolling_mean_7d: "7日滚动均值基线", rolling_mean_28d: "28日滚动均值基线" };
const comparisons = computed(() => props.analysis ? [{ name: recipes[props.analysis.recipe], metrics: props.analysis.backtest.primary_metrics }, ...props.analysis.backtest.baselines.map(row => ({ name: recipes[row.recipe] ?? row.recipe, metrics: row.metrics }))] : []);
const leads = computed(() => props.analysis?.backtest.primary_by_lead.map(row => ({ ...row, interval: props.analysis.backtest.intervals.by_lead.find(item => item.lead_days === row.lead_days) })) ?? []);
const percentage = value => value == null || !Number.isFinite(value) ? "未知" : `${(value * 100).toFixed(2)}%`;
const wape = metrics => metrics.wape == null ? "不可计算（实际量合计为0）" : percentage(metrics.wape);
const mase = metrics => metrics.mase == null ? "未知（存在零原点尺度）" : String(metrics.mase);
</script>
<style scoped>.forecast-findings { line-height: 1.7; margin: 16px 0; }.hash, pre { overflow-wrap: anywhere; }pre { white-space: pre-wrap; max-height: 420px; overflow: auto; }</style>
