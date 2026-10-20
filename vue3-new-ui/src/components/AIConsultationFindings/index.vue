<template>
  <section v-if="findings && (findings.referrals?.length || findings.mdt_cases?.length)" class="consultation-findings">
    <h4>转诊与MDT原记录</h4><p>{{ findings.scope_note }}</p>
    <el-collapse>
      <el-collapse-item v-for="row in findings.referrals || []" :key="row.source_id" :name="row.source_id" :title="`转诊 #${row.referral_id} · ${row.recorded_status_meaning}`">
        <el-descriptions :column="1" border>
          <el-descriptions-item label="原转出科室">{{ departmentLabel(row.from_department) }}</el-descriptions-item>
          <el-descriptions-item label="原转入科室">{{ departmentLabel(row.to_department) }}</el-descriptions-item>
          <el-descriptions-item label="原类型编码">{{ row.recorded_type || '未知' }}</el-descriptions-item>
          <el-descriptions-item label="原转诊原因"><p class="recorded-text">{{ row.recorded_reason || '未记录' }}</p></el-descriptions-item>
          <el-descriptions-item label="原申请时间">{{ row.created_at || '未记录' }}</el-descriptions-item>
          <el-descriptions-item label="原审批时间">{{ row.reviewed_at || '未记录' }}</el-descriptions-item>
          <el-descriptions-item label="原审批意见"><p class="recorded-text">{{ row.recorded_review_note || '未记录' }}</p></el-descriptions-item>
        </el-descriptions>
        <p>{{ row.definition_note }}</p><el-button link @click="$emit('inspect', row.source_id)">查看转诊原始依据</el-button>
      </el-collapse-item>
      <el-collapse-item v-for="row in findings.mdt_cases || []" :key="row.source_id" :name="row.source_id" :title="`MDT #${row.mdt_id} · ${row.recorded_status_meaning}`">
        <p v-if="row.unparsed_department_tokens || row.missing_department_count" class="data-gap">科室引用有无法解析或目录缺失项，参与范围不完整。</p>
        <el-descriptions :column="1" border>
          <el-descriptions-item label="原初步诊断"><p class="recorded-text">{{ row.recorded_diagnosis || '未记录' }}</p></el-descriptions-item>
          <el-descriptions-item label="原参与科室">{{ row.participating_departments?.map(departmentLabel).join('、') || '未记录' }}</el-descriptions-item>
          <el-descriptions-item label="原申请时间">{{ row.created_at || '未记录' }}</el-descriptions-item>
          <el-descriptions-item label="原审批时间">{{ row.reviewed_at || '未记录' }}</el-descriptions-item>
          <el-descriptions-item label="原审批意见"><p class="recorded-text">{{ row.recorded_review_note || '未记录' }}</p></el-descriptions-item>
          <el-descriptions-item label="原会诊结果文本"><p class="recorded-text">{{ row.recorded_result || '未记录' }}</p></el-descriptions-item>
          <el-descriptions-item label="结果所在病例状态">{{ row.result_on_completed_case ? '有完成标记且结果非空，仍需核实签署' : '未取得完成标记下的非空结果，不作最终意见' }}</el-descriptions-item>
        </el-descriptions>
        <p>{{ row.definition_note }}</p><el-button link @click="$emit('inspect', row.source_id)">查看MDT原始依据</el-button>
      </el-collapse-item>
    </el-collapse>
  </section>
</template>
<script setup>
defineProps({ findings: { type: Object, default: null } });
defineEmits(["inspect"]);
const departmentLabel = item => item?.exists_in_current_directory ? item.name : item?.department_id ? `未核实（原标识 ${item.department_id}）` : "未注明";
</script>
<style scoped>
.consultation-findings { line-height: 1.7; margin: 16px 0; }
.recorded-text { white-space: pre-wrap; overflow-wrap: anywhere; margin: 0; }
.data-gap { color: #9a6700; }
</style>
