import request from "@/utils/request";

export function getLabQcList(params) { return request({ url: "/labQc/list", method: "get", params }); }
export function createLabQc(data) { return request({ url: "/labQc/create", method: "post", data }); }
export function getLabQcSummary() { return request({ url: "/labQc/summary", method: "get" }); }
