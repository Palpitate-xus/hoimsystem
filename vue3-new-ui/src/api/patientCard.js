import request from "@/utils/request";

export function getPatientCards(keyword = "") {
  return request({ url: "patientCard/list", method: "get", params: { keyword } });
}
export function issuePatientCard(data) {
  return request({ url: "patientCard/issue", method: "post", data });
}
export function reportPatientCardLost(data) {
  return request({ url: "patientCard/lost", method: "post", data });
}
export function cancelPatientCard(data) {
  return request({ url: "patientCard/cancel", method: "post", data });
}
