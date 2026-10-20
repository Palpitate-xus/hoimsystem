import request from "@/utils/request";

const read = (url, params) => request({ url, method: "get", params, retry: 0 });
// Explicit unknown applicability fields must survive the shared interceptor.
const write = (url, data) => request({ url, method: "post", data: JSON.stringify(data), headers: { "Content-Type": "application/json" }, retry: 0 });
const assessments = "ai/news2-assessments", profiles = "ai/admin/risk-rule-profiles";
export const getNews2Candidates = params => read(`${assessments}/candidates`, params);
export const getNews2Assessments = params => read(assessments, params);
export const getNews2Assessment = (id, params) => read(`${assessments}/${encodeURIComponent(id)}`, params);
export const createNews2Assessment = data => write(assessments, data);
export const revokeNews2Assessment = (id, data) => write(`${assessments}/${encodeURIComponent(id)}/revoke`, data);
export const getRiskRuleOptions = () => read(`${profiles}/options`);
export const getRiskRuleProfiles = params => read(profiles, params);
export const getRiskRuleProfile = id => read(`${profiles}/${encodeURIComponent(id)}`);
export const createRiskRuleProfile = data => write(profiles, data);
export const publishRiskRuleProfile = (id, data) => write(`${profiles}/${encodeURIComponent(id)}/publish`, data);
export const revokeRiskRuleProfile = (id, data) => write(`${profiles}/${encodeURIComponent(id)}/revoke`, data);
export const getAdminNews2Assessments = params => read("ai/admin/news2-assessments", params);
export const getAdminNews2Assessment = id => read(`ai/admin/news2-assessments/${encodeURIComponent(id)}`);
export const checkNews2Provider = (id, expectedRevision) => write(`ai/admin/providers/${encodeURIComponent(id)}/news2-capabilities`, { expected_revision: expectedRevision });

export const news2Canonical = value => {
  const ordered = item => Array.isArray(item) ? item.map(ordered) : item && typeof item === "object" ? Object.fromEntries(Object.keys(item).sort().map(key => [key, ordered(item[key])])) : item;
  return JSON.stringify(ordered(value));
};
export function news2AssessmentMatches(row, patientId, admissionId, windowId = null, requireProjection = false) {
  if (row?.patient_id !== patientId || row.admission_id !== admissionId || (windowId && row.window_id !== windowId) || !/^[a-f0-9]{64}$/.test(row.content_hash || "")) return false;
  const frozen = row.snapshot;
  if (frozen != null && (typeof frozen !== "object" || Array.isArray(frozen) || ["assessment_id", "patient_id", "admission_id", "window_id", "window_content_hash", "point_id", "point_content_hash", "rule_profile_id", "rule_profile_content_hash", "recipe_digest", "observed_at"].some(key => frozen[key] !== row[key]) || frozen.point?.patient_id !== patientId || frozen.point?.admission_id !== admissionId || frozen.point?.observation_id !== row.point_id || frozen.point?.content_hash !== row.point_content_hash || frozen.rule_profile?.rule_profile_id !== row.rule_profile_id || frozen.rule_profile?.content_hash !== row.rule_profile_content_hash || frozen.window_binding?.window_id !== row.window_id || frozen.window_binding?.content_hash !== row.window_content_hash)) return false;
  if (requireProjection && !frozen) return false;
  const source = row.specialist_source;
  if (!source) return !requireProjection;
  if (typeof source !== "object" || Array.isArray(source) || !frozen) return false;
  const expectedMeasurements = Object.fromEntries(Object.entries(frozen.point.payload?.measurements || {}).filter(([key]) => ["respiratory_rate", "spo2", "systolic_bp", "pulse_rate", "temperature"].includes(key)));
  if (news2Canonical(source.measurements) !== news2Canonical(expectedMeasurements) || source.supplemental_oxygen !== frozen.point.payload?.supplemental_oxygen || news2Canonical(source.consciousness) !== news2Canonical(frozen.point.payload?.consciousness) || ["age_at_observation_years", "pregnancy_status", "spo2_scale"].some(key => source[key] !== frozen.attestation?.[key])) return false;
  return ["assessment_id", "source_id", "content_hash", "window_id", "window_content_hash", "point_id", "rule_profile_id", "rule_profile_content_hash", "recipe_digest", "observed_at"].every(key => source[key] === row[key]) && source.source_governance_hash === row.governance_hash;
}
