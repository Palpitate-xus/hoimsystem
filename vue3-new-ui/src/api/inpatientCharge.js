import request from "@/utils/request";

export function getInpatientChargeList(params) {
  return request({
    url: "/inpatientCharge/getList",
    method: "get",
    params,
  });
}

export function getDailyBill(params) {
  return request({
    url: "/inpatientCharge/getDailyBill",
    method: "get",
    params,
  });
}

export function settleCharges(data) {
  return request({
    url: "/inpatientCharge/settle",
    method: "post",
    data,
  });
}

export function refundCharge(data) {
  return request({
    url: "/inpatientCharge/refund",
    method: "post",
    data,
  });
}

export function getChargeSummary() {
  return request({
    url: "/inpatientCharge/getSummary",
    method: "get",
  });
}
