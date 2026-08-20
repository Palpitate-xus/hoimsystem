import request from "@/utils/request";

export function getMedicalRecordArchiveList() { return request({ url: "/medicalRecordArchive/list", method: "get" }); }
export function createMedicalRecordArchive(data) { return request({ url: "/medicalRecordArchive/create", method: "post", data }); }
export function archiveMedicalRecord(data) { return request({ url: "/medicalRecordArchive/archive", method: "post", data }); }
export function borrowMedicalRecord(data) { return request({ url: "/medicalRecordArchive/borrow", method: "post", data }); }
export function returnMedicalRecord(data) { return request({ url: "/medicalRecordArchive/return", method: "post", data }); }
export function sealMedicalRecord(data) { return request({ url: "/medicalRecordArchive/seal", method: "post", data }); }

export function getBorrowRequests(params) {
  return request({ url: "medicalRecordArchive/borrowRequests", method: "get", params });
}
export function approveBorrowRequest(data) {
  return request({ url: "medicalRecordArchive/borrowApprove", method: "post", data });
}
