import request from "@/utils/request";

export function getNursingRecordList(params) {
  return request({
    url: "/nursingRecord/getList",
    method: "get",
    params,
  });
}

export function createNursingRecord(data) {
  return request({
    url: "/nursingRecord/create",
    method: "post",
    data,
  });
}

export function deleteNursingRecord(data) {
  return request({
    url: "/nursingRecord/delete",
    method: "post",
    data,
  });
}

export function getTemperatureRecordList(params) {
  return request({
    url: "/temperatureRecord/getList",
    method: "get",
    params,
  });
}

export function createTemperatureRecord(data) {
  return request({
    url: "/temperatureRecord/create",
    method: "post",
    data,
  });
}

export function deleteTemperatureRecord(data) {
  return request({
    url: "/temperatureRecord/delete",
    method: "post",
    data,
  });
}
