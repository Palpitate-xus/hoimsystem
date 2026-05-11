import request from "@/utils/request";

export function getWardList(params) {
  return request({
    url: "/ward/getList",
    method: "get",
    params,
  });
}

export function createWard(data) {
  return request({
    url: "/ward/create",
    method: "post",
    data,
  });
}

export function updateWard(data) {
  return request({
    url: "/ward/update",
    method: "post",
    data,
  });
}

export function deleteWard(data) {
  return request({
    url: "/ward/delete",
    method: "post",
    data,
  });
}

export function getBedList(params) {
  return request({
    url: "/bed/getList",
    method: "get",
    params,
  });
}

export function createBed(data) {
  return request({
    url: "/bed/create",
    method: "post",
    data,
  });
}

export function updateBed(data) {
  return request({
    url: "/bed/update",
    method: "post",
    data,
  });
}

export function deleteBed(data) {
  return request({
    url: "/bed/delete",
    method: "post",
    data,
  });
}
