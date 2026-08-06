import request from "@/utils/request";

export function getDoctorScheduleList(keyword = "") {
  return request({ url: "doctorScheduleManagement/getList", method: "get", params: { keyword } });
}

export function registerDoctorSchedule(data) {
  return request({ url: "doctorScheduleManagement/register", method: "post", data });
}

export function createMedicalRecord(data) {
  return request({ url: "medicalRecord/create", method: "post", data });
}

export function updateMedicalRecord(data) {
  return request({ url: "medicalRecord/update", method: "post", data });
}

export function getMedicalRecordList(keyword = "") {
  return request({ url: "medicalRecord/getList", method: "get", params: { keyword } });
}

export function getMedicalRecordDetail(data) {
  return request({ url: "medicalRecord/detail", method: "post", data });
}

export function getPrescriptionList(keyword = "") {
  return request({ url: "prescriptionManagement/getList", method: "get", params: { keyword } });
}

export function createPrescription(data) {
  return request({ url: "prescriptionManagement/create", method: "post", data });
}

export function cancelPrescription(data) {
  return request({ url: "prescriptionManagement/cancel", method: "post", data });
}

export function getPrescriptionTemplates() {
  return request({ url: "prescriptionTemplate/list", method: "get" });
}

export function createPrescriptionTemplate(data) {
  return request({ url: "prescriptionTemplate/create", method: "post", data });
}

export function updatePrescriptionTemplate(data) {
  return request({ url: "prescriptionTemplate/update", method: "put", data });
}

export function deletePrescriptionTemplate(data) {
  return request({ url: "prescriptionTemplate/delete", method: "post", data });
}

export function applyPrescriptionTemplate(data) {
  return request({ url: "prescriptionTemplate/apply", method: "post", data });
}

export function getDiagnosisTemplates() {
  return request({ url: "diagnosisTemplate/list", method: "get" });
}

export function createDiagnosisTemplate(data) {
  return request({ url: "diagnosisTemplate/create", method: "post", data });
}

export function updateDiagnosisTemplate(data) {
  return request({ url: "diagnosisTemplate/update", method: "put", data });
}

export function deleteDiagnosisTemplate(data) {
  return request({ url: "diagnosisTemplate/delete", method: "post", data });
}

export function createLabOrder(data) {
  return request({ url: "labOrder/create", method: "post", data });
}

export function getLabOrderList(keyword = "") {
  return request({ url: "labOrder/getList", method: "get", params: { keyword } });
}

export function attendanceCheckIn() {
  return request({ url: "attendance/checkIn", method: "post" });
}

export function attendanceCheckOut() {
  return request({ url: "attendance/checkOut", method: "post" });
}

export function getAttendanceList(params) {
  return request({ url: "attendance/getList", method: "get", params });
}
