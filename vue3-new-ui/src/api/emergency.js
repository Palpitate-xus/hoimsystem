import request from "@/utils/request";

export function getEmergencyTriageList() { return request({ url: "emergency/triage/list", method: "get" }); }
export function createEmergencyTriage(data) { return request({ url: "emergency/triage/create", method: "post", data }); }
export function updateEmergencyTriage(data) { return request({ url: "emergency/triage/update", method: "put", data }); }
export function getEmergencyRescueList(triageId) { return request({ url: "emergency/rescue/list", method: "get", params: triageId ? { triage_id: triageId } : {} }); }
export function createEmergencyRescueEvent(data) { return request({ url: "emergency/rescue/create", method: "post", data }); }
export function getEmergencyObservationList(params = {}) { return request({ url: "emergency/observation/list", method: "get", params }); }
export function createEmergencyObservation(data) { return request({ url: "emergency/observation/create", method: "post", data }); }
export function updateEmergencyObservation(data) { return request({ url: "emergency/observation/update", method: "put", data }); }
export function getEmergencyGreenChannelList() { return request({ url: "emergency/greenChannel/list", method: "get" }); }
export function createEmergencyGreenChannel(data) { return request({ url: "emergency/greenChannel/create", method: "post", data }); }
export function approveEmergencyGreenChannel(data) { return request({ url: "emergency/greenChannel/approve", method: "post", data }); }
export function closeEmergencyGreenChannel(data) { return request({ url: "emergency/greenChannel/close", method: "post", data }); }
