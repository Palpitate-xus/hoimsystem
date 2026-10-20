<template>
  <section v-if="findings" class="operational-findings">
    <h4>本次原始业务资料</h4>
    <p>{{ findings.scope === 'department' ? '所属科室范围' : findings.source_domain === 'inventory' ? '所选库存品种范围' : '全院范围' }} · {{ findings.since }} 至 {{ findings.until }}</p>
    <p>资料读取时刻：{{ findings.snapshot_time || '旧任务未留存' }}；任务结果保留本次读取的资料版本。</p>
    <p>{{ findings.scope_note }}</p>
    <p v-if="findings.department_names?.length">科室：{{ findings.department_names.join('、') }}</p>
    <p v-for="(item, index) in findings.missing_data || []" :key="'missing-' + index" class="data-gap">{{ item }}</p>
    <p v-if="findings.truncated_sources?.length" class="data-gap">本次有资料截断，请缩小日期、科室或品种范围，不能把部分清单当作完整序列。</p>
    <template v-if="findings.feedback_rating_summary">
      <h4>已记录评价评分</h4><p>{{ findings.feedback_rating_summary.definition_note }}</p>
      <el-descriptions :column="2" border>
        <el-descriptions-item label="原评价行数">{{ findings.feedback_rating_summary.record_count ?? '未知' }}</el-descriptions-item>
        <el-descriptions-item label="关联就诊记录数">{{ findings.feedback_rating_summary.distinct_recorded_visit_count ?? '未知' }}</el-descriptions-item>
        <el-descriptions-item label="有效评分行数">{{ findings.feedback_rating_summary.valid_score_record_count ?? '未知' }}</el-descriptions-item>
        <el-descriptions-item label="有效评分均值">{{ findings.feedback_rating_summary.mean_recorded_score ?? '未知' }}</el-descriptions-item>
        <el-descriptions-item label="越界评分行数">{{ findings.feedback_rating_summary.out_of_range_score_record_count ?? '未知' }}</el-descriptions-item>
        <el-descriptions-item label="未提供评论原文行数">{{ findings.feedback_rating_summary.withheld_comment_record_count ?? '未知' }}</el-descriptions-item>
      </el-descriptions>
      <el-button link @click="$emit('inspect', findings.feedback_rating_summary.source_id)">查看评分汇总依据</el-button>
    </template>
    <el-collapse>
      <el-collapse-item v-for="section in series" :key="section.key" :title="section.title" :name="section.key">
        <p>{{ section.data.definition_note || section.data.status_note }}</p>
        <p v-if="section.data.planning_window">计划区间：{{ section.data.planning_window.join(' 至 ') }}</p>
        <p v-if="section.key === 'surgical_recorded_overlaps'">可检查原区间数：{{ section.data.checked_intervals ?? '未知' }}；未检查或非活动排台数：{{ section.data.uncheckable_or_inactive_schedules ?? '未知' }}。没有线索不代表排台可行。</p>
        <p v-if="section.data.missing_dates?.length">未汇总日期 {{ section.data.missing_dates.length }} 天，保持缺失，未补零。</p>
        <el-table :data="section.rows" max-height="300" empty-text="本次范围未取得相应原始记录">
          <el-table-column v-for="column in section.data.columns" :key="column" :label="labels[column] || column" min-width="110"><template #default="{ row }">{{ row[column] ?? '未知' }}</template></el-table-column>
        </el-table>
        <el-button link @click="$emit('inspect', section.data.source_id)">查看{{ section.title }}依据</el-button>
      </el-collapse-item>
    </el-collapse>
    <template v-if="findings.ward_capacity">
      <h4>当前病区与床位状态</h4><p>{{ findings.ward_capacity.definition_note }}</p>
      <el-table :data="findings.ward_capacity.wards" max-height="300">
        <el-table-column prop="name" label="病区" min-width="140" /><el-table-column prop="configured_bed_count" label="配置床数" width="100" /><el-table-column prop="loaded_bed_record_count" label="加载床行数" width="110" />
        <el-table-column prop="recorded_free_beds_in_active_ward" label="启用病区空闲状态数" width="160" />
        <el-table-column label="配置与记录" width="120"><template #default="{ row }">{{ row.configured_count_matches_loaded === true ? '一致' : row.configured_count_matches_loaded === false ? '不一致，待核实' : '未知' }}</template></el-table-column>
      </el-table>
      <el-button link @click="$emit('inspect', findings.ward_capacity.source_id)">查看床位状态依据</el-button>
    </template>
    <template v-if="findings.supply_inventory">
      <h4>所选品种的原始库存</h4><p>{{ findings.supply_inventory.scope_note }}</p>
      <el-table v-if="findings.supply_inventory.drugs?.length" :data="findings.supply_inventory.drugs" max-height="280">
        <el-table-column prop="name" label="药品" min-width="150" /><el-table-column label="目录库存原计数" width="130"><template #default="{ row }">{{ row.catalog_stock ?? '未知' }}</template></el-table-column>
        <el-table-column label="批次库存合计" width="130"><template #default="{ row }">{{ row.all_batch_stock_sum ?? '未知' }}</template></el-table-column>
        <el-table-column label="库存计数单位" width="120"><template #default="{ row }">{{ row.stock_count_unit || '未记录' }}</template></el-table-column>
        <el-table-column label="目录与批次" width="120"><template #default="{ row }">{{ row.catalog_matches_batch_sum === true ? '一致' : row.catalog_matches_batch_sum === false ? '不一致，待核实' : '未知' }}</template></el-table-column>
      </el-table>
      <el-table v-if="findings.supply_inventory.consumables?.length" :data="findings.supply_inventory.consumables" max-height="240">
        <el-table-column prop="name" label="耗材" /><el-table-column label="原库存数量"><template #default="{ row }">{{ row.stock ?? '未知' }}</template></el-table-column><el-table-column prop="unit" label="原单位" />
      </el-table>
      <p>{{ findings.supply_inventory.batch_note }}</p><p>{{ findings.supply_inventory.drug_ledger_daily?.definition_note }}</p><p>{{ findings.supply_inventory.consumable_trace_daily?.definition_note }}</p><p>{{ findings.supply_inventory.purchase_note }}</p>
      <el-button link @click="$emit('inspect', findings.supply_inventory.source_id)">查看库存与原始流水依据</el-button>
    </template>
  </section>
