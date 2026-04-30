import request from "@/utils/request";

export function reportOutpatientVolume(data, keyword = "") {
  return request({ url: "report/outpatientVolume", method: "post", data, params: { keyword } });
}

export function reportFinance(data) {
  return request({ url: "report/finance", method: "post", data });
}

export function reportPharmaceutical(data, keyword = "") {
  return request({ url: "report/pharmaceutical", method: "post", data, params: { keyword } });
}

export function reportDoctorWorkload(data, keyword = "") {
  return request({ url: "report/doctorWorkload", method: "post", data, params: { keyword } });
}
