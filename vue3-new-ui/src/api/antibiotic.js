import request from "@/utils/request";

export function getAntibioticGrades() { return request({ url: "antibiotic/grade/list", method: "get" }); }
export function saveAntibioticGrade(data) { return request({ url: "antibiotic/grade/save", method: "post", data }); }
export function getAntibioticApprovals() { return request({ url: "antibiotic/approval/list", method: "get" }); }
export function reviewAntibioticApproval(data) { return request({ url: "antibiotic/approval/review", method: "post", data }); }
export function getAntibioticDdds(params) { return request({ url: "antibiotic/ddds", method: "get", params }); }
export function getAntibioticSubmissionRate(params) { return request({ url: "antibiotic/submissionRate", method: "get", params }); }