</template>

<script setup>
import { computed } from "vue";
const props = defineProps({ findings: { type: Object, default: null } });
defineEmits(["inspect"]);
const sections = [{ key: "saved_daily_metrics", title: "已保存日统计" }, { key: "recorded_registrations", title: "挂号原记录汇总" }, { key: "recorded_hourly_registrations", title: "挂号原记录小时汇总" }, { key: "recorded_admissions", title: "入院原记录汇总" }, { key: "recorded_discharges", title: "出院时间汇总" }, { key: "recorded_schedules", title: "当前周期排班" }, { key: "recorded_schedule_changes", title: "计划区间排班变更" }, { key: "surgical_applications", title: "手术申请原记录" }, { key: "surgical_schedules", title: "计划区间排台原记录" }, { key: "surgical_recorded_overlaps", title: "原时间同资源交叠线索" }, { key: "surgical_completed_intervals", title: "历史已完成排台原起止" }, { key: "feedback_rating_series", title: "原评分日期分组" }];
const series = computed(() => {
  const items = sections.filter(item => props.findings?.[item.key]).map(item => ({ ...item, data: props.findings[item.key] }));
  const inventory = props.findings?.supply_inventory;
  for (const [key, title] of [["drug_ledger_daily", "药品原台账汇总"], ["consumable_trace_daily", "耗材追溯汇总"]]) {
    if (inventory?.[key]?.columns) items.push({ key, title, data: { ...inventory[key], source_id: inventory.source_id } });
  }
  return items.map(item => ({ ...item, rows: (item.data.rows || []).map(row => Object.fromEntries((item.data.columns || []).map((column, index) => [column, row[index]]))) }));
});
const labels = { date: "日期", updated_at: "汇总更新时间", current_record_status: "当前原状态", record_count: "原记录数", outpatient_visits: "原门诊统计", emergency_visits: "原急诊统计", admissions: "原入院统计", discharges: "原出院统计", active_inpatients: "原在院估算", prescriptions: "处方统计", lab_orders: "检验统计", imaging_orders: "影像统计", critical_labs: "危急值统计", successful_payments: "成功支付数", revenue: "原收入统计", refunds: "原退款统计", average_queue_wait_minutes: "原平均候诊分钟", recorded_hour: "原记录小时", schedule_id: "排班标识", doctor_id: "医生标识", department_id: "科室标识", recorded_weekday: "原星期", recorded_period: "原时段编码", current_shared_stock: "当前共享余量", specialist: "原号类", recorded_title: "档案职称", request_id: "申请标识", target_date: "目标日期", request_type: "原申请类型", extra_slots: "原加号数量", request_status: "原申请状态", drug_id: "药品标识", consumable_id: "耗材标识", transaction_type: "原台账类型", raw_quantity_sum: "原数量合计", recorded_stock_delta_sum: "前后库存差额合计", consistent_quantity_delta_count: "数量差额一致记录数", recorded_action: "原追溯动作", negative_quantity_record_count: "负数量记录数" };
Object.assign(labels, { application_id: "手术申请标识", surgery_name: "原手术名称", surgery_code: "原手术编码", surgery_level: "原手术级别", anesthesia_type: "原麻醉类型", scheduled_date: "原申请日期", application_status: "原申请状态", operating_room: "原手术室", surgery_date: "原排台日期", recorded_start: "原开始记录", recorded_end: "原结束记录", surgeon_id: "原主刀标识", anesthesiologist_id: "原麻醉医生标识", assistant_doctor_ids: "原助手标识", scrub_nurse_id: "原器械护士标识", circulating_nurse_id: "原巡回护士标识", schedule_status: "原排台状态", left_schedule_id: "交叠排台一", right_schedule_id: "交叠排台二", shared_resource_references: "共同资源引用", recorded_score: "有效原评分", withheld_comment_record_count: "未提供评论原文行数", out_of_range_score_record_count: "越界评分行数" });
</script>

<style scoped>
.operational-findings { line-height: 1.7; margin: 16px 0; }
.data-gap { color: #9a6700; }
</style>
