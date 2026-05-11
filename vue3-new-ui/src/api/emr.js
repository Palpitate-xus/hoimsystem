import request from "@/utils/request";

// 病历模板
export function getEmrTemplateList(params) {
  return request({ url: "/emrTemplate/getList", method: "get", params });
}
export function createEmrTemplate(data) {
  return request({ url: "/emrTemplate/create", method: "post", data });
}
export function updateEmrTemplate(data) {
  return request({ url: "/emrTemplate/update", method: "post", data });
}
export function deleteEmrTemplate(data) {
  return request({ url: "/emrTemplate/delete", method: "post", data });
}
export function getEmrTemplateDetail(params) {
  return request({ url: "/emrTemplate/detail", method: "get", params });
}

// 结构化病历
export function getStructuredRecordList(params) {
  return request({ url: "/structuredMedicalRecord/getList", method: "get", params });
}
export function createStructuredRecord(data) {
  return request({ url: "/structuredMedicalRecord/create", method: "post", data });
}
export function getStructuredRecordDetail(params) {
  return request({ url: "/structuredMedicalRecord/detail", method: "get", params });
}
export function updateStructuredRecord(data) {
  return request({ url: "/structuredMedicalRecord/update", method: "post", data });
}
export function signMedicalRecord(data) {
  return request({ url: "/structuredMedicalRecord/sign", method: "post", data });
}
export function deleteStructuredRecord(data) {
  return request({ url: "/structuredMedicalRecord/delete", method: "post", data });
}

// 病程记录
export function getProgressNoteList(params) {
  return request({ url: "/progressNote/getList", method: "get", params });
}
export function createProgressNote(data) {
  return request({ url: "/progressNote/create", method: "post", data });
}
export function deleteProgressNote(data) {
  return request({ url: "/progressNote/delete", method: "post", data });
}

// 查房记录
export function getWardRoundList(params) {
  return request({ url: "/wardRound/getList", method: "get", params });
}
export function createWardRound(data) {
  return request({ url: "/wardRound/create", method: "post", data });
}
export function deleteWardRound(data) {
  return request({ url: "/wardRound/delete", method: "post", data });
}

// 病历质控
export function getQualityList(params) {
  return request({ url: "/medicalRecordQuality/getList", method: "get", params });
}
export function qualityCheck(data) {
  return request({ url: "/medicalRecordQuality/check", method: "post", data });
}
export function getQualitySummary() {
  return request({ url: "/medicalRecordQuality/summary", method: "get" });
}
