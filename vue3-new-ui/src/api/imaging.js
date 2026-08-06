import request from "@/utils/request";

export function getImagingOrders(params = {}) {
  return request({ url: "imaging/order/list", method: "get", params });
}

export function createImagingOrder(data) {
  return request({ url: "imaging/order/create", method: "post", data });
}

export function updateImagingOrderStatus(data) {
  return request({ url: "imaging/order/status", method: "post", data });
}

export function getImagingReports() {
  return request({ url: "imaging/report/list", method: "get" });
}

export function saveImagingReport(data) {
  return request({ url: "imaging/report/save", method: "post", data });
}

export function submitImagingReport(data) {
  return request({ url: "imaging/report/submit", method: "post", data });
}

export function getImagingTemplates(modality = "") {
  return request({ url: "imaging/template/list", method: "get", params: { modality } });
}

export function saveImagingTemplate(data) {
  return request({ url: "imaging/template/save", method: "post", data });
}

export function getImagingViewer(orderId) {
  return request({ url: `imaging/viewer/${orderId}`, method: "get" });
}
