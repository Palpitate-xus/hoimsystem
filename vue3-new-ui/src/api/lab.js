import request from "@/utils/request";

export function getPendingLabOrders() {
  return request({ url: "labResult/getPending", method: "get" });
}

export function getLabResultList() {
  return request({ url: "labResult/getList", method: "get" });
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
