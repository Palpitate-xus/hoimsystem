import request from "@/utils/request";

export function reportOutpatientVolume(data) {
  return request({ url: "report/outpatientVolume", method: "post", data });
}

export function reportFinance(data) {
  return request({ url: "report/finance", method: "post", data });
}

export function reportPharmaceutical(data) {
  return request({ url: "report/pharmaceutical", method: "post", data });
}

export function reportDoctorWorkload(data) {
  return request({ url: "report/doctorWorkload", method: "post", data });
}
