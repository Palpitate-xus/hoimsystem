<template>
  <section class="observation-panel" aria-label="原住院生理观测来源">
    <p v-if="!allowed">请以有权限的工作人员身份明确选择原住院。原记录作者身份不替代当前照护权限。</p>
    <template v-else>
      <p>患者 #{{ patientId }} · 原住院 {{ admissionId }}。只登记实际观测；空白不表示正常，0须明确填写。时间须含时区，录入时间与观察时间分别保留。</p>
      <p>这些资料是离散观测，采样计划未知，不代表连续监护齐全；登记或冻结不会调用模型、计算量表或改变功能验证状态。</p>
      <el-tabs v-model="tab" aria-label="住院观测资料类型">
        <el-tab-pane label="点测量" name="points">
          <el-form label-position="top" :disabled="saving.points" @submit.prevent>
            <el-form-item label="实际观察时点"><el-input v-model="point.observed_at" aria-label="实际观察时点" placeholder="例如 2026-10-20T08:30:00.123456+08:00" /></el-form-item>
            <div class="measurement-grid">
              <fieldset v-for="field in metricFields" :key="field.key"><legend>{{ field.label }}（{{ field.unit }}）</legend>
                <el-input v-model="point.measurements[field.key].value" :aria-label="`${field.label}原始数值`" inputmode="decimal" placeholder="未填写" />
                <el-select v-model="point.measurements[field.key].absent_reason" :aria-label="`${field.label}缺失原因`" clearable placeholder="缺失时明确原因"><el-option v-for="(label, key) in absentReasons" :key="key" :label="label" :value="key" /></el-select>
              </fieldset>
            </div>
            <p>单位固定显示；FiO₂按百分数录入，不将小数比例自动乘100。心率与脉搏分开记录。未填写的指标可省略，填数值时不能同时选择缺失原因。只记录未测或失败原因时，观察时点是本次测量尝试或评估时点，不表示取得实际测值或结果正常。</p>
            <div class="measurement-grid">
              <el-form-item label="观察时是否正在吸氧"><el-select v-model="point.supplemental_oxygen" aria-label="观察时吸氧情况" placeholder="必须明确选择"><el-option v-for="(label, key) in oxygenLabels" :key="key" :label="label" :value="key" /></el-select></el-form-item>
              <el-form-item label="原氧疗装置（可选）"><el-input v-model="point.oxygen_device" aria-label="原氧疗装置" maxlength="120" /></el-form-item>
              <el-form-item label="意识记录体系（可选）"><el-select v-model="point.consciousness_system" aria-label="意识记录体系" clearable placeholder="未观察" @change="point.consciousness_code = ''"><el-option label="AVPU" value="AVPU" /><el-option label="ACVPU" value="ACVPU" /></el-select></el-form-item>
              <el-form-item label="实际意识观察"><el-select v-model="point.consciousness_code" aria-label="实际意识观察" :disabled="!point.consciousness_system" clearable placeholder="未观察"><el-option v-for="entry in consciousnessOptions" :key="entry.code" :label="entry.label" :value="entry.code" /></el-select></el-form-item>
            </div>
            <el-form-item label="点测来源备注"><el-input v-model="point.note" aria-label="点测来源备注" type="textarea" maxlength="1000" /></el-form-item>
            <el-button type="primary" :loading="saving.points" @click="savePoint">登记点测量</el-button>
          </el-form>
          <source-list kind="points" />
        </el-tab-pane>
        <el-tab-pane label="尿量" name="urine">
          <el-form label-position="top" :disabled="saving.urine" @submit.prevent>
            <div class="measurement-grid"><el-form-item label="实际收集开始"><el-input v-model="urine.start_at" aria-label="尿量收集开始" placeholder="明确填写带时区ISO" /></el-form-item><el-form-item label="实际收集结束"><el-input v-model="urine.end_at" aria-label="尿量收集结束" placeholder="明确填写带时区ISO" /></el-form-item></div>
            <div class="measurement-grid">
              <el-form-item label="该区间原尿量（mL）"><el-input v-model="urine.volume_ml" aria-label="区间尿量mL" inputmode="decimal" placeholder="未知留空，不填0替代" /></el-form-item>
              <el-form-item label="缺失原因"><el-select v-model="urine.absent_reason" aria-label="尿量缺失原因" clearable placeholder="未知时选择原因"><el-option v-for="(label, key) in absentReasons" :key="key" :label="label" :value="key" /></el-select></el-form-item>
              <el-form-item label="收集完整性"><el-select v-model="urine.collection_completeness" aria-label="尿量收集完整性" placeholder="必须明确选择"><el-option label="完整收集" value="complete" /><el-option label="部分收集" value="partial" /><el-option label="完整性未知" value="unknown" /></el-select></el-form-item>
              <el-form-item label="是否为患者该区间全部尿量"><el-select v-model="urine.patient_total" aria-label="尿量是否患者总量" placeholder="必须明确选择"><el-option label="是，患者总量" value="yes" /><el-option label="否，仅部分来源" value="no" /><el-option label="总量范围未知" value="unknown" /></el-select></el-form-item>
              <el-form-item label="原收集方法"><el-input v-model="urine.collection_method" aria-label="尿量收集方法" maxlength="120" placeholder="填写实际收集方法" /></el-form-item>
            </div>
            <p>填写本区间体积，不填写设备累计读数。重叠区间保留原值，不能直接相加；这里不自动求合计、速率或体重归一值。</p>
            <el-form-item label="尿量来源备注"><el-input v-model="urine.note" aria-label="尿量来源备注" type="textarea" maxlength="1000" /></el-form-item>
            <el-button type="primary" :loading="saving.urine" @click="saveUrine">登记分时尿量</el-button>
          </el-form>
          <source-list kind="urine" />
        </el-tab-pane>
        <el-tab-pane label="观测窗" name="windows">
          <el-form label-position="top" :disabled="saving.windows" @submit.prevent>
            <el-form-item label="窗口开始"><el-input v-model="windowForm.start_at" aria-label="观测窗开始" placeholder="明确填写带时区ISO" /></el-form-item>
            <el-form-item label="窗口结束"><el-input v-model="windowForm.end_at" aria-label="观测窗结束" placeholder="明确填写带时区ISO" /></el-form-item>
            <el-form-item label="截至当时可知的时点（as_of）"><el-input v-model="windowForm.as_of" aria-label="观测窗截至时点" placeholder="明确填写带时区ISO，不能早于窗口结束" /><el-button @click="windowForm.as_of = new Date().toISOString()">填入当前UTC</el-button></el-form-item>
            <p>开始须早于结束，结束不晚于截至时点，截至时点不晚于现在；最长168小时是工程限额。晚于截至时点录入的资料不进入旧窗口。无资料或空区间保持未知。</p>
            <el-button type="primary" :loading="saving.windows" @click="saveWindow">冻结本住院观测窗</el-button>
          </el-form>
          <source-list kind="windows" />
        </el-tab-pane>
      </el-tabs>
    </template>
    <el-dialog v-model="detailOpen" title="原住院观测来源核对" width="min(1000px,96vw)" @closed="clearDetail">
      <div v-loading="detailLoading" v-if="allowed">
        <p v-if="detailError" role="alert">{{ detailError }}</p>
        <template v-if="detail">
          <p class="hash">原来源 {{ rowId(detailKind, detail) }} · 患者 #{{ detail.patient_id }} · 原住院 {{ detail.admission_id }}<br />状态 {{ statusLabel(detail.status) }} · 版本 {{ detail.revision }}<br />内容摘要 {{ detail.content_hash }}</p>
          <p>{{ rowTimes(detailKind, detail) }}</p>
          <template v-if="detailKind === 'points'"><p>意识：{{ consciousnessLabel(detail.payload?.consciousness) }}；{{ oxygenLabels[detail.payload?.supplemental_oxygen] || '吸氧情况未知' }}；装置：{{ detail.payload?.oxygen_device ?? '未记录' }}</p><measurement-table :measurements="detail.payload?.measurements" /><p>原备注：{{ detail.payload?.note || '未记录' }}</p></template>
          <template v-if="detailKind === 'urine'"><p>{{ urineSummary(detail.payload) }}</p><p>收集方法：{{ detail.payload?.collection_method || '未记录' }}；备注：{{ detail.payload?.note || '未记录' }}</p></template>
          <template v-if="detailKind === 'windows'">
            <p>当前一致性：{{ freshnessLabel(detail.freshness) }} {{ detail.freshness?.message || '' }}</p>
            <p v-if="!detail.snapshot">当前响应未提供冻结数值；旧资料不能作为当前有效观测读取。</p>
            <template v-else>
              <p>以下为创建窗口时冻结的原资料：点测 {{ detail.snapshot.points.length }} 项、分时尿量 {{ detail.snapshot.urine_intervals.length }} 项；不代表连续监护齐全，未列资料保持未知。</p>
              <p v-for="message in detail.snapshot.limitations || []" :key="message">{{ message }}</p>
              <p v-if="detail.snapshot.quality?.same_time_groups?.length">有 {{ detail.snapshot.quality.same_time_groups.length }} 组同时间重复或冲突记录，未自动选取其中一项。</p>
              <p v-for="gap in detail.snapshot.quality?.measurement_gaps || []" :key="gap.measurement_code">{{ metricFields.find(field => field.key === gap.measurement_code)?.label || gap.measurement_code }}：窗口内 {{ gap.unique_numeric_observation_times ?? '未知' }} 个数值时点；最早 {{ gap.first_at ?? '未知' }}，最晚 {{ gap.last_at ?? '未知' }}；相邻原观测最大间隔 {{ gap.max_observed_gap_seconds ?? '未知' }} 秒（不是允许间隔或采样完整性判断）。</p>
              <p v-if="detail.snapshot.quality?.urine">尿量有 {{ detail.snapshot.quality.urine.overlap_groups?.length ?? '未知' }} 组重叠、{{ detail.snapshot.quality.urine.excluded_intervals?.length ?? '未知' }} 项未纳入覆盖；没有自动求总体积或速率。</p>
              <p v-for="gap in detail.snapshot.quality?.urine?.uncovered_intervals || []" :key="gap.start_at + gap.end_at">尿量未获合格区间覆盖：{{ gap.start_at }} 至 {{ gap.end_at }}；保持未知。</p>
              <div v-for="item in detail.snapshot.points" :key="item.observation_id" class="frozen-row"><p>点测 {{ item.observation_id }} · {{ item.observed_at }} · 登记 {{ item.recorded_at }} · {{ statusLabel(item.status) }}</p><p>{{ oxygenLabels[item.payload?.supplemental_oxygen] || '吸氧情况未知' }}；意识 {{ consciousnessLabel(item.payload?.consciousness) }}</p><measurement-table :measurements="item.payload?.measurements || item.measurements" /></div>
              <div v-for="item in detail.snapshot.urine_intervals" :key="item.interval_id" class="frozen-row"><p>尿量 {{ item.interval_id }} · {{ item.start_at }} 至 {{ item.end_at }} · 登记 {{ item.recorded_at }} · {{ statusLabel(item.status) }}</p><p>{{ urineSummary(item.payload || item) }}</p></div>
            </template>
          </template>
          <template v-if="detail.status === 'active' && detail.can_revoke === true"><el-input v-model="revokeReason" aria-label="观测来源撤销依据" maxlength="1000" placeholder="明确说明撤销原因，不可恢复或原地改写" /><el-button type="danger" :loading="revoking" :disabled="!revokeReason.trim()" @click="revokeDetail">撤销此观测来源</el-button></template>
          <p v-if="detail.status === 'revoked'">撤销时点 {{ detail.revoked_at || '未记录' }}；原因 {{ detail.revoke_reason || '未记录' }}。</p>
        </template>
      </div>
      <template #footer><el-button @click="detailOpen = false">关闭</el-button></template>
    </el-dialog>
  </section>
