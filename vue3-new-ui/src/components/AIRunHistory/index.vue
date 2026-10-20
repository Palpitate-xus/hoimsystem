<template>
  <div>
    <el-form inline @submit.prevent="load(true)">
      <el-form-item label="能力"><el-select v-model="filters.feature_key" clearable filterable placeholder="全部能力" style="width: 210px"><el-option v-for="item in features" :key="item.key" :value="item.key" :label="item.name" /></el-select></el-form-item>
      <el-form-item label="状态"><el-select v-model="filters.status" clearable placeholder="全部状态" style="width: 130px"><el-option v-for="(label, value) in states" :key="value" :value="value" :label="label" /></el-select></el-form-item>
      <el-form-item label="反馈"><el-select v-model="filters.outcome" clearable placeholder="全部反馈" style="width: 150px"><el-option v-for="(label, value) in outcomes" :key="value" :value="value" :label="'含' + label + '反馈'" /></el-select></el-form-item>
      <el-form-item label="发起用户ID"><el-input-number v-model="filters.requested_by" :min="1" :controls="false" style="width: 130px" /></el-form-item>
      <el-form-item label="患者ID"><el-input-number v-model="filters.patient_id" :min="1" :controls="false" style="width: 130px" /></el-form-item>
      <el-form-item><el-button type="primary" native-type="submit">查询任务</el-button><el-button @click="load()">刷新任务</el-button></el-form-item>
    </el-form>
    <el-table :data="rows" v-loading="loading" empty-text="暂无匹配任务">
      <el-table-column prop="feature_name" label="能力" min-width="160" />
      <el-table-column prop="requested_by" label="用户ID" width="85" /><el-table-column prop="patient_id" label="患者ID" width="85" />
      <el-table-column label="状态" width="100"><template #default="{ row }">{{ states[row.status] }}</template></el-table-column>
      <el-table-column label="已报告Token" width="130"><template #default="{ row }">{{ row.input_tokens || row.output_tokens ? (row.input_tokens || 0) + ' / ' + (row.output_tokens || 0) : '未报告' }}</template></el-table-column>
      <el-table-column prop="feedback_count" label="反馈数" width="85" /><el-table-column prop="create_time" label="发起时间" width="180" />
      <el-table-column label="操作" fixed="right" width="175"><template #default="{ row }"><el-button size="small" @click="inspect(row)">执行溯源</el-button><el-button v-if="['queued', 'running'].includes(row.status)" size="small" type="warning" @click="cancel(row)">取消接收</el-button></template></el-table-column>
    </el-table>
    <el-pagination v-model:current-page="page" :page-size="30" :total="total" layout="total, prev, pager, next" class="pagination-wrapper" @current-change="load()" />

    <el-dialog v-model="visible" title="AI 任务执行溯源" width="min(1150px, 96vw)" append-to-body destroy-on-close>
      <div v-loading="detailLoading" class="trace-body">
        <template v-if="detail">
          <el-descriptions :column="2" border>
            <el-descriptions-item label="能力">{{ detail.feature_name }}</el-descriptions-item><el-descriptions-item label="任务状态">{{ states[detail.status] }}{{ detail.preview ? ' · 评估预览' : '' }}</el-descriptions-item>
            <el-descriptions-item label="发起用户ID">{{ detail.requested_by }}</el-descriptions-item><el-descriptions-item label="患者ID">{{ detail.patient_id || '未关联患者' }}</el-descriptions-item>
            <el-descriptions-item label="发起时间">{{ detail.create_time }}</el-descriptions-item><el-descriptions-item label="Prompt / 模型配置版本">v{{ detail.prompt_version }} / v{{ detail.provider_revision }}</el-descriptions-item>
          </el-descriptions>
          <el-alert v-if="detail.error_message" type="error" :closable="false" :title="detail.error_message" class="spaced" />
          <el-alert v-if="!detail.snapshot_complete" type="info" :closable="false" title="旧任务按实际留存内容展示，部分执行快照字段未保存。" class="spaced" />
          <el-tabs v-model="detailTab" class="spaced">
            <el-tab-pane label="结果与引用" name="result">
              <p class="plain-text">{{ detail.result?.summary || '此任务没有已接收的结果' }}</p>
              <el-alert v-for="(item, i) in detail.result?.warnings || []" :key="'warning-' + i" type="warning" :closable="false" :title="item" class="spaced" />
              <p v-for="(item, i) in detail.result?.missing_data || []" :key="'missing-' + i">待补资料：{{ item }}</p>
              <section v-for="(item, i) in detail.result?.sections || []" :key="i"><h4>{{ item.title }}</h4><p class="plain-text">{{ item.content }}</p><el-button v-for="id in item.source_ids" :key="id" link @click="showEvidence(id)">查看依据 {{ id }}</el-button></section>
            </el-tab-pane>
            <el-tab-pane label="人工反馈" name="feedback">
              <el-table :data="detail.feedback || []" empty-text="尚无人工反馈"><el-table-column prop="reviewer_id" label="复核用户ID" width="110" /><el-table-column label="反馈" width="110"><template #default="{ row }">{{ outcomes[row.outcome] }}</template></el-table-column><el-table-column prop="comment" label="说明" min-width="240" /><el-table-column prop="create_time" label="时间" width="180" /></el-table>
              <p v-if="detail.feedback_truncated">仅展示最近 100 条反馈。</p>
            </el-tab-pane>
            <el-tab-pane label="调用时 Prompt" name="prompt"><h4>固定系统 Prompt</h4><pre class="plain-text">{{ detail.frozen_request?.system_prompt || '未保存原文' }}</pre><h4>任务 Prompt</h4><pre class="plain-text">{{ detail.frozen_request?.task_prompt }}</pre></el-tab-pane>
            <el-tab-pane label="模型与验证快照" name="model"><el-descriptions :column="1" border><el-descriptions-item label="请求模型">{{ detail.frozen_request?.provider_snapshot?.model || '未保存' }}</el-descriptions-item><el-descriptions-item label="服务地址">{{ detail.frozen_request?.provider_snapshot?.api_base || '未保存' }}</el-descriptions-item><el-descriptions-item label="输出上限">{{ detail.frozen_request?.provider_snapshot?.effective_output_limit ?? '未保存' }}</el-descriptions-item><el-descriptions-item label="当时验证记录">{{ detail.frozen_request?.feature_validation?.note || '未保存' }}</el-descriptions-item><el-descriptions-item label="适配器验证记录">{{ detail.frozen_request?.provider_snapshot?.validation_report || '未登记' }}</el-descriptions-item></el-descriptions></el-tab-pane>
            <el-tab-pane label="调用时资料与工具" name="input"><pre class="plain-text">{{ JSON.stringify(detail.frozen_request?.payload || {}, null, 2) }}</pre></el-tab-pane>
          </el-tabs>
        </template>
      </div>
    </el-dialog>
    <el-dialog v-model="evidenceVisible" title="任务原始依据" width="min(800px, 96vw)" append-to-body><h4>{{ evidence?.title }}</h4><p>{{ evidence?.observed_at }}</p><pre class="plain-text">{{ evidence?.content }}</pre></el-dialog>
  </div>
