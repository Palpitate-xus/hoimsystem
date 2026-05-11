import request from "@/utils/request";

export function doDischarge(data) {
  return request({
    url: "/discharge/doDischarge",
    method: "post",
    data,
  });
}

export function getDischargeSummary(params) {
  return request({
    url: "/discharge/getSummary",
    method: "get",
    params,
  });
}

export function updateDischargeSummary(data) {
  return request({
    url: "/discharge/updateSummary",
    method: "post",
    data,
  });
}

export function getDischargedList(params) {
  return request({
    url: "/discharge/getDischargedList",
    method: "get",
    params,
  });
}
