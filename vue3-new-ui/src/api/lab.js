import request from "@/utils/request";

export function getPendingLabOrders(keyword = "") {
  return request({ url: "labResult/getPending", method: "get", params: { keyword } });
}

export function getLabResultList(keyword = "") {
  return request({ url: "labResult/getList", method: "get", params: { keyword } });
}

export function getLabResultDetail(data) {
  return request({ url: "labResult/detail", method: "post", data });
}

export function createLabResult(data) {
  return request({ url: "labResult/create", method: "post", data });
}

export function auditLabResult(data) {
  return request({ url: "labResult/audit", method: "post", data });
}
