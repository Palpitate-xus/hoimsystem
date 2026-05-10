import request from "@/utils/request";
import { tokenName } from "@/config";

export async function login(data) {
  return request({
    url: "login",
    method: "post",
    data,
  });
}

export function getUserInfo(accessToken) {
  return request({
    url: "userInfo",
    method: "post",
    data: {
      [tokenName]: accessToken,
    },
  });
}

export function logout() {
  return request({
    url: "logout",
    method: "post",
  });
}

export function register(data) {
  return request({
    url: "register",
    method: "post",
    data,
  });
}

export function getPublicKey() {
  return request({
    url: "publicKey",
    method: "get",
  });
}

export function getUserList(params) {
  return request({ url: "user/getList", method: "get", params });
}

export function updateUserRole(data) {
  return request({ url: "user/updateRole", method: "post", data });
}

export function resetUserPassword(data) {
  return request({ url: "user/resetPassword", method: "post", data });
}

export function deleteUser(data) {
  return request({ url: "user/delete", method: "post", data });
}
