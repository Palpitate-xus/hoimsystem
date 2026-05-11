import request from "@/utils/request";

export function getSurgeryApplicationList(params) {
  return request({ url: "/surgeryApplication/getList", method: "get", params });
}
export function createSurgeryApplication(data) {
  return request({ url: "/surgeryApplication/create", method: "post", data });
}
export function approveSurgeryApplication(data) {
  return request({ url: "/surgeryApplication/approve", method: "post", data });
}
export function cancelSurgeryApplication(data) {
  return request({ url: "/surgeryApplication/cancel", method: "post", data });
}

export function getSurgeryScheduleList(params) {
  return request({ url: "/surgerySchedule/getList", method: "get", params });
}
export function createSurgerySchedule(data) {
  return request({ url: "/surgerySchedule/create", method: "post", data });
}
export function startSurgery(data) {
  return request({ url: "/surgerySchedule/start", method: "post", data });
}
export function completeSurgery(data) {
  return request({ url: "/surgerySchedule/complete", method: "post", data });
}

export function getAnesthesiaRecordList(params) {
  return request({ url: "/anesthesiaRecord/getList", method: "get", params });
}
export function createAnesthesiaRecord(data) {
  return request({ url: "/anesthesiaRecord/create", method: "post", data });
}
