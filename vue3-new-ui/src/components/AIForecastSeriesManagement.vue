<template>
  <section v-if="allowed" aria-label="挂号预测来源管理">
    <p>每日挂号记录数包含全部挂号状态，单位为条/日。请核对覆盖日期和时区；修改资料时需新建来源。</p>
    <div class="page-toolbar"><el-button type="primary" @click="openCreate">新建覆盖声明</el-button><el-button @click="load">刷新来源</el-button><el-select v-model="status" aria-label="预测来源状态" clearable placeholder="全部状态" @change="load"><el-option label="活动" value="active" /><el-option label="已撤销" value="revoked" /></el-select></div>
    <p v-if="directory.truncated">显示前100个来源，可按状态筛选。</p>
    <el-table :data="directory.items || []" v-loading="loading" empty-text="尚无冻结预测来源">
      <el-table-column prop="name" label="来源名称" min-width="180" /><el-table-column label="原范围" min-width="150"><template #default="{ row }">{{ row.scope === 'hospital' ? '全院' : `科室 #${row.department_id}` }} · {{ row.day_count }} 日</template></el-table-column>
      <el-table-column label="历史与时区" min-width="250"><template #default="{ row }">{{ row.date_from }} 至 {{ row.date_to }}<div>{{ row.timezone }} · 原数据库无时区钟点</div></template></el-table-column>
      <el-table-column label="状态" min-width="170"><template #default="{ row }">{{ row.status === 'active' ? '活动' : '已撤销' }} · v{{ row.revision }}<div>目录尚未核对原资料一致性</div></template></el-table-column>
      <el-table-column label="核对" width="120"><template #default="{ row }"><el-button size="small" @click="inspect(row)">查看冻结来源</el-button></template></el-table-column>
    </el-table>
    <el-dialog v-model="createDialog" title="确认挂号历史覆盖并冻结来源" width="min(900px,95vw)" @closed="clearCreate">
      <el-form label-width="130px" :disabled="creating" @submit.prevent>
        <el-form-item label="来源名称"><el-input v-model="form.name" aria-label="预测来源名称" maxlength="120" /></el-form-item>
        <el-form-item label="统计范围"><el-select v-model="form.scope" aria-label="来源统计范围"><el-option label="全院" value="hospital" /><el-option label="单个科室" value="department" /></el-select></el-form-item>
        <el-form-item v-if="form.scope === 'department'" label="科室ID"><el-input-number v-model="form.department_id" aria-label="来源科室ID" :controls="false" :min="1" :precision="0" /></el-form-item>
        <el-form-item label="完整历史窗口"><el-date-picker v-model="form.range" aria-label="来源历史窗口" type="daterange" value-format="YYYY-MM-DD" start-placeholder="历史开始日期" end-placeholder="历史末日" /></el-form-item>
        <el-form-item label="原钟点时区解释"><el-input v-model="form.timezone" aria-label="原钟点时区解释" placeholder="明确填写IANA时区，如Asia/Shanghai；不转换既有钟点" /></el-form-item>
        <el-form-item><el-button :loading="previewing" @click="previewSource">预览原始日计数</el-button></el-form-item>
      </el-form>
      <template v-if="preview">
        <p>目标：每日挂号原记录数 · 112至366日连续窗口；原钟点时区解释 {{ preview.timezone }}。无原时间记录 {{ preview.unassigned_time_records }} 条，无法分日，已排除。</p>
        <p v-for="note in preview.quality?.notes || []" :key="note">{{ note }}</p>
        <p>尚未确认覆盖：即使观测到0条，可训练值仍为未知。每个日已结束：{{ preview.quality?.all_days_ended ? '是' : '否，不能冻结' }}。</p>
        <el-table :data="preview.observations" max-height="260" aria-label="未确认挂号历史"><el-table-column prop="date" label="原日期" /><el-table-column prop="observed_count" label="观测原记录数" /><el-table-column label="可训练值"><template #default>未知（尚未确认覆盖）</template></el-table-column></el-table>
        <div class="checks"><el-checkbox :disabled="creating" v-model="checks.coverage_confirmed">我确认整个历史窗口的挂号原记录完整覆盖</el-checkbox><el-checkbox :disabled="creating" v-model="checks.days_ended_confirmed">我确认每个日期在声明时区均已结束</el-checkbox><el-checkbox :disabled="creating" v-model="checks.timezone_confirmed">我确认原无时区钟点的时区解释</el-checkbox></div>
        <el-input :disabled="creating" v-model="form.coverage_note" aria-label="覆盖确认依据" type="textarea" :rows="4" maxlength="2000" show-word-limit placeholder="至少20字：说明完整覆盖、闭合日期和原钟点时区的核对依据" />
      </template>
      <template #footer><el-button @click="createDialog = false">取消</el-button><el-button type="primary" :disabled="!canCreate" :loading="creating" @click="confirmSource">确认声明并冻结来源</el-button></template>
    </el-dialog>
    <el-dialog v-model="detailDialog" title="冻结挂号预测来源" width="min(900px,95vw)" @closed="clearDetail">
      <div v-loading="inspecting">
        <template v-if="detail">
          <h4>{{ detail.name }}</h4><p>状态 {{ detail.status }} · v{{ detail.revision }}；{{ detail.current ? '本次原资料一致性核对通过' : detail.current_error || '原资料一致性待核对' }}</p>
          <p>{{ detail.coverage_note }}</p><p v-for="note in detail.quality?.notes || []" :key="note">{{ note }}</p>
          <template v-if="detail.source"><p>{{ detail.source.date_from }} 至 {{ detail.source.date_to }} · {{ detail.source.timezone }} · 覆盖声明 {{ detail.source.coverage_attested_at }}。</p><p class="hash">来源 {{ detail.source.source_id }}<br />内容摘要 {{ detail.source.content_hash }}<br />原登记摘要 {{ detail.source.registration_digest }}<br />声明依据摘要 {{ detail.source.coverage_note_hash }}</p><el-table :data="detail.source.observations" max-height="300" aria-label="已冻结挂号历史"><el-table-column prop="date" label="日期" /><el-table-column label="冻结记录数"><template #default="{ row }">{{ row.value ?? '未知' }}</template></el-table-column></el-table></template>
          <template v-if="detail.status === 'active'"><el-input v-model="revokeReason" aria-label="预测来源撤销依据" maxlength="1000" placeholder="说明撤销依据，撤销后不能恢复" /><el-button type="danger" :disabled="!revokeReason.trim()" :loading="revoking" @click="revoke">撤销此来源</el-button></template>
          <p v-else>已撤销 {{ detail.revoked_at }}：{{ detail.revoke_reason }}。此来源不能恢复。</p>
        </template>
      </div>
      <template #footer><el-button @click="detailDialog = false">关闭</el-button></template>
    </el-dialog>
  </section>
