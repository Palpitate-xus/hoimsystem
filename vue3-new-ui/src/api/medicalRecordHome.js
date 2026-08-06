import request from "@/utils/request";

export function getMedicalRecordHomeAdmissions() {
  return request({ url: "/medicalRecordHome/admissions", method: "get" });
}

export function getMedicalRecordHomeList(params) {
  return request({ url: "/medicalRecordHome/list", method: "get", params });
}

export function createMedicalRecordHome(data) {
  return request({ url: "/medicalRecordHome/create", method: "post", data });
}

export function updateMedicalRecordHome(data) {
  return request({ url: "/medicalRecordHome/update", method: "put", data });
}

export function submitMedicalRecordHome(data) {
  return request({ url: "/medicalRecordHome/submit", method: "post", data });
}
