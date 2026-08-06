import request from "@/utils/request";

export function getBloodRequests() { return request({ url: "blood/request/list", method: "get" }); }
export function createBloodRequest(data) { return request({ url: "blood/request/create", method: "post", data }); }
export function reviewBloodRequest(data) { return request({ url: "blood/request/review", method: "post", data }); }
export function recheckBlood(data) { return request({ url: "blood/recheck", method: "post", data }); }
export function crossMatchBlood(data) { return request({ url: "blood/crossMatch", method: "post", data }); }
export function issueBlood(data) { return request({ url: "blood/issue", method: "post", data }); }
export function getBloodReactions() { return request({ url: "blood/reaction/list", method: "get" }); }
