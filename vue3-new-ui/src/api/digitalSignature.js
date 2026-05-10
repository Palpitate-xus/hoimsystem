import request from "@/utils/request";

export function digitalSign(data) {
  return request({ url: "digitalSignature/sign", method: "post", data });
}
export function verifySign(data) {
  return request({ url: "digitalSignature/verify", method: "post", data });
}
