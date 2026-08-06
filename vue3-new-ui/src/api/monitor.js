import request from "@/utils/request";

export function getMonitorSummary() { return request({ url: "/monitor/summary", method: "get" }); }
