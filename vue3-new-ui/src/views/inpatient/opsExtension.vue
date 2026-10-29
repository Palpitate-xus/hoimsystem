<template>
  <div class="app-container">
    <el-tabs v-model="tab">
      <!-- CSSD -->
      <el-tab-pane label="CSSD 器械包" name="cssd">
        <div class="page-toolbar">
          <el-select v-model="cssdQuery.status" placeholder="状态" clearable style="width: 130px" @change="loadCssd">
            <el-option v-for="(t, k) in cssdStatus" :key="k" :label="t" :value="Number(k)" />
          </el-select>
          <el-button type="primary" @click="cssdDialogVisible = true">登记器械包</el-button>
        </div>
        <el-table :data="cssdData" v-loading="cssdLoading" border empty-text="暂无器械包">
          <el-table-column prop="package_code" label="包内卡号" width="110" />
          <el-table-column prop="package_name" label="器械包名" min-width="140" />
          <el-table-column prop="sterilize_method" label="灭菌方式" width="90" />
          <el-table-column prop="status_text" label="状态" width="100">
            <template #default="{ row }">
              <el-tag size="small" :type="row.status === 4 ? 'success' : row.status === 6 ? 'danger' : 'info'">{{ row.status_text }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="BD/生物" width="90">
            <template #default="{ row }">{{ row.bd_test === null ? "-" : row.bd_test ? "✓" : "✗" }} / {{ row.biological_monitor === null ? "-" : row.biological_monitor ? "✓" : "✗" }}</template>
          </el-table-column>
          <el-table-column prop="sterilize_date" label="灭菌日期" width="105" />
          <el-table-column prop="expire_date" label="无菌效期" width="105" />
          <el-table-column prop="current_location" label="位置" width="90" />
          <el-table-column label="流转" width="90">
            <template #default="{ row }">
              <el-button size="small" @click="openCssdTransition(row)">流转</el-button>
            </template>
          </el-table-column>
        </el-table>
      </el-tab-pane>

      <!-- PIVAS -->
      <el-tab-pane label="PIVAS 批次" name="pivas">
        <div class="page-toolbar">
          <el-button type="primary" @click="pivasDialogVisible = true">创建批次</el-button>
        </div>
        <el-table :data="pivasData" v-loading="pivasLoading" border empty-text="暂无批次">
          <el-table-column prop="batch_no" label="批次号" width="100" />
          <el-table-column prop="plan_date" label="调配日期" width="105" />
          <el-table-column prop="ward_name" label="病区" width="110" />
          <el-table-column prop="status_text" label="状态" width="100" />
          <el-table-column prop="label_count" label="贴签数" width="80" />
          <el-table-column label="标记" width="120">
            <template #default="{ row }">
              <el-tag v-if="row.cytotoxic" size="small" type="danger">细胞毒</el-tag>
              <el-tag v-if="row.tpn" size="small" type="warning" style="margin-left: 4px">肠外营养</el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="receive_time" label="签收时间" width="160" />
          <el-table-column label="流转" width="90">
            <template #default="{ row }">
              <el-button size="small" :disabled="row.status === 5" @click="openPivasTransition(row)">流转</el-button>
            </template>
          </el-table-column>
        </el-table>
      </el-tab-pane>

      <!-- ICU 评分 -->
      <el-tab-pane label="ICU/PACU 评分" name="score">
        <div class="page-toolbar">
          <el-select v-model="scoreQuery.score_type" placeholder="评分类型" clearable style="width: 140px" @change="loadScores">
            <el-option label="APACHE II" value="apache2" />
            <el-option label="SOFA" value="sofa" />
            <el-option label="GCS" value="gcs" />
            <el-option label="Aldrete" value="aldrete" />
            <el-option label="Steward" value="steward" />
          </el-select>
          <el-button type="primary" @click="openScoreDialog">新建评分</el-button>
        </div>
        <el-table :data="scoreData" v-loading="scoreLoading" border empty-text="暂无评分记录">
          <el-table-column prop="patient_name" label="患者" width="90" />
          <el-table-column prop="score_type_text" label="类型" width="100" />
          <el-table-column prop="scene" label="场景原标记" width="110">
            <template #default="{ row }">{{ row.scene === "pacu" ? "PACU" : row.scene === "icu" ? "ICU" : "未记录/未知" }}</template>
          </el-table-column>
          <el-table-column label="人工分项与原始总分" min-width="230"><template #default="{ row }"><div>原始总分：{{ row.total_score ?? '未记录' }}</div><div>{{ scoreDetailText(row) }}</div><el-tag :type="row.calculation_version === 'manual_components_v2' ? 'info' : 'warning'">{{ row.calculation_version === 'manual_components_v2' ? '人工分项汇总' : '历史原值未核实' }}</el-tag><div v-if="row.component_integrity && row.calculation_version === 'manual_components_v2'">{{ row.component_integrity.status === 'complete' ? '分项齐全；来源尚未独立核实' : '分项待核对' }}</div></template></el-table-column>
          <el-table-column label="汇总说明" min-width="230"><template #default="{ row }"><div v-if="row.calculation_version !== 'manual_components_v2'">原记录说明（未核实）：{{ row.interpretation ?? '未记录' }}</div><template v-else><div>{{ row.score_definition ?? '版本未记录' }}</div><div>{{ row.scope_note ?? '仅汇总人工分项，须结合原始资料核实。' }}</div></template></template></el-table-column>
          <el-table-column label="评估时点与登记时间" min-width="240"><template #default="{ row }"><div>评估：{{ row.assessed_at ?? '未记录' }}</div><div>{{ row.time_basis === 'assessed_at_declared' ? '已声明评估时点（UTC）' : '实际评估时点未知' }}</div><div>登记：{{ row.create_time ?? row.assess_time ?? '未记录' }}</div></template></el-table-column>
          <el-table-column v-if="canUseNursingAI" label="AI辅助" width="150"><template #default="{ row }"><ai-action v-if="row.admission_id" label="AI 评分资料辅助" title="AI 原人工评分资料辅助" :patient-id="Number(row.patient_id)" :encounter-ref="row.admission_id" :feature-keys="['deterioration_risk', 'sepsis_risk', 'aki_risk', 'handover_summary']" initial-feature="handover_summary" :initial-input="{ icu_score_id: String(row.score_id) }" /><span v-else>未关联住院，不提供本次就诊 AI</span></template></el-table-column>
        </el-table>
      </el-tab-pane>

      <!-- 临床路径 -->
      <el-tab-pane label="临床路径执行" name="pathway">
        <div class="page-toolbar">
          <el-select v-model="pathwayQuery.status" placeholder="状态" clearable style="width: 110px" @change="loadPathways">
            <el-option label="在径" :value="1" />
            <el-option label="变异" :value="2" />
            <el-option label="完成出径" :value="3" />
            <el-option label="退出" :value="4" />
          </el-select>
          <el-button type="primary" @click="pathwayDialogVisible = true">患者入组</el-button>
        </div>
        <el-table :data="pathwayData" v-loading="pathwayLoading" border empty-text="暂无入组记录">
          <el-table-column prop="pathway_name" label="路径" min-width="140" />
          <el-table-column prop="patient_name" label="患者" width="90" />
          <el-table-column prop="status_text" label="状态" width="90">
            <template #default="{ row }">
              <el-tag size="small" :type="{ 1: 'success', 2: 'warning', 3: 'primary', 4: 'danger' }[row.status]">{{ row.status_text }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="enroll_date" label="入组日期" width="105" />
          <el-table-column label="进度" width="140">
            <template #default="{ row }">
              <el-progress v-if="row.counter_state === 'known' && typeof row.completion_rate === 'number'" :percentage="row.completion_rate" :stroke-width="12" />
              <span v-else :title="row.counter_note">{{ row.counter_state === 'invalid' ? '原计数矛盾，待核对' : '进度未知' }}</span>
            </template>
          </el-table-column>
          <el-table-column prop="variation_reason" label="变异原因" min-width="120" show-overflow-tooltip />
          <el-table-column label="操作" width="420">
            <template #default="{ row }">
              <el-button v-if="row.status === 1 || row.status === 2" size="small" @click="handleRecordProgress(row)">登记进度</el-button>
              <el-button v-if="row.status === 1" size="small" type="warning" @click="handleVariation(row)">变异</el-button>
              <el-button v-if="row.status === 1 || row.status === 2" size="small" type="success" @click="handleExit(row, 3)">出径</el-button>
              <el-button v-if="row.status === 1 || row.status === 2" size="small" type="danger" @click="handleExit(row, 4)">退出</el-button>
              <ai-action v-if="canUsePathwayAI" label="AI 路径复评" title="AI 原入径记录与疗效复评" :patient-id="row.patient_id" :encounter-ref="row.admission_id || ''" :feature-keys="['response_review', 'treatment_pathway', 'patient_summary', 'progress_note', 'discharge_summary']" initial-feature="response_review" :initial-input="{ pathway_enrollment_id: String(row.enrollment_id), pathway_id: String(row.pathway_id) }" />
            </template>
          </el-table-column>
        </el-table>
      </el-tab-pane>
    </el-tabs>

    <!-- CSSD 对话框 -->
    <el-dialog v-model="cssdDialogVisible" title="登记器械包" width="480px">
      <el-form :model="cssdForm" label-width="100px" class="dialog-form">
        <el-form-item label="器械包名"><el-input v-model="cssdForm.package_name" /></el-form-item>
        <el-form-item label="包内卡号"><el-input v-model="cssdForm.package_code" placeholder="唯一，可扫码生成" /></el-form-item>
        <el-form-item label="包内清单"><el-input v-model="cssdForm.contents" type="textarea" :rows="2" placeholder="如：弯盘×1、镊子×2、纱布×10" /></el-form-item>
        <el-form-item label="灭菌方式">
          <el-select v-model="cssdForm.sterilize_method">
            <el-option label="压力蒸汽" value="压力蒸汽" />
            <el-option label="环氧乙烷" value="环氧乙烷" />
            <el-option label="低温等离子" value="低温等离子" />
            <el-option label="干热灭菌" value="干热灭菌" />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer><el-button @click="cssdDialogVisible = false">取消</el-button><el-button type="primary" @click="handleCreateCssd">登记</el-button></template>
    </el-dialog>

    <el-dialog v-model="cssdTransitionVisible" title="器械包流转" width="440px">
      <el-form label-width="110px">
        <el-form-item label="目标状态">
          <el-select v-model="cssdTransitionForm.status">
            <el-option v-for="s in cssdNextStates" :key="s.value" :label="s.label" :value="s.value" />
          </el-select>
        </el-form-item>
        <el-form-item v-if="cssdTransitionForm.status === 3" label="BD试验">
          <el-radio-group v-model="cssdTransitionForm.bd_test">
            <el-radio :label="1">通过</el-radio>
            <el-radio :label="0">失败</el-radio>
          </el-radio-group>
        </el-form-item>
        <el-form-item v-if="cssdTransitionForm.status === 4" label="生物监测">
          <el-radio-group v-model="cssdTransitionForm.biological_monitor">
            <el-radio :label="1">通过</el-radio>
            <el-radio :label="0">失败</el-radio>
          </el-radio-group>
        </el-form-item>
        <el-form-item v-if="cssdTransitionForm.status === 4" label="无菌效期">
          <el-date-picker v-model="cssdTransitionForm.expire_date" type="date" value-format="YYYY-MM-DD" style="width: 100%" />
        </el-form-item>
        <el-form-item v-if="cssdTransitionForm.status === 5" label="发放位置">
          <el-input v-model="cssdTransitionForm.current_location" placeholder="如：手术室3间" />
        </el-form-item>
      </el-form>
      <template #footer><el-button @click="cssdTransitionVisible = false">取消</el-button><el-button type="primary" @click="handleCssdTransition">确认流转</el-button></template>
    </el-dialog>

    <!-- PIVAS 对话框 -->
    <el-dialog v-model="pivasDialogVisible" title="创建调配批次" width="460px">
      <el-form :model="pivasForm" label-width="100px" class="dialog-form">
        <el-form-item label="批次号"><el-input v-model="pivasForm.batch_no" placeholder="如 0801-A" /></el-form-item>
        <el-form-item label="调配日期">
          <el-date-picker v-model="pivasForm.plan_date" type="date" value-format="YYYY-MM-DD" style="width: 100%" />
        </el-form-item>
        <el-form-item label="病区ID"><el-input v-model="pivasForm.ward_id" placeholder="选填" /></el-form-item>
        <el-form-item label="贴签数"><el-input-number v-model="pivasForm.label_count" :min="0" :controls="false" style="width: 100%" /></el-form-item>
        <el-form-item label="含细胞毒"><el-switch v-model="pivasForm.cytotoxic" /></el-form-item>
        <el-form-item label="含肠外营养"><el-switch v-model="pivasForm.tpn" /></el-form-item>
      </el-form>
      <template #footer><el-button @click="pivasDialogVisible = false">取消</el-button><el-button type="primary" @click="handleCreatePivas">创建</el-button></template>
    </el-dialog>

    <el-dialog v-model="pivasTransitionVisible" title="批次流转" width="400px">
      <el-alert :closable="false" :title="`当前状态：${pivasCurrent.status_text}；配置与核对须双人`" type="info" />
      <el-form label-width="100px" style="margin-top: 12px">
        <el-form-item label="目标状态">
          <el-select v-model="pivasTransitionStatus">
            <el-option :label="pivasNextLabel" :value="pivasCurrent.status + 1" />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer><el-button @click="pivasTransitionVisible = false">取消</el-button><el-button type="primary" @click="handlePivasTransition">确认</el-button></template>
    </el-dialog>

    <!-- 评分对话框：仅汇总已明确录入的全部人工分项。 -->
    <el-dialog v-model="scoreDialogVisible" title="新建专科评分" width="620px" @closed="closeScoreDialog">
      <el-form :model="scoreForm" label-width="120px" class="dialog-form" @submit.prevent>
        <el-form-item label="患者ID"><el-input-number v-model="scoreForm.patient_id" aria-label="评分患者ID" :min="1" :controls="false" :precision="0" placeholder="必填" @change="changeScorePatient" /></el-form-item>
        <el-form-item label="住院ID"><el-input v-model="scoreForm.admission_id" aria-label="评分住院ID" placeholder="可空；仅填写真实住院标识，保存时核实归属" @input="resetScoreValues" /></el-form-item>
        <el-form-item label="评分类型"><el-select v-model="scoreForm.score_type" aria-label="评分类型" @change="resetScoreValues"><el-option label="APACHE II" value="apache2" /><el-option label="SOFA（原1996版）" value="sofa" /><el-option label="GCS" value="gcs" /><el-option label="Aldrete（原1970肤色版）" value="aldrete" /><el-option label="Steward（原1975版）" value="steward" /></el-select></el-form-item>
        <el-form-item label="场景"><el-radio-group v-model="scoreForm.scene" aria-label="评分场景" @change="resetScoreValues"><el-radio value="icu">ICU</el-radio><el-radio value="pacu">PACU</el-radio></el-radio-group></el-form-item>
        <p class="sofa-hint">{{ scoreDefinitions[scoreForm.score_type] }}。所有分项须人工明确录入；未测、无法评估或缺项时不能计算。汇总不判断死亡风险、器官功能或 PACU 转出条件。</p>
        <el-form-item v-for="field in currentScoreFields" :key="`${scoreForm.score_type}:${field.key}`" :label="field.label">
          <el-input-number v-if="field.key === 'aps_total'" v-model="scoreForm.detail[field.key]" :aria-label="field.label" :min="0" :max="60" :precision="0" :controls="false" placeholder="未评估" />
          <el-select v-else v-model="scoreForm.detail[field.key]" :aria-label="field.label" clearable placeholder="未评估"><el-option v-for="value in field.values" :key="value" :label="String(value)" :value="value" /></el-select>
        </el-form-item>
        <el-form-item label="评估时点"><el-input v-model="scoreForm.assessed_at" aria-label="评分评估时点" placeholder="如 2026-10-20T08:30:00+08:00，可留空" /></el-form-item>
        <p class="sofa-hint">留空时点仅保存登记时间。住院 ID 留空时不提供固定本次住院的 AI 入口。</p>
      </el-form>
      <template #footer><el-button @click="scoreDialogVisible = false">取消</el-button><el-button type="primary" :loading="scoreSubmitting" @click="handleCreateScore">提交评分</el-button></template>
    </el-dialog>

    <!-- 路径入组对话框 -->
    <el-dialog v-model="pathwayDialogVisible" title="患者入组临床路径" width="460px">
      <el-form :model="pathwayForm" label-width="100px" class="dialog-form">
        <el-form-item label="路径ID"><el-input v-model="pathwayForm.pathway_id" placeholder="临床路径模板编号" /></el-form-item>
        <el-form-item label="患者ID"><el-input v-model="pathwayForm.patient_id" /></el-form-item>
        <el-form-item label="住院ID"><el-input v-model="pathwayForm.admission_id" placeholder="选填" /></el-form-item>
        <el-form-item label="应完成节点"><el-input-number v-model="pathwayForm.total_items" :min="0" :controls="false" style="width: 100%" /></el-form-item>
      </el-form>
      <template #footer><el-button @click="pathwayDialogVisible = false">取消</el-button><el-button type="primary" @click="handleEnroll">入组</el-button></template>
    </el-dialog>
  </div>
</template>

<script>
import { getCssdList, createCssd, transitionCssd, getPivasList, createPivas, transitionPivas, getIcuScoreList, createIcuScore, getPathwayEnrollmentList, enrollPathway, recordPathwayProgress, recordPathwayVariation, exitPathway } from "@/api/hisModules";
import { ElMessage, ElMessageBox } from "element-plus";
import AiAction from "@/components/AIAction/index.vue";


const scoreFields = {
  gcs: [{ key: "eye", label: "睁眼(1-4)", values: [1, 2, 3, 4] }, { key: "verbal", label: "语言(1-5)", values: [1, 2, 3, 4, 5] }, { key: "motor", label: "运动(1-6)", values: [1, 2, 3, 4, 5, 6] }],
  apache2: [{ key: "aps_total", label: "APS合计(0-60)" }, { key: "age_points", label: "年龄评分(0/2/3/5/6)", values: [0, 2, 3, 5, 6] }, { key: "chronic_health_points", label: "慢性健康(0/2/5)", values: [0, 2, 5] }],
  sofa: ["resp", "coag", "liver", "cardio", "neuro", "renal"].map((key, i) => ({ key: `${key}_score`, label: ["呼吸", "凝血", "肝脏", "心血管", "神经", "肾脏"][i], values: [0, 1, 2, 3, 4] })),
  aldrete: ["activity", "respiration", "circulation", "consciousness", "color"].map((key, i) => ({ key: `${key}_score`, label: ["活动", "呼吸", "循环", "意识", "肤色"][i], values: [0, 1, 2] })),
  steward: ["wake", "airway", "motor"].map((key, i) => ({ key: `${key}_score`, label: ["清醒程度", "气道通畅", "肢体活动"][i], values: [0, 1, 2] })),
};
const newScoreForm = () => ({ patient_id: null, admission_id: "", score_type: "gcs", scene: "icu", detail: Object.fromEntries(scoreFields.gcs.map(field => [field.key, null])), assessed_at: "" });
const scoreAwareTime = value => {
  const text = value.trim();
  if (!text) return null;
  const match = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.\d{1,6})?(Z|[+-]\d{2}:\d{2})$/.exec(text);
  if (!match) throw new Error("评估时点须带时区，例如 2026-10-20T08:30:00+08:00");
  const [, year, month, day, hour, minute, second, zone] = match;
  const y = Number(year), m = Number(month), d = Number(day), days = [31, y % 4 === 0 && (y % 100 !== 0 || y % 400 === 0) ? 29 : 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31];
  if (y < 1 || m < 1 || m > 12 || d < 1 || d > days[m - 1] || Number(hour) > 23 || Number(minute) > 59 || Number(second) > 59 || (zone !== "Z" && (Number(zone.slice(1, 3)) > 23 || Number(zone.slice(4)) > 59)) || !Number.isFinite(Date.parse(text)) || new Date(text).getUTCFullYear() < 1 || new Date(text).getUTCFullYear() > 9999) throw new Error("请输入合法的日期、时间和时区");
  return text;
};

export default {
  name: "OpsExtension",
  components: { AiAction },
  data() {
    return {
      tab: "cssd",
      cssdStatus: { 0: "待回收", 1: "清洗中", 2: "检查打包", 3: "灭菌中", 4: "无菌可用", 5: "发放使用中", 6: "报损" },
      cssdFlow: { 0: [1], 1: [2], 2: [3], 3: [4, 6], 4: [5, 6], 5: [0, 6] },
      cssdLoading: false, cssdData: [], cssdQuery: { status: null },
      cssdDialogVisible: false, cssdForm: { sterilize_method: "压力蒸汽" },
      cssdTransitionVisible: false, cssdTransitionForm: {}, cssdCurrentItem: null,
      pivasLoading: false, pivasData: [],
      pivasDialogVisible: false, pivasForm: { label_count: 0 },
      pivasTransitionVisible: false, pivasTransitionStatus: null, pivasCurrent: {},
      scoreLoading: false, scoreData: [], scoreQuery: { score_type: null },
      scoreDialogVisible: false, scoreForm: newScoreForm(), scoreSubmitting: false, scoreEpoch: 0, scoreLoadSequence: 0,
      scoreDefinitions: { gcs: "GCS 人工分项", apache2: "APACHE II 人工分项（APS已由人员汇总）", sofa: "SOFA 原1996版人工分项", aldrete: "Aldrete 原1970肤色版", steward: "Steward 原1975版人工分项" },
      pathwayLoading: false, pathwayData: [], pathwayQuery: { status: null },
      pathwayDialogVisible: false, pathwayForm: { total_items: 0 },
    };
  },
  computed: {
    canUseNursingAI() { return this.$store.getters["user/permissions"].some(role => ["super_admin", "doctor", "director", "nurse"].includes(role)); },
    currentScoreFields() { return scoreFields[this.scoreForm.score_type] ?? []; },
    canUsePathwayAI() { return this.$store.getters["user/permissions"].some(role => ["super_admin", "doctor", "director"].includes(role)); },
    cssdNextStates() {
      if (!this.cssdCurrentItem) return [];
      return (this.cssdFlow[this.cssdCurrentItem.status] || []).map((s) => ({ value: s, label: this.cssdStatus[s] }));
    },
    pivasNextLabel() {
      const labels = { 0: "已排药贴签", 1: "配置中", 2: "成品核对", 3: "已配送", 4: "病区签收" };
      return labels[this.pivasCurrent.status] || "";
    },
  },
  deactivated() { this.scoreEpoch++; this.scoreLoadSequence++; this.scoreDialogVisible = false; this.scoreForm = newScoreForm(); this.scoreLoading = false; },
  beforeUnmount() { this.scoreEpoch++; this.scoreLoadSequence++; },
  created() {
    this.loadCssd();
    this.loadPivas();
    this.loadScores();
    this.loadPathways();
  },
  methods: {
    async loadCssd() {
      this.cssdLoading = true;
      try { const res = await getCssdList(this.cssdQuery); this.cssdData = res.data || []; } finally { this.cssdLoading = false; }
    },
    async handleCreateCssd() {
      const res = await createCssd(this.cssdForm);
      if (res.code === 200) { ElMessage.success("已登记"); this.cssdDialogVisible = false; this.cssdForm = { sterilize_method: "压力蒸汽" }; this.loadCssd(); }
      else ElMessage.error(res.msg);
    },
    openCssdTransition(row) {
      this.cssdCurrentItem = row;
      this.cssdTransitionForm = { status: (this.cssdFlow[row.status] || [])[0] };
      this.cssdTransitionVisible = true;
    },
    async handleCssdTransition() {
      const res = await transitionCssd({ instrument_id: this.cssdCurrentItem.instrument_id, ...this.cssdTransitionForm });
      if (res.code === 200) { ElMessage.success("已流转"); this.cssdTransitionVisible = false; this.loadCssd(); }
      else ElMessage.error(res.msg);
    },
    async loadPivas() {
      this.pivasLoading = true;
      try { const res = await getPivasList({}); this.pivasData = res.data || []; } finally { this.pivasLoading = false; }
    },
    async handleCreatePivas() {
      const res = await createPivas(this.pivasForm);
      if (res.code === 200) { ElMessage.success("批次已创建"); this.pivasDialogVisible = false; this.pivasForm = { label_count: 0 }; this.loadPivas(); }
      else ElMessage.error(res.msg);
    },
    openPivasTransition(row) {
      this.pivasCurrent = row;
      this.pivasTransitionStatus = row.status + 1;
      this.pivasTransitionVisible = true;
    },
    async handlePivasTransition() {
      const res = await transitionPivas({ batch_id: this.pivasCurrent.batch_id, status: this.pivasTransitionStatus });
      if (res.code === 200) { ElMessage.success("已流转"); this.pivasTransitionVisible = false; this.loadPivas(); }
      else ElMessage.error(res.msg);
    },
    openScoreDialog() { this.scoreEpoch++; this.scoreForm = newScoreForm(); this.scoreDialogVisible = true; },
    closeScoreDialog() { this.scoreEpoch++; this.scoreForm = newScoreForm(); },
    resetScoreValues() { this.scoreEpoch++; this.scoreForm.detail = Object.fromEntries(this.currentScoreFields.map(field => [field.key, null])); this.scoreForm.assessed_at = ""; },
    changeScorePatient() { this.scoreForm.admission_id = ""; this.resetScoreValues(); },
    scoreDetailText(row) {
      const detail = row.detail;
      if (!detail || typeof detail !== "object" || Array.isArray(detail)) return "原分项未记录或无法解析";
      return Object.entries(detail).map(([key, value]) => `${scoreFields[row.score_type]?.find(field => field.key === key)?.label ?? key}：${value ?? '未记录'}`).join("；") || "原分项未记录";
    },
    async loadScores() {
      const sequence = ++this.scoreLoadSequence;
      this.scoreLoading = true;
      try { const res = await getIcuScoreList(this.scoreQuery); if (sequence === this.scoreLoadSequence) this.scoreData = res.data ?? []; }
      catch (error) { if (sequence === this.scoreLoadSequence) ElMessage.error(error?.msg || "评分记录加载失败"); }
      finally { if (sequence === this.scoreLoadSequence) this.scoreLoading = false; }
    },
    async handleCreateScore() {
      if (this.scoreSubmitting) return;
      if (!Number.isSafeInteger(this.scoreForm.patient_id) || this.scoreForm.patient_id < 1) { ElMessage.warning("请填写有效的患者ID"); return; }
      const fields = this.currentScoreFields;
      if (!fields.length || fields.some(field => !Number.isInteger(this.scoreForm.detail[field.key]) || (field.values ? !field.values.includes(this.scoreForm.detail[field.key]) : this.scoreForm.detail[field.key] < 0 || this.scoreForm.detail[field.key] > 60))) { ElMessage.warning("请明确填写所有人工分项；未测或无法评估时不能计算"); return; }
      let assessed_at;
      try { assessed_at = scoreAwareTime(this.scoreForm.assessed_at); } catch (error) { ElMessage.warning(error.message); return; }
      const payload = { patient_id: this.scoreForm.patient_id, admission_id: this.scoreForm.admission_id.trim() || null, score_type: this.scoreForm.score_type, scene: this.scoreForm.scene, detail: Object.fromEntries(fields.map(field => [field.key, this.scoreForm.detail[field.key]])), assessed_at }, epoch = this.scoreEpoch;
      this.scoreSubmitting = true;
      try {
        const res = await createIcuScore(payload);
        if (res.code === 200) {
          ElMessage.success(`人工分项已保存，总分 ${res.data.total_score}；须结合原资料核实`);
          if (epoch === this.scoreEpoch) { this.scoreDialogVisible = false; this.scoreEpoch++; this.scoreForm = newScoreForm(); }
          await this.loadScores();
        } else ElMessage.error(res.msg);
      } catch (error) { ElMessage.error(error?.msg || "评分保存失败"); } finally { this.scoreSubmitting = false; }
    },
    async loadPathways() {
      this.pathwayLoading = true;
      try { const res = await getPathwayEnrollmentList(this.pathwayQuery); this.pathwayData = res.data || []; } finally { this.pathwayLoading = false; }
    },
    async handleEnroll() {
      const res = await enrollPathway(this.pathwayForm);
      if (res.code === 200) { ElMessage.success("已入组"); this.pathwayDialogVisible = false; this.pathwayForm = { total_items: 0 }; this.loadPathways(); }
      else ElMessage.error(res.msg);
    },
    async handleRecordProgress(row) {
      const { value } = await ElMessageBox.prompt(`已完成节点数（0-${row.total_items}）`, "登记进度", {
        inputPattern: /^\d+$/, inputValue: String(row.completed_items || 0),
        inputErrorMessage: "请输入数字",
      });
      const res = await recordPathwayProgress({ enrollment_id: row.enrollment_id, completed_items: Number(value) });
      if (res.code === 200) this.loadPathways();
      else ElMessage.error(res.msg);
    },
    async handleVariation(row) {
      const { value } = await ElMessageBox.prompt("变异原因", "登记变异", { inputPattern: /\S+/, inputErrorMessage: "必填" });
      const types = ["病情变异", "医方变异", "患方变异", "系统变异"];
      const { value: vtype } = await ElMessageBox.prompt(`变异类型（${types.join("/")}）`, "变异类型", { inputValue: "病情变异" });
      const res = await recordPathwayVariation({ enrollment_id: row.enrollment_id, variation_reason: value, variation_type: types.includes(vtype) ? vtype : "病情变异" });
      if (res.code === 200) this.loadPathways();
      else ElMessage.error(res.msg);
    },
    async handleExit(row, status) {
      if (status === 3) {
        await ElMessageBox.confirm("确认完成出径？（须全部节点完成）", "完成出径");
        const res = await exitPathway({ enrollment_id: row.enrollment_id, status: 3 });
        if (res.code === 200) { ElMessage.success("已完成出径"); this.loadPathways(); }
        else ElMessage.error(res.msg);
      } else {
        const { value } = await ElMessageBox.prompt("退出原因", "退出路径", { inputPattern: /\S+/, inputErrorMessage: "必填" });
        const res = await exitPathway({ enrollment_id: row.enrollment_id, status: 4, exit_reason: value });
        if (res.code === 200) { this.loadPathways(); }
        else ElMessage.error(res.msg);
      }
    },
  },
};
</script>

<style scoped>
.sofa-hint { color: var(--el-text-color-secondary); font-size: 12px; margin: 0 0 8px; }
</style>
