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

export function windowRegistration(data) {
  return request({ url: "windowRegistration/create", method: "post", data });
}

export function windowCancelRegistration(data) {
  return request({ url: "windowRegistration/cancel", method: "post", data });
}

export function dailySettlement(data) {
  return request({ url: "dailySettlement/report", method: "post", data });
}

export function createPayment(data) {
  return request({ url: "payment/create", method: "post", data });
}

export function queryPayment(paymentNo) {
  return request({ url: `payment/query/${paymentNo}`, method: "get" });
}

export function mockPaymentNotify(data) {
  return request({ url: "payment/mockNotify", method: "post", data });
}

export function getPaymentList(keyword = "") {
  return request({ url: "payment/getList", method: "get", params: { keyword } });
}
