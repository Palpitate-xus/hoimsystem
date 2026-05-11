import request from "@/utils/request";

export function getExamPackageList(keyword = "") {
  return request({ url: "exam/package/getList", method: "get", params: { keyword } });
}

export function createExamPackage(data) {
  return request({ url: "exam/package/create", method: "post", data });
}

export function updateExamPackage(data) {
  return request({ url: "exam/package/update", method: "post", data });
}

export function deleteExamPackage(data) {
  return request({ url: "exam/package/delete", method: "post", data });
}

export function getExamItemList(keyword = "") {
  return request({ url: "exam/item/getList", method: "get", params: { keyword } });
}

export function createExamItem(data) {
  return request({ url: "exam/item/create", method: "post", data });
}

export function updateExamItem(data) {
  return request({ url: "exam/item/update", method: "post", data });
}

export function deleteExamItem(data) {
  return request({ url: "exam/item/delete", method: "post", data });
}

export function getExamAppointmentList(keyword = "", status = "") {
  return request({ url: "exam/appointment/getList", method: "get", params: { keyword, status } });
}

export function createExamAppointment(data) {
  return request({ url: "exam/appointment/create", method: "post", data });
}

export function updateAppointmentStatus(data) {
  return request({ url: "exam/appointment/updateStatus", method: "post", data });
}

export function getExamRecordList(keyword = "") {
  return request({ url: "exam/record/getList", method: "get", params: { keyword } });
}

export function createExamRecord(data) {
  return request({ url: "exam/record/create", method: "post", data });
}

export function updateExamRecord(data) {
  return request({ url: "exam/record/update", method: "post", data });
}

export function completeExamRecord(data) {
  return request({ url: "exam/record/complete", method: "post", data });
}

export function getExamResultList(keyword = "") {
  return request({ url: "exam/result/getList", method: "get", params: { keyword } });
}

export function createExamResult(data) {
  return request({ url: "exam/result/create", method: "post", data });
}

export function getExamReportDetail(data) {
  return request({ url: "exam/report/detail", method: "post", data });
}
