import request from "@/utils/request";

export function getPharmaceuticalList(keyword = "") {
  return request({ url: "pharmaceuticalManagement/getList", method: "get", params: { keyword } });
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

export { setMedicationBarcode } from "@/api/emar";

export function stockQuery(data) {
  return request({ url: "pharmaceuticalManagement/stock_query", method: "post", data });
}

export function getDispenseList(keyword = "") {
  return request({ url: "pharmacy/dispenseList", method: "get", params: { keyword } });
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

export function getLowStockDrugs(threshold = 10, keyword = "") {
  return request({ url: "pharmaceuticalManagement/lowStock", method: "get", params: { threshold, keyword } });
}

export function getNearExpiryDrugs(days = 30, keyword = "") {
  return request({ url: "pharmaceuticalManagement/nearExpiry", method: "get", params: { days, keyword } });
}

export function stockCheck(data) {
  return request({ url: "pharmacy/stockCheck", method: "post", data });
}

export function reviewPrescription(data) {
  return request({ url: "pharmacy/review", method: "post", data });
}

export function getReviewList(keyword = "") {
  return request({ url: "pharmacy/reviewList", method: "get", params: { keyword } });
}

export function getDrugDamageList(status) { return request({ url: "pharmacy/drugDamage/list", method: "get", params: status === undefined ? {} : { status } }); }
export function createDrugDamage(data) { return request({ url: "pharmacy/drugDamage/create", method: "post", data }); }
export function approveDrugDamage(data) { return request({ url: "pharmacy/drugDamage/approve", method: "post", data }); }
export function rejectDrugDamage(data) { return request({ url: "pharmacy/drugDamage/reject", method: "post", data }); }

export function getDispenseStats(params = {}) {
  return request({ url: "pharmacy/dispenseStats", method: "get", params });
}

export function getInventoryAdjustments(status) {
  return request({ url: "pharmacy/inventoryAdjustment/list", method: "get", params: status === undefined ? {} : { status } });
}

export function createInventoryAdjustment(data) {
  return request({ url: "pharmacy/inventoryAdjustment/create", method: "post", data });
}

export function approveInventoryAdjustment(data) {
  return request({ url: "pharmacy/inventoryAdjustment/approve", method: "post", data });
}

export function rejectInventoryAdjustment(data) {
  return request({ url: "pharmacy/inventoryAdjustment/reject", method: "post", data });
}

export function getDispenseVerificationList() { return request({ url: "pharmacy/verificationList", method: "get" }); }
export function verifyDispense(data) { return request({ url: "pharmacy/verify", method: "post", data }); }
export function getSpecialDrugList() { return request({ url: "specialDrug/list", method: "get" }); }
export function createSpecialDrug(data) { return request({ url: "specialDrug/create", method: "post", data }); }
export function approveSpecialDrug(data) { return request({ url: "specialDrug/approve", method: "post", data }); }
export function rejectSpecialDrug(data) { return request({ url: "specialDrug/reject", method: "post", data }); }
