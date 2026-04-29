import request from "@/utils/request";

export function getChargeList() {
  return request({ url: "chargeManagement/getList", method: "get" });
}

export function commitCharge(data) {
  return request({ url: "chargeManagement/charge", method: "post", data });
}

export function refundCharge(data) {
  return request({ url: "chargeManagement/refund", method: "post", data });
}

export function getInvoiceList() {
  return request({ url: "invoice/getList", method: "get" });
}

export function createInvoice(data) {
  return request({ url: "invoice/create", method: "post", data });
}

export function printInvoice(data) {
  return request({ url: "invoice/print", method: "post", data });
}
