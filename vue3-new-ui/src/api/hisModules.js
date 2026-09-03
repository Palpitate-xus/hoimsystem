import request from "@/utils/request";

// 审方规则引擎
export function getRxRuleList(params) {
  return request({ url: "rxReviewRule/getList", method: "get", params });
}
export function createRxRule(data) {
  return request({ url: "rxReviewRule/create", method: "post", data });
}
export function updateRxRule(data) {
  return request({ url: "rxReviewRule/update", method: "post", data });
}
export function deleteRxRule(data) {
  return request({ url: "rxReviewRule/delete", method: "post", data });
}
export function rxCheck(data) {
  return request({ url: "rxReviewRule/check", method: "post", data });
}
export function getClinicalProfile(patientId) {
  return request({ url: `clinicalProfile/${patientId}`, method: "get" });
}
export function saveClinicalProfile(patientId, data) {
  return request({ url: `clinicalProfile/${patientId}`, method: "post", data });
}

// 医保目录对照
export function getInsuranceCatalogList(params) {
  return request({ url: "insuranceCatalog/getList", method: "get", params });
}
export function createInsuranceMapping(data) {
  return request({ url: "insuranceCatalog/create", method: "post", data });
}
export function updateInsuranceMapping(data) {
  return request({ url: "insuranceCatalog/update", method: "post", data });
}
export function deleteInsuranceMapping(data) {
  return request({ url: "insuranceCatalog/delete", method: "post", data });
}
export function importInsuranceMappings(data) {
  return request({ url: "insuranceCatalog/import", method: "post", data });
}
export function downloadInsuranceTemplate() {
  return request({ url: "insuranceCatalog/template", method: "get", responseType: "blob" });
}

// MDRO 隔离
export function getMdroList(params) {
  return request({ url: "mdro/getList", method: "get", params });
}
export function createMdro(data) {
  return request({ url: "mdro/create", method: "post", data });
}
export function releaseMdro(data) {
  return request({ url: "mdro/release", method: "post", data });
}

// 手卫生
export function getHandHygieneList(params) {
  return request({ url: "handHygiene/getList", method: "get", params });
}
export function createHandHygiene(data) {
  return request({ url: "handHygiene/create", method: "post", data });
}

// 传染病报告卡
export function getNotifiableList(params) {
  return request({ url: "notifiableDisease/getList", method: "get", params });
}
export function createNotifiable(data) {
  return request({ url: "notifiableDisease/create", method: "post", data });
}
export function submitNotifiable(data) {
  return request({ url: "notifiableDisease/submit", method: "post", data });
}
export function auditNotifiable(data) {
  return request({ url: "notifiableDisease/audit", method: "post", data });
}
export function correctNotifiable(data) {
  return request({ url: "notifiableDisease/correct", method: "post", data });
}

// RCA
export function getRcaList(params) {
  return request({ url: "rca/getList", method: "get", params });
}
export function createRca(data) {
  return request({ url: "rca/create", method: "post", data });
}
export function advanceRca(data) {
  return request({ url: "rca/advance", method: "post", data });
}

// HQMS
export function getHqmsList(params) {
  return request({ url: "hqms/getList", method: "get", params });
}
export function createHqms(data) {
  return request({ url: "hqms/create", method: "post", data });
}
export function importHqms(data) {
  return request({ url: "hqms/batchImport", method: "post", data });
}
export function submitHqms(data) {
  return request({ url: "hqms/submit", method: "post", data });
}

// CSSD
export function getCssdList(params) {
  return request({ url: "cssd/getList", method: "get", params });
}
export function createCssd(data) {
  return request({ url: "cssd/create", method: "post", data });
}
export function transitionCssd(data) {
  return request({ url: "cssd/transition", method: "post", data });
}

// PIVAS
export function getPivasList(params) {
  return request({ url: "pivas/getList", method: "get", params });
}
export function createPivas(data) {
  return request({ url: "pivas/create", method: "post", data });
}
export function transitionPivas(data) {
  return request({ url: "pivas/transition", method: "post", data });
}

// ICU/PACU 评分
export function getIcuScoreList(params) {
  return request({ url: "icuScore/getList", method: "get", params });
}
export function createIcuScore(data) {
  return request({ url: "icuScore/create", method: "post", data });
}

// 临床路径入组
export function getPathwayEnrollmentList(params) {
  return request({ url: "pathwayEnrollment/getList", method: "get", params });
}
export function enrollPathway(data) {
  return request({ url: "pathwayEnrollment/enroll", method: "post", data });
}
export function recordPathwayProgress(data) {
  return request({ url: "pathwayEnrollment/record", method: "post", data });
}
export function recordPathwayVariation(data) {
  return request({ url: "pathwayEnrollment/variation", method: "post", data });
}
export function exitPathway(data) {
  return request({ url: "pathwayEnrollment/exit", method: "post", data });
}
