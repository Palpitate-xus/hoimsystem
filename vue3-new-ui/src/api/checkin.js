import request from "@/utils/request";

export function checkIn(data) {
  return request({ url: "checkIn/checkIn", method: "post", data });
}
