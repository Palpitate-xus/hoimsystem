import request from "@/utils/request";

export function getIcd10DiagnosisList(params) { return request({ url: "/icd10/diagnosis/list", method: "get", params }); }
export function createIcd10Diagnosis(data) { return request({ url: "/icd10/diagnosis/create", method: "post", data }); }
export function updateIcd10Diagnosis(data) { return request({ url: "/icd10/diagnosis/update", method: "put", data }); }
export function getIcd10OperationList(params) { return request({ url: "/icd10/operation/list", method: "get", params }); }
export function createIcd10Operation(data) { return request({ url: "/icd10/operation/create", method: "post", data }); }
export function updateIcd10Operation(data) { return request({ url: "/icd10/operation/update", method: "put", data }); }
