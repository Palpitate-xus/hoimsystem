import request from "@/utils/request";

export function getChargeList(keyword = "") {
  return request({ url: "chargeManagement/getList", method: "get", params: { keyword } });
}

export function commitCharge(data) {
  return request({ url: "chargeManagement/charge", method: "post", data });
}

export function refundCharge(data) {
  return request({ url: "chargeManagement/refund", method: "post", data });
}

export function getInvoiceList(keyword = "") {
  return request({ url: "invoice/getList", method: "get", params: { keyword } });
}

export function createInvoice(data) {
  return request({ url: "invoice/create", method: "post", data });
}

export function printInvoice(data) {
  return request({ url: "invoice/print", method: "post", data });
}
