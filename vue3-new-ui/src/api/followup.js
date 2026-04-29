import request from "@/utils/request";

export function createFollowUpAppointment(data) {
  return request({ url: "followUpAppointment/create", method: "post", data });
}

export function createFollowUpPlan(data) {
  return request({ url: "followUp/createPlan", method: "post", data });
}

export function getFollowUpList() {
  return request({ url: "followUp/getList", method: "get" });
}

export function recordFollowUp(data) {
  return request({ url: "followUp/record", method: "post", data });
}
