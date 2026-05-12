import request from "@/utils/request";

export function getExamPackageList(keyword = "") {
  return request({ url: "examPackage/getList", method: "get", params: { keyword } });
}

export function createExamPackage(data) {
  return request({ url: "examPackage/create", method: "post", data });
}

export function updateExamPackage(data) {
  return request({ url: "examPackage/update", method: "post", data });
}

export function deleteExamPackage(data) {
  return request({ url: "examPackage/delete", method: "post", data });
}

export function getExamItemList(keyword = "") {
  return request({ url: "examItem/getList", method: "get", params: { keyword } });
}

export function createExamItem(data) {
  return request({ url: "examItem/create", method: "post", data });
}

export function updateExamItem(data) {
  return request({ url: "examItem/update", method: "post", data });
}

export function deleteExamItem(data) {
  return request({ url: "examItem/delete", method: "post", data });
}

export function getExamAppointmentList(keyword = "", status = "") {
  return request({ url: "examAppointment/getList", method: "get", params: { keyword, status } });
}

export function createExamAppointment(data) {
  return request({ url: "examAppointment/create", method: "post", data });
}

export function updateAppointmentStatus(data) {
  return request({ url: "examAppointment/updateStatus", method: "post", data });
}

export function getExamRecordList(keyword = "") {
  return request({ url: "examRecord/getList", method: "get", params: { keyword } });
}

export function createExamRecord(data) {
  return request({ url: "examRecord/create", method: "post", data });
}

export function updateExamRecord(data) {
  return request({ url: "examRecord/update", method: "post", data });
}

export function completeExamRecord(data) {
  return request({ url: "examRecord/complete", method: "post", data });
}

export function getExamResultList(record_id = "") {
  return request({ url: "examResult/getList", method: "get", params: { record_id } });
}

export function createExamResult(data) {
  return request({ url: "examResult/create", method: "post", data });
}

export function getExamReportDetail(record_id = "") {
  return request({ url: "examReport/getDetail", method: "get", params: { record_id } });
}
