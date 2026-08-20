import request from "@/utils/request";

export function getHomeIcdBindings(params) {
  return request({ url: "homeIcd/getList", method: "get", params });
}
export function getUncodedHomes() {
  return request({ url: "homeIcd/uncoded", method: "get" });
}
export function bindHomeIcd(data) {
  return request({ url: "homeIcd/bind", method: "post", data });
}
export function unbindHomeIcd(data) {
  return request({ url: "homeIcd/unbind", method: "post", data });
}
export function setPrimaryIcd(data) {
  return request({ url: "homeIcd/setPrimary", method: "post", data });
}
export function getIcdStatistics() {
  return request({ url: "homeIcd/statistics", method: "get" });
}
export function getAntibioticCompliance(params) {
  return request({ url: "surgery/antibioticCompliance", method: "get", params });
}
