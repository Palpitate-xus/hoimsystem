import request from "@/utils/request";

export function getInsuranceCatalog() { return request({ url: "insurance/catalog/list", method: "get" }); }
export function getInsuranceSettlements() { return request({ url: "insurance/settlement/list", method: "get" }); }
export function createInsuranceSettlement(data) { return request({ url: "insurance/settlement/create", method: "post", data }); }
export function getChronicRegistrations() { return request({ url: "insurance/chronic/list", method: "get" }); }
export function getDrgAnalysis() { return request({ url: "insurance/drg/analysis", method: "get" }); }
export function getInsuranceWarnings() { return request({ url: "insurance/control/warnings", method: "get" }); }
