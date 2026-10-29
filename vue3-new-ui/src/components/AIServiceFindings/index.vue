<template>
  <section v-if="findings?.appointment_candidates" class="service-findings">
    <h4>当前排班与共享号源候选</h4>
    <p v-if="noticeText(findings.appointment_candidates.scope_note)">{{ noticeText(findings.appointment_candidates.scope_note) }}</p>
    <p>本次查询日期范围：{{ findings.appointment_candidates.window_start }} 至 {{ findings.appointment_candidates.window_end }}</p>
    <el-table :data="findings.appointment_candidates.candidates" max-height="360" empty-text="本次筛选暂无可展示号源候选">
      <el-table-column prop="department_name" label="科室" min-width="110" /><el-table-column prop="doctor_name" label="医生" min-width="100" />
      <el-table-column prop="appointment_date" label="日期" width="120" /><el-table-column prop="recorded_period" label="原时段编码" width="100" />
      <el-table-column prop="current_shared_stock" label="当前共享余量" width="110" />
      <el-table-column label="依据" width="120"><template #default="{ row }"><el-button link @click="$emit('inspect', row.source_id)">查看号源依据</el-button></template></el-table-column>
    </el-table>
    <p v-for="(item, index) in noticeList(findings.appointment_candidates.missing_data)" :key="index">{{ item }}</p>
    <p v-if="findings.appointment_candidates.truncated">候选已限制为有限范围，请指定科室、医生或日期缩小查询。</p>
  </section>
  <section v-if="findings?.hospital_navigation" class="service-findings">
    <h4>院内已配置路线与办事资料</h4><p v-if="noticeText(findings.hospital_navigation.scope_note)">{{ noticeText(findings.hospital_navigation.scope_note) }}</p>
    <template v-if="findings.hospital_navigation.route">
      <p>{{ findings.hospital_navigation.route.nodes.map(node => node.name).join(' → ') }}</p>
      <ol><li v-for="(step, index) in findings.hospital_navigation.route.steps" :key="index">{{ step.instruction }}（原路线距离：{{ step.distance }}）</li></ol>
      <el-button link @click="$emit('inspect', findings.hospital_navigation.route.source_id)">查看路线依据</el-button>
    </template>
    <p v-for="(item, index) in noticeList(findings.hospital_navigation.missing_data)" :key="index">{{ item }}</p>
    <div v-for="item in findings.hospital_navigation.hospital_faq" :key="item.source_id">
      <strong>{{ item.question }}</strong><p class="plain-text">{{ item.answer }}</p><el-button link @click="$emit('inspect', item.source_id)">查看办事问答依据</el-button>
    </div>
  </section>
</template>

<script setup>
import { noticeText, noticeList } from "@/utils/noticeText.cjs";
defineProps({ findings: { type: Object, default: null } });
defineEmits(["inspect"]);
</script>

<style scoped>
.service-findings { margin: 16px 0; line-height: 1.7; }
.plain-text { white-space: pre-wrap; overflow-wrap: anywhere; }
</style>
