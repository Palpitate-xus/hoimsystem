import request from "@/utils/request";

export function getEmergencyTriageList() { return request({ url: "emergency/triage/list", method: "get" }); }
export function createEmergencyTriage(data) { return request({ url: "emergency/triage/create", method: "post", data }); }
export function updateEmergencyTriage(data) { return request({ url: "emergency/triage/update", method: "put", data }); }
