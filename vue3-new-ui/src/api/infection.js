import request from "@/utils/request";

export function getInfectionCases() { return request({ url: "infection/case/list", method: "get" }); }
export function createInfectionCase(data) { return request({ url: "infection/case/create", method: "post", data }); }
export function getDisinfectionRecords() { return request({ url: "infection/disinfection/list", method: "get" }); }
export function createDisinfectionRecord(data) { return request({ url: "infection/disinfection/create", method: "post", data }); }
export function getExposureRecords() { return request({ url: "infection/exposure/list", method: "get" }); }
export function createExposureRecord(data) { return request({ url: "infection/exposure/create", method: "post", data }); }
export function getInfectionReport() { return request({ url: "infection/report", method: "get" }); }
export function getOutbreakAlerts() { return request({ url: "infection/outbreakAlert", method: "get" }); }
