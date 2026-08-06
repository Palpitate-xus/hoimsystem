import request from "@/utils/request";

export function getAllergyList(patientId) {
  return request({ url: "/allergy/list", method: "get", params: patientId ? { patient_id: patientId } : {} });
}

export function createAllergy(data) { return request({ url: "/allergy/create", method: "post", data }); }
export function updateAllergy(data) { return request({ url: "/allergy/update", method: "put", data }); }
export function disableAllergy(data) { return request({ url: "/allergy/disable", method: "post", data }); }
