import request from "@/utils/request";

export function triageSuggest(data) {
  return request({ url: "triage/suggest", method: "post", data });
}

export function getTriageKeywords() {
  return request({ url: "triage/keywords", method: "get" });
}
