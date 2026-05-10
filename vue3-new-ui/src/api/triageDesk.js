import request from "@/utils/request";

export function createTriageRecord(data) {
  return request({ url: "triageDesk/create", method: "post", data });
}

export function getTriageList(params) {
  return request({ url: "triageDesk/getList", method: "get", params });
}

export function updateTriageStatus(data) {
  return request({ url: "triageDesk/updateStatus", method: "post", data });
}

export function updateTriageRecord(data) {
  return request({ url: "triageDesk/update", method: "post", data });
}
