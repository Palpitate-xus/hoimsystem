import request from "@/utils/request";

export function getLogList(data) {
  return request({ url: "log/getList", method: "post", data });
}

export function getDictList(data) {
  return request({ url: "dict/getList", method: "post", data });
}

export function createDict(data) {
  return request({ url: "dict/create", method: "post", data });
}

export function updateDict(data) {
  return request({ url: "dict/update", method: "post", data });
}

export function deleteDict(data) {
  return request({ url: "dict/delete", method: "post", data });
}

export function getConfigList(keyword = "") {
  return request({ url: "config/getList", method: "get", params: { keyword } });
}

export function updateConfig(data) {
  return request({ url: "config/update", method: "post", data });
}

export function getMessageList(keyword = "") {
  return request({ url: "message/getList", method: "get", params: { keyword } });
}

export function readMessage(data) {
  return request({ url: "message/read", method: "post", data });
}

export function sendMessage(data) {
  return request({ url: "message/send", method: "post", data });
}
