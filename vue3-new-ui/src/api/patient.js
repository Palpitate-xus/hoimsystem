import request from "@/utils/request";

export function getAppointmentList() {
  return request({ url: "appointmentManagement/getList", method: "get" });
}

export function getAppointmentSchedules() {
  return request({ url: "appointmentManagement/appointmentList", method: "get" });
}

export function createAppointment(data) {
  return request({ url: "appointmentManagement/create", method: "post", data });
}

export function cancelAppointment(data) {
  return request({ url: "appointmentManagement/cancel", method: "post", data });
}

export function getRegistrationList() {
  return request({ url: "registrationManagement/getList", method: "get" });
}

export function getRegistrationSchedules() {
  return request({ url: "registrationManagement/registrationList", method: "get" });
}

export function createRegistration(data) {
  return request({ url: "registrationManagement/create", method: "post", data });
}

export function cancelRegistration(data) {
  return request({ url: "registrationManagement/cancel", method: "post", data });
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

export function getHealthProfile() {
  return request({ url: "healthRecord/getProfile", method: "get" });
}

export function getVisitRecords() {
  return request({ url: "healthRecord/getVisits", method: "get" });
}

export function createReview(data) {
  return request({ url: "review/create", method: "post", data });
}
