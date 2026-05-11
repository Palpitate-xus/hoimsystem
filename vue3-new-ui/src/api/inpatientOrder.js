import request from "@/utils/request";

export function getInpatientOrderList(params) {
  return request({
    url: "/inpatientOrder/getList",
    method: "get",
    params,
  });
}

export function createInpatientOrder(data) {
  return request({
    url: "/inpatientOrder/create",
    method: "post",
    data,
  });
}

export function auditInpatientOrder(data) {
  return request({
    url: "/inpatientOrder/audit",
    method: "post",
    data,
  });
}

export function stopInpatientOrder(data) {
  return request({
    url: "/inpatientOrder/stop",
    method: "post",
    data,
  });
}

export function cancelInpatientOrder(data) {
  return request({
    url: "/inpatientOrder/cancel",
    method: "post",
    data,
  });
}

export function getExecutionList(params) {
  return request({
    url: "/inpatientOrder/getExecutionList",
    method: "get",
    params,
  });
}

export function executeOrder(data) {
  return request({
    url: "/inpatientOrder/execute",
    method: "post",
    data,
  });
}
