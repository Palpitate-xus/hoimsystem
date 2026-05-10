import request from "@/utils/request";

export function getSlotPoolList() {
  return request({ url: "slotPool/getList", method: "get" });
}

export function adjustSlot(data) {
  return request({ url: "slotPool/adjust", method: "post", data });
}
