import request from "@/utils/request";

export function createPurchase(data) {
  return request({ url: "purchase/create", method: "post", data });
}

export function getPurchaseList(params) {
  return request({ url: "purchase/getList", method: "get", params });
}

export function approvePurchase(data) {
  return request({ url: "purchase/approve", method: "post", data });
}

export function storagePurchase(data) {
  return request({ url: "purchase/storage", method: "post", data });
}

export function cancelPurchase(data) {
  return request({ url: "purchase/cancel", method: "post", data });
}
