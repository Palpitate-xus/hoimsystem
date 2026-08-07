import request from "@/utils/request";
import { tokenName } from "@/config";
import JSEncrypt from "jsencrypt";

let publicKeyPromise;

function toPem(base64Key) {
  const lines = base64Key.match(/.{1,64}/g)?.join("\n") || base64Key;
  return `-----BEGIN PUBLIC KEY-----\n${lines}\n-----END PUBLIC KEY-----`;
}

export async function encryptPassword(password) {
  if (!publicKeyPromise) {
    publicKeyPromise = request({ url: "publicKey", method: "get" })
      .then((response) => response?.data?.publicKey)
      .catch((error) => {
        publicKeyPromise = undefined;
        throw error;
      });
  }
  const publicKey = await publicKeyPromise;
  const encryptor = new JSEncrypt();
  encryptor.setPublicKey(toPem(publicKey));
  const encrypted = encryptor.encrypt(password);
  if (!encrypted) throw new Error("密码加密失败，请稍后重试");
  return `RSA1:${encrypted}`;
}

export async function login(data) {
  const password = await encryptPassword(data.password);
  return request({
    url: "login",
    method: "post",
    data: { ...data, password },
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

export async function register(data) {
  const password = await encryptPassword(data.password);
  return request({
    url: "register",
    method: "post",
    data: { ...data, password },
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

export async function resetUserPassword(data) {
  const new_password = await encryptPassword(data.new_password);
  return request({ url: "user/resetPassword", method: "post", data: { ...data, new_password } });
}

export function deleteUser(data) {
  return request({ url: "user/delete", method: "post", data });
}
