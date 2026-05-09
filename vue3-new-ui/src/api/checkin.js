import request from "@/utils/request";

export function checkIn(data) {
  return request({ url: "checkIn/checkIn", method: "post", data });
}

export function getBreachList(patient_id) {
  return request({ url: "breach/getList", method: "get", params: { patient_id } });
}

export function checkSuspend(patient_id) {
  return request({ url: "breach/checkSuspend", method: "get", params: { patient_id } });
}
