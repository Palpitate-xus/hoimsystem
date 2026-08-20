<template>
  <div class="app-container">
    <vab-page-header title="运营扩展：CSSD / PIVAS / ICU评分 / 临床路径" description="器械消毒供应、静配中心、专科评分与路径执行（全部手工登记，无预置数据）" />
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
          <el-button type="primary" @click="scoreDialogVisible = true">新建评分</el-button>
        </div>
        <el-table :data="scoreData" v-loading="scoreLoading" border empty-text="暂无评分记录">
          <el-table-column prop="patient_name" label="患者" width="90" />
          <el-table-column prop="score_type_text" label="类型" width="100" />
          <el-table-column prop="scene" label="场景" width="70">
            <template #default="{ row }">{{ row.scene === "pacu" ? "PACU" : "ICU" }}</template>
          </el-table-column>
          <el-table-column prop="total_score" label="总分" width="70" />
          <el-table-column prop="interpretation" label="结论" min-width="180" />
          <el-table-column prop="assess_time" label="评估时间" width="160" />
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
              <el-progress :percentage="row.completion_rate || 0" :stroke-width="12" />
            </template>
          </el-table-column>
          <el-table-column prop="variation_reason" label="变异原因" min-width="120" show-overflow-tooltip />
          <el-table-column label="操作" width="230">
            <template #default="{ row }">
              <el-button v-if="row.status === 1 || row.status === 2" size="small" @click="handleRecordProgress(row)">登记进度</el-button>
              <el-button v-if="row.status === 1" size="small" type="warning" @click="handleVariation(row)">变异</el-button>
              <el-button v-if="row.status === 1 || row.status === 2" size="small" type="success" @click="handleExit(row, 3)">出径</el-button>
              <el-button v-if="row.status === 1 || row.status === 2" size="small" type="danger" @click="handleExit(row, 4)">退出</el-button>
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

    <!-- 评分对话框 -->
    <el-dialog v-model="scoreDialogVisible" title="新建专科评分" width="560px">
      <el-form :model="scoreForm" label-width="110px" class="dialog-form">
        <el-form-item label="患者ID"><el-input v-model="scoreForm.patient_id" /></el-form-item>
        <el-form-item label="评分类型">
          <el-select v-model="scoreForm.score_type" @change="scoreForm.detail = {}">
            <el-option label="APACHE II" value="apache2" />
            <el-option label="SOFA" value="sofa" />
            <el-option label="GCS" value="gcs" />
            <el-option label="Aldrete(PACU)" value="aldrete" />
            <el-option label="Steward(PACU)" value="steward" />
          </el-select>
        </el-form-item>
        <el-form-item label="场景">
          <el-radio-group v-model="scoreForm.scene">
            <el-radio label="icu">ICU</el-radio>
            <el-radio label="pacu">PACU</el-radio>
          </el-radio-group>
        </el-form-item>
        <template v-if="scoreForm.score_type === 'gcs'">
          <el-form-item label="睁眼(1-4)"><el-input-number v-model="scoreForm.detail.eye" :min="1" :max="4" /></el-form-item>
          <el-form-item label="语言(1-5)"><el-input-number v-model="scoreForm.detail.verbal" :min="1" :max="5" /></el-form-item>
          <el-form-item label="运动(1-6)"><el-input-number v-model="scoreForm.detail.motor" :min="1" :max="6" /></el-form-item>
        </template>
        <template v-else-if="scoreForm.score_type === 'apache2'">
          <el-form-item label="年龄评分(0-6)"><el-input-number v-model="scoreForm.detail.age_points" :min="0" :max="6" /></el-form-item>
          <el-form-item label="APS 合计(0-60)"><el-input-number v-model="scoreForm.detail.aps_total" :min="0" :max="60" /></el-form-item>
          <el-form-item label="慢性健康(0/2/5)"><el-input-number v-model="scoreForm.detail.chronic_health_points" :min="0" :max="5" /></el-form-item>
        </template>
        <template v-else-if="scoreForm.score_type === 'sofa'">
          <p class="sofa-hint">六项脏器各 0-4 分（呼吸/凝血/肝脏/心血管/神经/肾脏）</p>
          <el-form-item v-for="o in ['resp', 'coag', 'liver', 'cardio', 'neuro', 'renal']" :key="o" :label="sofaLabels[o]">
            <el-input-number v-model="scoreForm.detail[o + '_score']" :min="0" :max="4" />
          </el-form-item>
        </template>
        <template v-else-if="scoreForm.score_type === 'aldrete'">
          <p class="sofa-hint">五项各 0-2 分（活动/呼吸/循环/意识/肤色），≥9 可转出</p>
          <el-form-item v-for="o in ['activity', 'respiration', 'circulation', 'consciousness', 'color']" :key="o" :label="aldreteLabels[o]">
            <el-input-number v-model="scoreForm.detail[o + '_score']" :min="0" :max="2" />
          </el-form-item>
        </template>
        <template v-else-if="scoreForm.score_type === 'steward'">
          <p class="sofa-hint">三项各 0-2 分（清醒程度/呼吸道通畅/肢体活动），≥4 可转出</p>
          <el-form-item v-for="o in ['wake', 'airway', 'motor']" :key="o" :label="stewardLabels[o]">
            <el-input-number v-model="scoreForm.detail[o + '_score']" :min="0" :max="2" />
          </el-form-item>
        </template>
      </el-form>
      <template #footer><el-button @click="scoreDialogVisible = false">取消</el-button><el-button type="primary" @click="handleCreateScore">提交评分</el-button></template>
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

export default {
  name: "OpsExtension",
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
      scoreDialogVisible: false, scoreForm: { score_type: "gcs", scene: "icu", detail: {} },
      sofaLabels: { resp: "呼吸", coag: "凝血", liver: "肝脏", cardio: "心血管", neuro: "神经", renal: "肾脏" },
      aldreteLabels: { activity: "活动", respiration: "呼吸", circulation: "循环", consciousness: "意识", color: "肤色" },
      stewardLabels: { wake: "清醒程度", airway: "气道通畅", motor: "肢体活动" },
      pathwayLoading: false, pathwayData: [], pathwayQuery: { status: null },
      pathwayDialogVisible: false, pathwayForm: { total_items: 0 },
    };
  },
  computed: {
    cssdNextStates() {
      if (!this.cssdCurrentItem) return [];
      return (this.cssdFlow[this.cssdCurrentItem.status] || []).map((s) => ({ value: s, label: this.cssdStatus[s] }));
    },
    pivasNextLabel() {
      const labels = { 0: "已排药贴签", 1: "配置中", 2: "成品核对", 3: "已配送", 4: "病区签收" };
      return labels[this.pivasCurrent.status] || "";
    },
  },
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
    async loadScores() {
      this.scoreLoading = true;
      try { const res = await getIcuScoreList(this.scoreQuery); this.scoreData = res.data || []; } finally { this.scoreLoading = false; }
    },
    async handleCreateScore() {
      const res = await createIcuScore(this.scoreForm);
      if (res.code === 200) {
        ElMessage.success(`评分完成：${res.data.total_score} 分 — ${res.data.interpretation}`);
        this.scoreDialogVisible = false;
        this.scoreForm = { score_type: "gcs", scene: "icu", detail: {} };
        this.loadScores();
      } else ElMessage.error(res.msg);
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
