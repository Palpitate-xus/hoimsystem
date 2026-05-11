import request from "@/utils/request";

export function getAdmissionList(params) {
  return request({
    url: "/admission/getList",
    method: "get",
    params,
  });
}

export function createAdmission(data) {
  return request({
    url: "/admission/create",
    method: "post",
    data,
  });
}

export function getAdmissionDetail(params) {
  return request({
    url: "/admission/detail",
    method: "get",
    params,
  });
}

export function updateAdmission(data) {
  return request({
    url: "/admission/update",
    method: "post",
    data,
  });
}

export function getAvailableBeds(params) {
  return request({
    url: "/admission/getAvailableBeds",
    method: "get",
    params,
  });
}

export function getInpatientList(params) {
  return request({
    url: "/admission/getInpatientList",
    method: "get",
    params,
  });
}
