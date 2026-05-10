import request from "@/utils/request";

export function getQueueList(keyword = "") {
  return request({ url: "queue/getList", method: "get", params: { keyword } });
}

export function callNext(data) {
  return request({ url: "queue/callNext", method: "post", data });
}

export function passQueue(data) {
  return request({ url: "queue/pass", method: "post", data });
}

export function skipQueue(data) {
  return request({ url: "queue/skip", method: "post", data });
}

export function markEmergency(data) {
  return request({ url: "queue/emergency", method: "post", data });
}

export function reorderQueue(data) {
  return request({ url: "queue/reorder", method: "post", data });
}

export function getPatrolList(keyword = "") {
  return request({ url: "patrol/getList", method: "get", params: { keyword } });
}

export function createPatrolRecord(data) {
  return request({ url: "patrol/create", method: "post", data });
}
