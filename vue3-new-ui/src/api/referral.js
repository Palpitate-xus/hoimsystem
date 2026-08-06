import request from "@/utils/request";

export function createReferral(data) {
  return request({ url: "referral/create", method: "post", data });
}
export function getReferralList() {
  return request({ url: "referral/getList", method: "get" });
}
export function updateReferralStatus(data) {
  return request({ url: "referral/updateStatus", method: "post", data });
}
export function getReferralApprovalList() {
  return request({ url: "referral/approvalList", method: "get" });
}
export function approveReferral(data) {
  return request({ url: "referral/approval", method: "post", data });
}
