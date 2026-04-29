import request from "@/utils/request";

export function getDoctorScheduleList() {
  return request({ url: "doctorScheduleManagement/getList", method: "get" });
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

export function getMedicalRecordList() {
  return request({ url: "medicalRecord/getList", method: "get" });
}

export function getMedicalRecordDetail(data) {
  return request({ url: "medicalRecord/detail", method: "post", data });
}

export function getPrescriptionList() {
  return request({ url: "prescriptionManagement/getList", method: "get" });
}

export function createPrescription(data) {
  return request({ url: "prescriptionManagement/create", method: "post", data });
}

export function cancelPrescription(data) {
  return request({ url: "prescriptionManagement/cancel", method: "post", data });
}

export function createLabOrder(data) {
  return request({ url: "labOrder/create", method: "post", data });
}

export function getLabOrderList() {
  return request({ url: "labOrder/getList", method: "get" });
}
