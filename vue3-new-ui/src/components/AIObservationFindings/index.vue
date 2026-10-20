<template>
  <section v-if="findings?.schema_version === 'inpatient_window_v1'" aria-label="原住院观测窗复核">
    <el-alert v-if="!scoped" type="error" :closable="false" title="观测窗与当前患者或原住院不符，不显示其他范围的观测数值。" />
    <template v-else>
      <h4>原住院观测窗</h4>
      <p>观察区间 {{ findings.start_at }} 至 {{ findings.end_at }}；系统可用截止 {{ findings.as_of }}。点测量包含起止两端，尿量按原始半开区间记录。</p>
      <p>当前快照的回溯观测资料，非历史数据库回放。离散测量不证明连续监护或采样完整；未提供模型输入适用性验证。</p>
      <el-button link @click="$emit('inspect', findings.source_id)">核对原冻结观测窗依据</el-button>
      <p v-for="item in findings.limitations || []" :key="item">{{ item }}</p>
      <p>检验尚需明确原住院关联和审核指标映射；此处不会从旧报告或问题正文补充肌酐、感染证据或基线。</p>
      <el-table :data="pointValues" max-height="340" aria-label="原点测量数值与缺项" empty-text="窗口内没有记录点测量">
        <el-table-column prop="observed_at" label="原观察时刻" min-width="205" />
        <el-table-column prop="recorded_at" label="系统登记时刻" min-width="205" />
        <el-table-column prop="label" label="指标" min-width="100" />
        <el-table-column prop="display" label="原值或缺失原因" min-width="150" />
        <el-table-column prop="unit" label="原单位" width="90" />
        <el-table-column prop="status_label" label="来源状态" width="100" />
        <el-table-column label="原始依据" width="90"><template #default="{ row }"><el-button link @click="$emit('inspect', row.source_id)">核对原行</el-button></template></el-table-column>
      </el-table>
      <el-table :data="findings.points || []" max-height="240" aria-label="氧疗与意识原始记录" empty-text="无氧疗或意识原记录">
        <el-table-column prop="observed_at" label="原观察时刻" min-width="205" />
        <el-table-column label="吸氧状态" width="110"><template #default="{ row }">{{ oxygen[row.payload.supplemental_oxygen] || '未知' }}</template></el-table-column>
        <el-table-column label="装置原文" min-width="120"><template #default="{ row }">{{ row.payload.oxygen_device ?? '未记录' }}</template></el-table-column>
        <el-table-column label="意识体系与原编码" min-width="180"><template #default="{ row }">{{ row.payload.consciousness ? `${row.payload.consciousness.system} · ${consciousness[row.payload.consciousness.code] || row.payload.consciousness.code}` : '未记录（不换算旧护理整数或GCS）' }}</template></el-table-column>
        <el-table-column label="状态" width="100"><template #default="{ row }">{{ row.status === 'active' ? '活动来源' : '已撤销，仅审计' }}</template></el-table-column>
      </el-table>
      <h4>分时尿量原记录</h4>
      <p>不自动累加、不分摊跨窗体积、不计算mL/kg/h或AKI分期。重叠、部分收集或非患者总量不能作为完整覆盖。</p>
      <el-table :data="findings.urine_intervals || []" max-height="280" aria-label="分时尿量原区间" empty-text="无分时尿量原记录；不是0mL">
        <el-table-column prop="start_at" label="收集开始" min-width="205" /><el-table-column prop="end_at" label="收集结束" min-width="205" />
        <el-table-column label="原mL量" min-width="140"><template #default="{ row }">{{ row.payload.volume_ml ?? `未知（${absent[row.payload.absent_reason] || row.payload.absent_reason || '未记录'}）` }}</template></el-table-column>
        <el-table-column label="收集完整性" width="115"><template #default="{ row }">{{ completeness[row.payload.collection_completeness] || '未知' }}</template></el-table-column>
        <el-table-column label="患者总量" width="110"><template #default="{ row }">{{ row.payload.patient_total === true ? '明确是' : row.payload.patient_total === false ? '明确不是' : '未知' }}</template></el-table-column>
        <el-table-column label="状态" width="100"><template #default="{ row }">{{ row.status === 'active' ? '活动来源' : '已撤销，仅审计' }}</template></el-table-column>
        <el-table-column label="依据" width="80"><template #default="{ row }"><el-button link @click="$emit('inspect', row.source_id)">核对原行</el-button></template></el-table-column>
      </el-table>
      <h4>缺项、冲突和观测间隔</h4>
      <p v-for="item in findings.quality?.missing_by_point || []" :key="item.source_id">{{ item.source_id }}：未记录 {{ (item.not_recorded || []).map(label).join('、') || '无' }}；明确未测 {{ (item.explicitly_unmeasured || []).map(label).join('、') || '无' }}。</p>
      <p v-for="(item, index) in findings.quality?.same_time_groups || []" :key="index">{{ item.observed_at }} · {{ label(item.measurement_code) }}：{{ item.state === 'duplicate_same_value' ? '同值重复，未择一合并' : '原值或缺失状态冲突，未任取最后一条' }}，共 {{ item.source_ids.length }} 个原来源。</p>
      <el-table :data="findings.quality?.measurement_gaps || []" max-height="270" aria-label="已观察时点与间隔">
        <el-table-column label="指标" min-width="120"><template #default="{ row }">{{ label(row.measurement_code) }}</template></el-table-column>
        <el-table-column prop="unique_numeric_observation_times" label="不同有值时点" width="125" />
        <el-table-column label="最大已观察间隔（秒）" min-width="180"><template #default="{ row }">{{ row.max_observed_gap_seconds ?? '不足两个有值时点' }}</template></el-table-column>
        <el-table-column label="起始缺口（秒）" min-width="130"><template #default="{ row }">{{ row.leading_gap_seconds ?? '无有值时点' }}</template></el-table-column>
        <el-table-column label="末尾缺口（秒）" min-width="130"><template #default="{ row }">{{ row.trailing_gap_seconds ?? '无有值时点' }}</template></el-table-column>
      </el-table>
      <p>这些间隔不构成采样计划或完整性证明。</p>
      <p v-for="(item, index) in findings.quality?.urine?.overlap_groups || []" :key="`overlap:${index}`">尿量相连重叠组：{{ item.source_ids.join('、') }}。不表示组内每对都重叠，组内记录未计为可靠覆盖。</p>
      <p v-for="item in findings.quality?.urine?.excluded_intervals || []" :key="item.source_id">{{ item.source_id }} 不计覆盖：{{ item.reasons.map(reason => urineReasons[reason] || reason).join('；') }}。</p>
      <p v-for="(item, index) in findings.quality?.urine?.uncovered_intervals || []" :key="`gap:${index}`">尿量未确认覆盖区间 {{ item.start_at }} 至 {{ item.end_at }}，不填0。</p>
    </template>
  </section>
