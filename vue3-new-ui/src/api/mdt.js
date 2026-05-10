import request from "@/utils/request";

export function createMdt(data) {
  return request({ url: "mdt/create", method: "post", data });
}
export function getMdtList() {
  return request({ url: "mdt/getList", method: "get" });
}
export function updateMdt(data) {
  return request({ url: "mdt/update", method: "post", data });
}
