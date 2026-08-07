import request from "@/utils/request";

export function triageSuggest(data) {
  return request({ url: "triage/suggest", method: "post", data });
}

export function getTriageKeywords() {
  return request({ url: "triage/keywords", method: "get" });
}

export function getNavigationDepartments(keyword = "") {
  return request({ url: "navigation/departments", method: "get", params: { keyword } });
}

export function getNavigationRoute(start_department_id, end_department_id) {
  return request({ url: "navigation/route/departments", method: "get", params: { start_department_id, end_department_id } });
}

export function getNavigationFaq(keyword = "") {
  return request({ url: "navigation/faq", method: "get", params: { keyword } });
}