</template>

<script setup>
import { computed } from "vue";
const props = defineProps({ findings: { type: Object, default: null }, expectedPatientId: { type: Number, default: null }, expectedAdmissionId: { type: String, default: "" } });
defineEmits(["inspect"]);
const labels = { heart_rate: "心率", pulse_rate: "脉率", respiratory_rate: "呼吸率", systolic_bp: "收缩压", diastolic_bp: "舒张压", temperature: "体温", spo2: "SpO₂", body_weight: "体重", oxygen_flow: "氧流量", fio2: "FiO₂百分比", supplemental_oxygen: "吸氧状态", consciousness: "意识" };
const label = code => labels[code] || code;
const absent = { unknown: "未知", not_performed: "未测", measurement_error: "测量失败" };
const completeness = { complete: "声明完整", partial: "部分收集", unknown: "未知" }, oxygen = { yes: "明确吸氧", no: "明确未吸氧", unknown: "未知" };
const consciousness = { alert: "清醒", voice: "对声音反应", pain: "对疼痛反应", unresponsive: "无反应", new_confusion: "新发意识混乱" };
const urineReasons = { revoked: "原记录已撤销", crosses_window_boundary_no_proration: "跨窗口边界，未按时长分摊", collection_not_complete: "未确认完整收集", not_confirmed_patient_total: "未确认患者总量", volume_not_measured: "体积未知", overlapping_intervals: "原区间存在重叠" };
const scoped = computed(() => (!props.expectedPatientId || props.findings?.patient_id === props.expectedPatientId) && (!props.expectedAdmissionId || props.findings?.admission_id === props.expectedAdmissionId));
const pointValues = computed(() => (props.findings?.points || []).flatMap(row => Object.entries(row.payload?.measurements || {}).map(([code, value]) => ({ ...row, label: label(code), display: value.value ?? `未知（${absent[value.absent_reason] || value.absent_reason || '未记录'}）`, unit: value.unit, status_label: row.status === "active" ? "活动来源" : "已撤销，仅审计" }))));
</script>