</template>

<script setup>
import { computed, defineComponent, h, onActivated, onBeforeUnmount, onDeactivated, reactive, ref, watch } from "vue";
import { useStore } from "vuex";
import { ElMessage } from "element-plus";
import { createInpatientPoint, createObservationWindow, createUrineInterval, getInpatientPoint, getInpatientPoints, getObservationWindow, getObservationWindows, getUrineInterval, getUrineIntervals, observationAbsentReasons as absentReasons, observationMetricFields as metricFields, observationOxygenLabels as oxygenLabels, observationTime, observationWindowMatches, revokeInpatientPoint, revokeObservationWindow, revokeUrineInterval } from "@/api/inpatientObservations";

const props = defineProps({ patientId: { type: Number, required: true }, admissionId: { type: String, required: true }, active: { type: Boolean, default: true } });
const emit = defineEmits(["window-created"]);
const store = useStore();
const roles = computed(() => store.getters["user/permissions"] || []);
const allowed = computed(() => props.active && Number.isSafeInteger(props.patientId) && props.patientId > 0 && !!props.admissionId && !!store.state.user.accessToken && roles.value.some(role => ["nurse", "doctor", "director", "admin", "super_admin"].includes(role)));
const blankPoint = () => ({ observed_at: "", measurements: Object.fromEntries(metricFields.map(field => [field.key, { value: "", absent_reason: "" }])), supplemental_oxygen: "", oxygen_device: "", consciousness_system: "", consciousness_code: "", note: "" });
const blankUrine = () => ({ start_at: "", end_at: "", volume_ml: "", absent_reason: "", collection_completeness: "", patient_total: "", collection_method: "", note: "" });
const blankWindow = () => ({ start_at: "", end_at: "", as_of: "" });
const point = ref(blankPoint()), urine = ref(blankUrine()), windowForm = ref(blankWindow()), tab = ref("points");
const lists = reactive({ points: [], urine: [], windows: [] }), totals = reactive({ points: null, urine: null, windows: null }), truncated = reactive({ points: false, urine: false, windows: false });
const pages = reactive({ points: 1, urine: 1 });
const loading = reactive({ points: false, urine: false, windows: false }), saving = reactive({ points: false, urine: false, windows: false }), errors = reactive({ points: "", urine: "", windows: "" });
const detailOpen = ref(false), detail = ref(null), detailKind = ref("points"), detailLoading = ref(false), detailError = ref(""), revokeReason = ref(""), revoking = ref(false);
const names = { points: "点测量", urine: "分时尿量", windows: "观测窗" }, ids = { points: "observation_id", urine: "interval_id", windows: "window_id" };
const apis = { points: { list: getInpatientPoints, detail: getInpatientPoint, create: createInpatientPoint, revoke: revokeInpatientPoint }, urine: { list: getUrineIntervals, detail: getUrineInterval, create: createUrineInterval, revoke: revokeUrineInterval }, windows: { list: getObservationWindows, detail: getObservationWindow, create: createObservationWindow, revoke: revokeObservationWindow } };
let epoch = 0, detailSequence = 0, inactive = false;
const sequences = { points: 0, urine: 0, windows: 0 };
const scopeKey = () => JSON.stringify([props.patientId, props.admissionId, props.active, store.state.user.accessToken, roles.value]);
const capture = () => ({ epoch, key: scopeKey(), patient_id: props.patientId, admission_id: props.admissionId });
const current = ticket => ticket.epoch === epoch && ticket.key === scopeKey() && allowed.value && !inactive;
const matches = (row, ticket) => row && row.patient_id === ticket.patient_id && row.admission_id === ticket.admission_id && (!row.window_id || observationWindowMatches(row, ticket.patient_id, ticket.admission_id));
const rowId = (kind, row) => row[ids[kind]];
const statusLabel = status => ({ active: "活动", revoked: "已撤销" }[status] || "未知状态");
const freshnessLabel = freshness => ({ not_checked: "尚未核对", current: "本次核对一致", stale: "原资料已变化", revoked: "已撤销" }[freshness?.state] || "尚未核对");
const rowTimes = (kind, row) => kind === "points" ? `观察 ${row.observed_at}；登记 ${row.recorded_at}` : kind === "urine" ? `收集 ${row.start_at} 至 ${row.end_at}；登记 ${row.recorded_at}` : `范围 ${row.start_at} 至 ${row.end_at}；截至 ${row.as_of}；冻结 ${row.created_at}`;
const consciousnessItems = [{ code: "alert", label: "清醒（alert）" }, { code: "voice", label: "对声音有反应（voice）" }, { code: "pain", label: "对疼痛有反应（pain）" }, { code: "unresponsive", label: "无反应（unresponsive）" }];
const consciousnessOptions = computed(() => point.value.consciousness_system === "ACVPU" ? [...consciousnessItems, { code: "new_confusion", label: "新发意识混乱（new_confusion）" }] : consciousnessItems);
const consciousnessLabel = value => value ? `${value.system} · ${value.code}` : "未观察，不用旧护理编码或GCS补齐";
function urineSummary(payload) { return `${payload?.volume_ml !== null && payload?.volume_ml !== undefined ? `${payload.volume_ml} mL` : `尿量未知（${absentReasons[payload?.absent_reason] || '未记录原因'}）`}；收集完整性：${({ complete: '完整收集', partial: '部分收集', unknown: '未知' })[payload?.collection_completeness] || '未知'}；患者总量：${payload?.patient_total === true ? '是' : payload?.patient_total === false ? '否' : '未知'}`; }
const MeasurementTable = defineComponent({ props: { measurements: Object }, setup(properties) { return () => h("dl", { class: "measurement-values", "aria-label": "原观测数值" }, metricFields.map(field => { const value = properties.measurements?.[field.key]; return h("div", { key: field.key }, [h("dt", field.label), h("dd", value?.value !== null && value?.value !== undefined ? `${value.value} ${value.unit}` : value ? absentReasons[value.absent_reason] || "未知" : "未记录")]); })); } });
const SourceList = defineComponent({
  props: { kind: String },
  setup(properties) {
    return () => {
      const kind = properties.kind;
      return h("div", { class: "source-directory", "aria-label": `${names[kind]}原来源目录` }, [
        h("button", { type: "button", disabled: loading[kind], onClick: () => load(kind) }, `刷新${names[kind]}来源`),
        errors[kind] ? h("p", { role: "alert" }, errors[kind]) : null,
        truncated[kind] ? h("p", kind === "windows" ? "目录已截断，不代表原住院全部资料。" : "当前仅显示一页，请翻页核对其余原来源。") : null,
        totals[kind] != null ? h("p", `原目录共${totals[kind]}项；第${pages[kind]}页，本页${lists[kind].length}项。`) : null,
        ...lists[kind].map(row => h("article", { key: rowId(kind, row), class: "source-row" }, [
          h("p", `${rowId(kind, row)} · ${statusLabel(row.status)} · v${row.revision}`),
          h("p", rowTimes(kind, row)),
          kind === "windows" ? h("p", `当前一致性：${freshnessLabel(row.freshness)}`) : null,
          h("button", { type: "button", onClick: () => inspect(kind, row) }, "核对原来源"),
        ])),
        kind !== "windows" && (totals[kind] > 50 || pages[kind] > 1) ? h("nav", { "aria-label": `${names[kind]}来源分页` }, [
          h("button", { type: "button", disabled: loading[kind] || pages[kind] <= 1, onClick: () => { pages[kind]--; load(kind); } }, `上一页${names[kind]}`),
          h("button", { type: "button", disabled: loading[kind] || pages[kind] * 50 >= totals[kind], onClick: () => { pages[kind]++; load(kind); } }, `下一页${names[kind]}`),
        ]) : null,
        !loading[kind] && !errors[kind] && !lists[kind].length ? h("p", "本页未显示来源；无资料不表示正常或零。") : null,
      ]);
    };
  },
});
function clearDetail() { detailSequence++; detail.value = null; detailLoading.value = false; detailError.value = ""; revokeReason.value = ""; revoking.value = false; }
function invalidate() { epoch++; clearDetail(); detailOpen.value = false; point.value = blankPoint(); urine.value = blankUrine(); windowForm.value = blankWindow(); tab.value = "points"; pages.points = 1; pages.urine = 1; for (const kind of Object.keys(apis)) { sequences[kind]++; lists[kind] = []; totals[kind] = null; truncated[kind] = false; loading[kind] = false; saving[kind] = false; errors[kind] = ""; } }
async function load(kind) {
  if (!allowed.value || inactive) return;
  const ticket = capture(), sequence = ++sequences[kind]; loading[kind] = true; errors[kind] = ""; lists[kind] = [];
  try { const response = await apis[kind].list({ patient_id: ticket.patient_id, admission_id: ticket.admission_id, ...(kind === "windows" ? {} : { page: pages[kind], page_size: 50 }) }); if (!current(ticket) || sequence !== sequences[kind]) return; const items = kind === "windows" ? response.data : response.data?.items; if (!Array.isArray(items) || items.some(row => !matches(row, ticket) || typeof rowId(kind, row) !== "string" || !rowId(kind, row))) throw new Error("返回来源与当前患者或原住院不一致"); lists[kind] = items; totals[kind] = kind === "windows" ? null : response.data.total; truncated[kind] = kind === "windows" ? response.truncated === true : response.data.total > items.length; }
  catch (failure) { if (current(ticket) && sequence === sequences[kind]) { lists[kind] = []; errors[kind] = failure?.message || "来源未能读取，请核对当前照护权限"; } }
  finally { if (current(ticket) && sequence === sequences[kind]) loading[kind] = false; }
}
async function save(kind, payload) { if (!allowed.value || inactive || saving[kind]) return; const ticket = capture(); saving[kind] = true; try { const response = await apis[kind].create({ patient_id: ticket.patient_id, admission_id: ticket.admission_id, ...payload }); if (!current(ticket)) return; if (!matches(response.data, ticket) || typeof rowId(kind, response.data) !== "string") throw new Error("登记回执与当前患者或原住院不一致"); if (kind === "points") point.value = blankPoint(); else if (kind === "urine") urine.value = blankUrine(); else { windowForm.value = blankWindow(); emit("window-created", response.data); } ElMessage.success("原来源已保存；未调用模型"); await load(kind); } catch (failure) { if (current(ticket)) ElMessage.error(failure?.response?.data?.detail || failure?.message || "保存失败，请核对原资料"); } finally { if (current(ticket)) saving[kind] = false; } }
function numericOrAbsent(value, reason) { const text = String(value ?? "").trim(); if (!!text === !!reason) throw new Error("数值与缺失原因必须且只能提供一项"); if (text && !/^-?(?:0|[1-9]\d{0,15})(?:\.\d{1,8})?$/.test(text)) throw new Error("数值须为原始十进制文本，最多16位整数和8位小数，不接受空值补0或科学计数表达式"); return { value: text || null, absent_reason: reason || null }; }
function savePoint() { if (!allowed.value || saving.points) return; try { const observed_at = observationTime(point.value.observed_at).text; if (!point.value.supplemental_oxygen) throw new Error("请明确选择观察时吸氧情况"); const measurements = {}; for (const field of metricFields) { const item = point.value.measurements[field.key]; if (item.value.trim() || item.absent_reason) measurements[field.key] = { ...numericOrAbsent(item.value, item.absent_reason), unit: field.unit }; } const system = point.value.consciousness_system, code = point.value.consciousness_code; if (!!system !== !!code) throw new Error("意识记录体系与实际观察须同时填写"); if (system === "AVPU" && code === "new_confusion") throw new Error("AVPU不包含new_confusion"); if (!Object.keys(measurements).length && !code && !["yes", "no"].includes(point.value.supplemental_oxygen)) throw new Error("至少记录一项指标或缺失原因、意识或明确的吸氧是/否；缺项不表示正常"); save("points", { observed_at, measurements, supplemental_oxygen: point.value.supplemental_oxygen, oxygen_device: point.value.oxygen_device.trim() || null, consciousness: code ? { system, code } : null, note: point.value.note }); } catch (failure) { ElMessage.warning(failure.message); } }
function saveUrine() { if (!allowed.value || saving.urine) return; try { const start = observationTime(urine.value.start_at), end = observationTime(urine.value.end_at); if (start.microseconds >= end.microseconds) throw new Error("尿量收集开始须早于结束"); const value = numericOrAbsent(urine.value.volume_ml, urine.value.absent_reason); if (!urine.value.collection_completeness || !urine.value.patient_total) throw new Error("请明确选择收集完整性和患者总量范围"); if (!urine.value.collection_method.trim()) throw new Error("请填写原收集方法"); save("urine", { start_at: start.text, end_at: end.text, volume_ml: value.value, absent_reason: value.absent_reason, collection_completeness: urine.value.collection_completeness, patient_total: urine.value.patient_total === "unknown" ? null : urine.value.patient_total === "yes", collection_method: urine.value.collection_method.trim(), note: urine.value.note }); } catch (failure) { ElMessage.warning(failure.message); } }
function saveWindow() { if (!allowed.value || saving.windows) return; try { const start = observationTime(windowForm.value.start_at), end = observationTime(windowForm.value.end_at), asOf = observationTime(windowForm.value.as_of); if (start.microseconds >= end.microseconds || end.microseconds > asOf.microseconds || asOf.microseconds > BigInt(Date.now()) * 1000n) throw new Error("须满足开始早于结束、结束不晚于截至时点、截至时点不晚于现在"); if (end.microseconds - start.microseconds > 168n * 3600n * 1000000n) throw new Error("观测窗不得超过168小时工程限额"); save("windows", { start_at: start.text, end_at: end.text, as_of: asOf.text }); } catch (failure) { ElMessage.warning(failure.message); } }
async function inspect(kind, row) { if (!allowed.value || inactive) return; clearDetail(); const ticket = capture(), sequence = detailSequence, id = rowId(kind, row); detailKind.value = kind; detailOpen.value = true; detailLoading.value = true; try { const response = await apis[kind].detail(id, { patient_id: ticket.patient_id, admission_id: ticket.admission_id }); if (!current(ticket) || sequence !== detailSequence || !detailOpen.value) return; if (!matches(response.data, ticket) || rowId(kind, response.data) !== id) throw new Error("原来源回执与当前患者、住院或来源ID不一致"); detail.value = response.data; } catch (failure) { if (current(ticket) && sequence === detailSequence && detailOpen.value) detailError.value = failure?.message || "原来源未能核对"; } finally { if (current(ticket) && sequence === detailSequence) detailLoading.value = false; } }
async function revokeDetail() { if (!allowed.value || inactive || !detail.value || detail.value.status !== "active" || detail.value.can_revoke !== true || !revokeReason.value.trim() || revoking.value) return; const ticket = capture(), sequence = detailSequence, kind = detailKind.value, id = rowId(kind, detail.value); revoking.value = true; try { const body = { expected_revision: detail.value.revision, reason: revokeReason.value.trim(), ...(kind === "windows" ? {} : { patient_id: ticket.patient_id, admission_id: ticket.admission_id }) }; const response = await apis[kind].revoke(id, body); if (!current(ticket) || sequence !== detailSequence || !detailOpen.value) return; if (!matches(response.data, ticket) || rowId(kind, response.data) !== id) throw new Error("撤销回执与原来源不一致"); detail.value = response.data; revokeReason.value = ""; await load(kind); } catch (failure) { if (current(ticket) && sequence === detailSequence) ElMessage.error(failure?.message || "撤销失败，请重新核对版本与权限"); } finally { if (current(ticket) && sequence === detailSequence) revoking.value = false; } }
function reloadAll() { if (allowed.value && !inactive) for (const kind of Object.keys(apis)) load(kind); }
watch(scopeKey, () => { invalidate(); reloadAll(); }, { immediate: true, flush: "sync" });
onDeactivated(() => { inactive = true; invalidate(); });
onActivated(() => { if (inactive) { inactive = false; invalidate(); reloadAll(); } });
onBeforeUnmount(() => { inactive = true; invalidate(); });
</script>

<style scoped>
.observation-panel p { line-height: 1.7; }.measurement-grid { display: grid; grid-template-columns: repeat(auto-fit,minmax(220px,1fr)); gap: 12px; }fieldset { min-width: 0; border: 1px solid #dcdfe6; padding: 12px; }fieldset .el-select { margin-top: 8px; width: 100%; }.source-directory { margin-top: 24px; }.source-row,.frozen-row { border-top: 1px solid #dcdfe6; padding: 12px 0; }.hash,.quality { overflow-wrap: anywhere; }.measurement-values { display: grid; grid-template-columns: repeat(auto-fit,minmax(180px,1fr)); gap: 8px; }.measurement-values dd { margin-left: 0; }
</style>
