import request from "@/utils/request";

export function getPharmaceuticalList() {
  return request({ url: "pharmaceuticalManagement/getList", method: "get" });
}

export function createPharmaceutical(data) {
  return request({ url: "pharmaceuticalManagement/create", method: "post", data });
}

export function updatePharmaceutical(data) {
  return request({ url: "pharmaceuticalManagement/update", method: "post", data });
}

export function deletePharmaceutical(data) {
  return request({ url: "pharmaceuticalManagement/delete", method: "post", data });
}

export function stockQuery(data) {
  return request({ url: "pharmaceuticalManagement/stock_query", method: "post", data });
}

export function getDispenseList() {
  return request({ url: "pharmacy/dispenseList", method: "get" });
}

export function auditPrescription(data) {
  return request({ url: "pharmacy/audit", method: "post", data });
}

export function dispensePrescription(data) {
  return request({ url: "pharmacy/dispense", method: "post", data });
}

export function returnMedicine(data) {
  return request({ url: "pharmacy/return", method: "post", data });
}
