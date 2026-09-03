import request from "@/utils/request";

export function getInsuranceCatalog() { return request({ url: "insurance/catalog/list", method: "get" }); }
export function getInsuranceSettlements() { return request({ url: "insurance/settlement/list", method: "get" }); }
export function createInsuranceSettlement(data) { return request({ url: "insurance/settlement/create", method: "post", data }); }
export function getChronicRegistrations() { return request({ url: "insurance/chronic/list", method: "get" }); }
export function getDrgAnalysis() { return request({ url: "insurance/drg/analysis", method: "get" }); }
export function getInsuranceWarnings() { return request({ url: "insurance/control/warnings", method: "get" }); }
export function getDrgRules(params) { return request({ url: "insurance/drg/rules", method: "get", params }); }
export function saveDrgRule(data) { return request({ url: "insurance/drg/rule", method: "post", data }); }
export function autoGroupDrg(data) { return request({ url: "insurance/drg/autoGroup", method: "post", data }); }
