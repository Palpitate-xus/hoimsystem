<template>
  <div class="observation-editor">
    <p>逐项填写原始结果。数值保留输入精度，采样时间按当前设备时区填写；未提供的信息保持为空。</p>
    <el-button size="small" @click="addItem">添加检验指标</el-button>
    <el-card v-for="(item, index) in modelValue" :key="item._key" class="observation-card" shadow="never">
      <template #header>
        <span>指标 {{ index + 1 }}</span>
        <el-button type="danger" link @click="removeItem(index)">删除指标</el-button>
      </template>
      <div class="observation-fields">
        <el-form-item label="项目编码"><el-input v-model="item.code" placeholder="检验项目编码" maxlength="80" /></el-form-item>
        <el-form-item label="编码体系"><el-input v-model="item.code_system" placeholder="如 local、LOINC" maxlength="80" /></el-form-item>
        <el-form-item label="项目名称"><el-input v-model="item.display" placeholder="检验项目名称" maxlength="120" /></el-form-item>
        <el-form-item label="采样时间"><el-input v-model="item.collected_at" type="datetime-local" aria-label="指标采样时间" /></el-form-item>
        <el-form-item label="结果类型"><el-select v-model="item.value_kind"><el-option value="numeric" label="数值" /><el-option value="text" label="定性" /></el-select></el-form-item>
        <el-form-item v-if="item.value_kind === 'numeric'" label="数值"><el-input v-model="item.value_num" placeholder="原始检验数值" inputmode="decimal" /></el-form-item>
        <el-form-item v-else label="定性结果"><el-input v-model="item.value_text" placeholder="原始定性结果" maxlength="500" /></el-form-item>
        <el-form-item label="原始单位"><el-input v-model="item.unit" placeholder="按报告原样填写" maxlength="40" /></el-form-item>
        <el-form-item label="异常标记"><el-select v-model="item.flag"><el-option v-for="(label, value) in flags" :key="value" :value="value" :label="label" /></el-select></el-form-item>
        <el-form-item label="参考下限"><el-input v-model="item.reference_low" placeholder="可留空" inputmode="decimal" /></el-form-item>
        <el-form-item label="参考上限"><el-input v-model="item.reference_high" placeholder="可留空" inputmode="decimal" /></el-form-item>
        <el-form-item label="参考说明"><el-input v-model="item.reference_text" placeholder="原报告参考说明" maxlength="200" /></el-form-item>
        <el-form-item label="检测方法"><el-input v-model="item.method" placeholder="用于判断连续结果可比性" maxlength="100" /></el-form-item>
        <el-form-item label="标本类型"><el-input v-model="item.specimen_type" placeholder="如血清，未知可留空" maxlength="80" /></el-form-item>
      </div>
    </el-card>
  </div>
</template>

<script setup>
const props = defineProps({ modelValue: { type: Array, default: () => [] } });
const emit = defineEmits(["update:modelValue"]);
const flags = { unknown: "未标注", normal: "报告标记正常", high: "偏高", low: "偏低", critical: "危急值" };
let itemCounter = 0;
const addItem = () => emit("update:modelValue", [...props.modelValue, { _key: ++itemCounter, code: "", code_system: "local", display: "", collected_at: "", value_kind: "numeric", value_num: "", value_text: "", unit: "", reference_low: "", reference_high: "", reference_text: "", method: "", specimen_type: "", flag: "unknown" }]);
const removeItem = (index) => emit("update:modelValue", props.modelValue.filter((_, i) => i !== index));
</script>

<style scoped>
.observation-editor { width: 100%; }
.observation-editor p { color: var(--el-text-color-secondary); font-size: 13px; line-height: 1.6; }
.observation-card { margin-top: 12px; }
.observation-card :deep(.el-card__header) { display: flex; justify-content: space-between; }
.observation-fields { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 0 14px; }
@media (max-width: 700px) { .observation-fields { grid-template-columns: 1fr; } }
</style>
