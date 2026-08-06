import request from "@/utils/request";

export function getSchedulerStatus() {
  return request({ url: "scheduler/status", method: "get" });
}

export function runSchedulerJob(jobName) {
  return request({ url: `scheduler/run/${jobName}`, method: "post" });
}