</template>
<script setup>
import { computed, onActivated, onBeforeUnmount, onDeactivated, onMounted, ref, watch } from "vue";
import { useStore } from "vuex";
import { ElMessage } from "element-plus";
import { createAIForecastSeries, getAIAdminForecastSeries, getAIAdminForecastSeriesDetail, previewAIForecastSeries, revokeAIForecastSeries } from "@/api/ai";
const store = useStore();
const allowed = computed(() => !!store.state.user.accessToken && store.getters["user/permissions"].includes("super_admin"));
const blank = () => ({ name: "", scope: "hospital", department_id: null, range: [], timezone: "", coverage_note: "" });
const noChecks = () => ({ coverage_confirmed: false, days_ended_confirmed: false, timezone_confirmed: false });
const directory = ref({}), status = ref(""), loading = ref(false), createDialog = ref(false), detailDialog = ref(false), form = ref(blank()), checks = ref(noChecks()), preview = ref(null), detail = ref(null), revokeReason = ref("");
const previewing = ref(false), creating = ref(false), inspecting = ref(false), revoking = ref(false);
let listEpoch = 0, createEpoch = 0, detailEpoch = 0;
const selection = computed(() => JSON.stringify([form.value.scope, form.value.department_id, form.value.range, form.value.timezone]));
watch(selection, () => { createEpoch++; preview.value = null; checks.value = noChecks(); previewing.value = false; });
watch(() => form.value.scope, scope => { if (scope === "hospital") form.value.department_id = null; });
const canCreate = computed(() => allowed.value && !previewing.value && !!preview.value?.expected_digest && preview.value.quality?.all_days_ended === true && form.value.name.trim().length > 0 && form.value.coverage_note.trim().length >= 20 && Object.values(checks.value).every(value => value === true));
function clearCreate() { createEpoch++; preview.value = null; form.value = blank(); checks.value = noChecks(); previewing.value = false; creating.value = false; }
function clearDetail() { detailEpoch++; detail.value = null; revokeReason.value = ""; inspecting.value = false; revoking.value = false; }
function clearAll() { listEpoch++; createDialog.value = false; detailDialog.value = false; clearCreate(); clearDetail(); directory.value = {}; loading.value = false; }
watch([() => JSON.stringify(store.getters["user/permissions"]), () => store.state.user.accessToken], clearAll);
onDeactivated(clearAll); onBeforeUnmount(clearAll);
async function load() { if (!allowed.value) return; const epoch = ++listEpoch; loading.value = true; try { const res = await getAIAdminForecastSeries(status.value ? { status: status.value } : {}); if (epoch === listEpoch && allowed.value) directory.value = res.data ?? {}; } catch { if (epoch === listEpoch && allowed.value) ElMessage.error("预测来源加载失败"); } finally { if (epoch === listEpoch) loading.value = false; } }
function openCreate() { if (!allowed.value) return; clearCreate(); createDialog.value = true; }
function query() { return { scope: form.value.scope, department_id: form.value.scope === "department" ? form.value.department_id : null, date_from: form.value.range?.[0], date_to: form.value.range?.[1], timezone: form.value.timezone.trim() }; }
async function previewSource() {
  if (!allowed.value || previewing.value) return;
  if (form.value.range?.length !== 2 || !form.value.timezone.trim() || (form.value.scope === "department" && (!Number.isSafeInteger(form.value.department_id) || form.value.department_id < 1))) { ElMessage.warning("请明确选择完整日期窗口、原钟点时区和统计范围"); return; }
  const epoch = ++createEpoch; preview.value = null; checks.value = noChecks(); previewing.value = true;
  try { const res = await previewAIForecastSeries(query()); if (epoch === createEpoch && allowed.value && createDialog.value) preview.value = res.data; } catch { if (epoch === createEpoch && allowed.value) ElMessage.error("来源预览失败，请核对日期、时区与原资料"); } finally { if (epoch === createEpoch) previewing.value = false; }
}
async function confirmSource() {
  if (!canCreate.value || creating.value) return; const epoch = createEpoch, priorDetailEpoch = detailEpoch, payload = { ...query(), name: form.value.name.trim(), coverage_note: form.value.coverage_note.trim(), expected_digest: preview.value.expected_digest, ...checks.value }; creating.value = true;
  try { const res = await createAIForecastSeries(payload); if (epoch !== createEpoch || !allowed.value || !createDialog.value) return; createDialog.value = false; ElMessage.success("来源已冻结，声明未改变功能验证状态"); if (priorDetailEpoch === detailEpoch) { clearDetail(); detail.value = res.data; detailDialog.value = true; } await load(); } catch { if (epoch === createEpoch && allowed.value) { preview.value = null; checks.value = noChecks(); ElMessage.error("冻结失败，请重新预览后核对"); } } finally { if (epoch === createEpoch) creating.value = false; }
}
async function inspect(row) { if (!allowed.value) return; clearDetail(); const epoch = detailEpoch; detailDialog.value = true; inspecting.value = true; try { const res = await getAIAdminForecastSeriesDetail(row.series_id); if (epoch === detailEpoch && allowed.value && detailDialog.value && res.data?.series_id === row.series_id) detail.value = res.data; } catch { if (epoch === detailEpoch && allowed.value) ElMessage.error("冻结来源核对失败"); } finally { if (epoch === detailEpoch) inspecting.value = false; } }
async function revoke() { if (!allowed.value || detail.value?.status !== "active" || !revokeReason.value.trim() || revoking.value) return; const epoch = detailEpoch, id = detail.value.series_id, revision = detail.value.revision; revoking.value = true; try { const res = await revokeAIForecastSeries(id, { expected_revision: revision, reason: revokeReason.value.trim() }); if (epoch !== detailEpoch || !allowed.value || !detailDialog.value || res.data?.series_id !== id) return; detail.value = res.data; revokeReason.value = ""; await load(); } catch { if (epoch === detailEpoch && allowed.value) ElMessage.error("撤销失败，请刷新来源状态"); } finally { if (epoch === detailEpoch) revoking.value = false; } }
onMounted(load); onActivated(() => { if (!directory.value.items && !loading.value) load(); });
</script>
<style scoped>.checks { display: flex; flex-direction: column; align-items: flex-start; margin: 14px 0; }.hash { overflow-wrap: anywhere; line-height: 1.7; }p { line-height: 1.7; }</style>
