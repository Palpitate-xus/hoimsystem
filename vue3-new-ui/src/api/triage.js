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
