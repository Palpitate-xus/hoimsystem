import request from "@/utils/request";

export function getVitalSignList() {
  return request({ url: "vitalSign/getList", method: "get" });
}

export function createVitalSign(data) {
  return request({ url: "vitalSign/create", method: "post", data });
}
