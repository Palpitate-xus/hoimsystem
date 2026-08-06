import request from "@/utils/request";

export function getNursingRecordList(params) {
  return request({
    url: "/nursingRecord/getList",
    method: "get",
    params,
  });
}

export function createNursingRecord(data) {
  return request({
    url: "/nursingRecord/create",
    method: "post",
    data,
  });
}

export function deleteNursingRecord(data) {
  return request({
    url: "/nursingRecord/delete",
    method: "post",
    data,
  });
}

export function getTemperatureRecordList(params) {
  return request({
    url: "/temperatureRecord/getList",
    method: "get",
    params,
  });
}

export function createTemperatureRecord(data) {
  return request({
    url: "/temperatureRecord/create",
    method: "post",
    data,
  });
}

export function deleteTemperatureRecord(data) {
  return request({
    url: "/temperatureRecord/delete",
    method: "post",
    data,
  });
}

export function getInfusionList() { return request({ url: "/infusion/list", method: "get" }); }
export function createInfusion(data) { return request({ url: "/infusion/create", method: "post", data }); }
export function executeInfusion(data) { return request({ url: "/infusion/execute", method: "post", data }); }
export function observeInfusion(data) { return request({ url: "/infusion/observe", method: "post", data }); }
export function completeInfusion(data) { return request({ url: "/infusion/complete", method: "post", data }); }
export function cancelInfusion(data) { return request({ url: "/infusion/cancel", method: "post", data }); }
export function getInjectionList() { return request({ url: "/injection/list", method: "get" }); }
export function executeInjection(data) { return request({ url: "/injection/execute", method: "post", data }); }
export function completeInjection(data) { return request({ url: "/injection/complete", method: "post", data }); }
export function getSkinTestList() { return request({ url: "/skinTest/list", method: "get" }); }
export function administerSkinTest(data) { return request({ url: "/skinTest/administer", method: "post", data }); }
export function assessSkinTest(data) { return request({ url: "/skinTest/assess", method: "post", data }); }
export function getShiftHandoverList() { return request({ url: "/shiftHandover/list", method: "get" }); }
export function createShiftHandover(data) { return request({ url: "/shiftHandover/create", method: "post", data }); }
export function receiveShiftHandover(data) { return request({ url: "/shiftHandover/receive", method: "post", data }); }
export function getNursingAssessmentList(params) { return request({ url: "/nursingAssessment/list", method: "get", params }); }
export function createNursingAssessment(data) { return request({ url: "/nursingAssessment/create", method: "post", data }); }
export function updateNursingAssessment(data) { return request({ url: "/nursingAssessment/update", method: "put", data }); }
export function completeNursingAssessment(data) { return request({ url: "/nursingAssessment/complete", method: "post", data }); }
export function getNursingPlanList(params) { return request({ url: "/nursingPlan/list", method: "get", params }); }
export function createNursingPlan(data) { return request({ url: "/nursingPlan/create", method: "post", data }); }
export function updateNursingPlan(data) { return request({ url: "/nursingPlan/update", method: "put", data }); }
