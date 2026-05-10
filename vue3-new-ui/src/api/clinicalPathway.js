import request from "@/utils/request";

export function createPathway(data) {
  return request({ url: "clinicalPathway/create", method: "post", data });
}
export function getPathwayList() {
  return request({ url: "clinicalPathway/getList", method: "get" });
}
export function updatePathway(data) {
  return request({ url: "clinicalPathway/update", method: "post", data });
}
export function deletePathway(data) {
  return request({ url: "clinicalPathway/delete", method: "post", data });
}
