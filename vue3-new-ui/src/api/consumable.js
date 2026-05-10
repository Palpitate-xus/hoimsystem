import request from "@/utils/request";

export function getConsumableList(keyword = "", page, page_size) {
  return request({ url: "consumable/getList", method: "get", params: { keyword, page, page_size } });
}

export function createConsumable(data) {
  return request({ url: "consumable/create", method: "post", data });
}

export function updateConsumable(data) {
  return request({ url: "consumable/update", method: "post", data });
}

export function deleteConsumable(data) {
  return request({ url: "consumable/delete", method: "post", data });
}
