import request from "@/utils/request";

export function getQueueList() {
  return request({ url: "queue/getList", method: "get" });
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
