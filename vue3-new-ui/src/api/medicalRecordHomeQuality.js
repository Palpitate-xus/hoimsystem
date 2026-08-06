import request from "@/utils/request";

export function getMedicalRecordHomeQualityList(params) { return request({ url: "/medicalRecordHomeQuality/list", method: "get", params }); }
export function checkMedicalRecordHomeQuality(data) { return request({ url: "/medicalRecordHomeQuality/check", method: "post", data }); }
export function getMedicalRecordHomeQualitySummary() { return request({ url: "/medicalRecordHomeQuality/summary", method: "get" }); }
