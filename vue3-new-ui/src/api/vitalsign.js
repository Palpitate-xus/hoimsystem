import request from "@/utils/request";

export function getVitalSignList(keyword = "") {
  return request({ url: "vitalSign/getList", method: "get", params: { keyword } });
}

export function createVitalSign(data) {
  return request({ url: "vitalSign/create", method: "post", data });
}
