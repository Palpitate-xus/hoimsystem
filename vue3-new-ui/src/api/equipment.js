import request from "@/utils/request";

export function getEquipmentList() { return request({ url: "equipment/list", method: "get" }); }
export function createEquipment(data) { return request({ url: "equipment/create", method: "post", data }); }
export function getMaintenanceList() { return request({ url: "equipment/maintenance/list", method: "get" }); }
export function createMaintenance(data) { return request({ url: "equipment/maintenance/create", method: "post", data }); }
export function getInspectionList() { return request({ url: "equipment/inspection/list", method: "get" }); }
export function createInspection(data) { return request({ url: "equipment/inspection/create", method: "post", data }); }
export function getTraceList() { return request({ url: "equipment/trace/list", method: "get" }); }