</template>

<script setup>
import { onActivated, onBeforeUnmount, onDeactivated, onMounted, ref, watch } from "vue";
import { ElMessage, ElMessageBox } from "element-plus";
import { cancelAIRun, getAIAdminRuns, getAIAdminRunTrace } from "@/api/ai";
const props = defineProps({ features: { type: Array, default: () => [] }, active: { type: Boolean, default: true } });
const states = { queued: "排队中", running: "生成中", succeeded: "待业务复核", failed: "失败", cancelled: "已取消" };
const outcomes = { accepted: "采纳", rejected: "驳回", modified: "修改后采纳" };
const rows = ref([]), loading = ref(false), page = ref(1), total = ref(0), filters = ref({ feature_key: "", status: "", outcome: "", requested_by: undefined, patient_id: undefined });
const visible = ref(false), detail = ref(null), detailLoading = ref(false), detailTab = ref("result"), evidenceVisible = ref(false), evidence = ref(null);
let listVersion = 0, detailVersion = 0;
let wasDeactivated = false;
async function load(reset = false) {
  if (reset) page.value = 1;
  const version = ++listVersion; loading.value = true;
  const params = Object.fromEntries(Object.entries(filters.value).filter(([, value]) => value !== "" && value != null));
  try { const response = await getAIAdminRuns({ ...params, page: page.value, page_size: 30 }); if (version === listVersion) { rows.value = response.data || []; total.value = response.total || 0; } }
  finally { if (version === listVersion) loading.value = false; }
}
async function inspect(row) {
  const version = ++detailVersion; visible.value = true; detail.value = null; detailTab.value = "result"; detailLoading.value = true;
  try { const response = await getAIAdminRunTrace(row.run_id); if (version === detailVersion) detail.value = response.data; }
  finally { if (version === detailVersion) detailLoading.value = false; }
}
function showEvidence(id) { evidence.value = detail.value?.evidence?.find(item => item.source_id === id); evidenceVisible.value = !!evidence.value; }
async function cancel(row) {
  try {
    await ElMessageBox.confirm("取消后将停止接收结果，已发出的模型请求仍可能计费。", "取消任务结果接收", { confirmButtonText: "取消接收", cancelButtonText: "保留任务", type: "warning" });
    await cancelAIRun(row.run_id); ElMessage.success("任务结果已取消接收"); await load();
  } catch (error) { if (error !== "cancel" && error !== "close") throw error; }
}
watch(() => props.active, value => { if (value) load(); else { visible.value = false; evidenceVisible.value = false; ++detailVersion; } });
onMounted(() => { if (props.active) load(); });
onDeactivated(() => { wasDeactivated = true; visible.value = false; evidenceVisible.value = false; detail.value = null; ++detailVersion; });
onActivated(() => { if (wasDeactivated) { wasDeactivated = false; if (props.active) load(); } });
onBeforeUnmount(() => { ++listVersion; ++detailVersion; });
</script>

<style scoped>
.spaced { margin-top: 14px; }
.plain-text { white-space: pre-wrap; overflow-wrap: anywhere; line-height: 1.7; max-height: 55vh; overflow: auto; }
.trace-body { min-height: 100px; }
</style>
