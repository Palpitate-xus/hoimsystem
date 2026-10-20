<template>
  <el-table :data="items" border empty-text="原报告未提供结构化指标">
    <el-table-column label="项目" min-width="150"><template #default="{ row }">{{ row.display }}<br /><small>{{ row.code_system }}:{{ row.code }}</small></template></el-table-column>
    <el-table-column label="结果" min-width="100"><template #default="{ row }">{{ row.value_num ?? row.value_text }} {{ row.unit || '' }}</template></el-table-column>
    <el-table-column label="原报告参考范围" min-width="130"><template #default="{ row }">{{ reference(row) }}</template></el-table-column>
    <el-table-column label="标记" width="120"><template #default="{ row }"><el-tag :type="row.flag === 'critical' ? 'danger' : ['high', 'low'].includes(row.flag) ? 'warning' : 'info'">{{ flags[row.flag] || '未标注' }}</el-tag></template></el-table-column>
    <el-table-column label="采样时间" min-width="180"><template #default="{ row }">{{ row.collected_at ? new Date(row.collected_at).toLocaleString() : '未记录' }}</template></el-table-column>
    <el-table-column label="方法 / 标本" min-width="140"><template #default="{ row }">{{ row.method || '方法未记录' }} / {{ row.specimen_type || '标本未记录' }}</template></el-table-column>
  </el-table>
</template>

<script setup>
defineProps({ items: { type: Array, default: () => [] } });
const flags = { unknown: "未标注", normal: "报告标记正常", high: "偏高", low: "偏低", critical: "危急值" };
const reference = (row) => row.reference_text || (row.reference_low != null || row.reference_high != null ? `${row.reference_low ?? '未记录'} ～ ${row.reference_high ?? '未记录'} ${row.unit || ''}` : "未提供");
</script>
