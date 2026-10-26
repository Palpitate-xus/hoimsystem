// Navigation metadata only. The existing panes keep their own permission and loading guards.
export const AI_MANAGEMENT_GROUPS = Object.freeze([
  { key: "features_models", label: "功能与模型" },
  { key: "knowledge_data", label: "知识与数据" },
  { key: "tasks_usage", label: "任务与用量" },
  { key: "permissions_audit", label: "权限与审计" },
]);

export const AI_MANAGEMENT_ENTRIES = Object.freeze([
  {
    "name": "features",
    "label": "能力与启用",
    "group": "features_models"
  },
  {
    "name": "technical_tasks",
    "label": "全局技术任务",
    "group": "tasks_usage"
  },
  {
    "name": "providers",
    "label": "模型服务",
    "group": "features_models"
  },
  {
    "name": "knowledge",
    "label": "知识审核",
    "group": "knowledge_data"
  },
  {
    "name": "forecast_sources",
    "label": "挂号预测来源",
    "group": "knowledge_data"
  },
  {
    "name": "observation_windows",
    "label": "住院观测窗",
    "group": "knowledge_data"
  },
  {
    "name": "laboratory_mappings",
    "label": "检验项目与来源",
    "group": "knowledge_data"
  },
  {
    "name": "risk_rules",
    "label": "风险规则与评估",
    "group": "knowledge_data"
  },
  {
    "name": "roster_plans",
    "label": "受审排班计划治理",
    "group": "knowledge_data"
  },
  {
    "name": "roster_sources",
    "label": "排班人员来源治理",
    "group": "knowledge_data"
  },
  {
    "name": "bed_series",
    "label": "床位完整序列治理",
    "group": "knowledge_data"
  },
  {
    "name": "bed_sources",
    "label": "床位原来源治理",
    "group": "knowledge_data"
  },
  {
    "name": "surgery_sources",
    "label": "手术原资料与资源治理",
    "group": "knowledge_data"
  },
  {
    "name": "supply_sources",
    "label": "物资原计量与每日原量治理",
    "group": "knowledge_data"
  },
  {
    "name": "supply_series",
    "label": "完整物资原量序列治理",
    "group": "knowledge_data"
  },
  {
    "name": "inventory_sources",
    "label": "库存原观察与采购候选治理",
    "group": "knowledge_data"
  },
  {
    "name": "inventory_scenarios",
    "label": "完整库存候选场景治理",
    "group": "knowledge_data"
  },
  {
    "name": "document_evidence",
    "label": "指南原文与摘录治理",
    "group": "knowledge_data",
    "guard": "forecast"
  },
  {
    "name": "drug_label_sources",
    "label": "说明书原文与独立签署治理",
    "group": "knowledge_data",
    "guard": "drug_labels"
  },
  {
    "name": "document_change",
    "label": "双原文范围与规则关联",
    "group": "knowledge_data",
    "guard": "forecast"
  },
  {
    "name": "deidentification_sources",
    "label": "病例去标识来源与人工复核治理",
    "group": "knowledge_data",
    "guard": "research"
  },
  {
    "name": "operations_support_sources",
    "label": "运维受审材料与独立发布治理",
    "group": "knowledge_data",
    "guard": "research"
  },
  {
    "name": "clinical_training_sources",
    "label": "合成教学课程与独立复核治理",
    "group": "knowledge_data",
    "guard": "forecast"
  },
  {
    "name": "research_cohort_sources",
    "label": "科研来源治理",
    "group": "knowledge_data",
    "guard": "research"
  },
  {
    "name": "research_variable_sources",
    "label": "科研变量字典与完整批次治理",
    "group": "knowledge_data",
    "guard": "research"
  },
  {
    "name": "coding_evidence",
    "label": "病案编码证据与本地规则治理",
    "group": "knowledge_data",
    "guard": "forecast"
  },
  {
    "name": "charge_sources",
    "label": "完整住院账目来源治理",
    "group": "knowledge_data",
    "guard": "forecast"
  },
  {
    "name": "rca_evidence",
    "label": "完整事件RCA来源治理",
    "group": "knowledge_data",
    "guard": "forecast"
  },
  {
    "name": "satisfaction_sources",
    "label": "完整评价与人工摘录治理",
    "group": "knowledge_data",
    "guard": "forecast"
  },
  {
    "name": "infection_sources",
    "label": "有限病例来源与本地统计治理",
    "group": "knowledge_data",
    "guard": "forecast"
  },
  {
    "name": "surgery_scenarios",
    "label": "完整手术排程场景治理",
    "group": "knowledge_data"
  },
  {
    "name": "sofa",
    "label": "SOFA独立规则与全院评估",
    "group": "knowledge_data"
  },
  {
    "name": "organ_support",
    "label": "器官支持来源与映射",
    "group": "knowledge_data"
  },
  {
    "name": "audio",
    "label": "录音治理",
    "group": "knowledge_data"
  },
  {
    "name": "images",
    "label": "影像原文件",
    "group": "knowledge_data"
  },
  {
    "name": "ecg",
    "label": "心电原文件",
    "group": "knowledge_data"
  },
  {
    "name": "grants",
    "label": "患者访问授权",
    "group": "permissions_audit"
  },
  {
    "name": "audit",
    "label": "配置审计",
    "group": "permissions_audit"
  },
  {
    "name": "runs",
    "label": "任务与反馈",
    "group": "tasks_usage"
  },
  {
    "name": "review_excerpts",
    "label": "反馈脱敏审核",
    "group": "permissions_audit"
  },
  {
    "name": "usage",
    "label": "调用统计",
    "group": "tasks_usage"
  }
]);
