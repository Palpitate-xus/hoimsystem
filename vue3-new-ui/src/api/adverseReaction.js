import request from "@/utils/request";

export function createAdverseReaction(data) {
  return request({ url: "adverseReaction/create", method: "post", data });
}
export function getAdverseReactionList() {
  return request({ url: "adverseReaction/getList", method: "get" });
}
export function updateAdrStatus(data) {
  return request({ url: "adverseReaction/updateStatus", method: "post", data });
}
