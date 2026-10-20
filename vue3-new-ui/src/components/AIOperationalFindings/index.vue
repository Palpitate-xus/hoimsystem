<template>
  <section v-if="findings" class="operational-findings">
    <h4>本次原始业务资料</h4>
    <p>{{ findings.scope === 'department' ? '所属科室范围' : findings.source_domain === 'inventory' ? '所选库存品种范围' : '全院范围' }} · {{ findings.since }} 至 {{ findings.until }}</p>
    <p>{{ findings.scope_note }}</p>
    <p v-for="(item, index) in findings.missing_data || []" :key="'missing-' + index" class="data-gap">{{ item }}</p>
    <p v-if="findings.truncated_sources?.length" class="data-gap">本次有资料截断，请缩小日期、科室或品种范围，不能把部分清单当作完整序列。</p>
    <el-collapse>
      <el-collapse-item v-for="section in series" :key="section.key" :title="section.title" :name="section.key">
        <p>{{ section.data.definition_note }}</p>
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
const sections = [{ key: "saved_daily_metrics", title: "已保存日统计" }, { key: "recorded_registrations", title: "挂号原记录汇总" }, { key: "recorded_admissions", title: "入院原记录汇总" }, { key: "recorded_discharges", title: "出院时间汇总" }];
const series = computed(() => sections.filter(item => props.findings?.[item.key]).map(item => {
  const data = props.findings[item.key];
  return { ...item, data, rows: (data.rows || []).map(row => Object.fromEntries((data.columns || []).map((column, index) => [column, row[index]]))) };
}));
const labels = { date: "日期", updated_at: "汇总更新时间", current_record_status: "当前原状态", record_count: "原记录数", outpatient_visits: "原门诊统计", emergency_visits: "原急诊统计", admissions: "原入院统计", discharges: "原出院统计", active_inpatients: "原在院估算", prescriptions: "处方统计", lab_orders: "检验统计", imaging_orders: "影像统计", critical_labs: "危急值统计", successful_payments: "成功支付数", revenue: "原收入统计", refunds: "原退款统计", average_queue_wait_minutes: "原平均候诊分钟" };
</script>

<style scoped>
.operational-findings { line-height: 1.7; margin: 16px 0; }
.data-gap { color: #9a6700; }
</style>
