import request from "@/utils/request";

export function createAdverseEvent(data) {
  return request({ url: "adverseEvent/create", method: "post", data });
}
export function getAdverseEventList() {
  return request({ url: "adverseEvent/getList", method: "get" });
}
export function updateEventStatus(data) {
  return request({ url: "adverseEvent/updateStatus", method: "post", data });
}
