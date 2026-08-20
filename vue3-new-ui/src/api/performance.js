import request from "@/utils/request";

export function getPerformanceList(params) {
  return request({ url: "performance/getList", method: "get", params });
}
export function createPerformance(data) {
  return request({ url: "performance/create", method: "post", data });
}
export function updatePerformance(data) {
  return request({ url: "performance/update", method: "post", data });
}
export function submitPerformance(data) {
  return request({ url: "performance/submit", method: "post", data });
}
export function auditPerformance(data) {
  return request({ url: "performance/audit", method: "post", data });
}
