import request from "@/utils/request";

export function getPrepaidBalance(identity) {
  return request({ url: "prepaid/getBalance", method: "get", params: { identity } });
}
export function prepaidRecharge(data) {
  return request({ url: "prepaid/recharge", method: "post", data });
}
export function prepaidDeduct(data) {
  return request({ url: "prepaid/deduct", method: "post", data });
}
