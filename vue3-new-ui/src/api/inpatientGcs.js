import request from "@/utils/request";
import { observationTime } from "@/api/inpatientObservations";
const read = (url, params) => request({ url, method: "get", params, retry: 0 });
const write = (url, data) => request({ url, method: "post", data: JSON.stringify(data), headers: { "Content-Type": "application/json" }, retry: 0 });
export const getGcsObservations = params => read("inpatient-gcs", params);
export const getGcsObservation = (id, params) => read(`inpatient-gcs/${encodeURIComponent(id)}`, params);
export const createGcsObservation = data => write("inpatient-gcs", data);
export const revokeGcsObservation = (id, data) => write(`inpatient-gcs/${encodeURIComponent(id)}/revoke`, data);
export const getAdminGcsObservations = params => read("ai/admin/gcs-sources", params);
export const getAdminGcsObservation = id => read(`ai/admin/gcs-sources/${encodeURIComponent(id)}`);
export const gcsComponentLabels = Object.freeze({ eye: "睁眼E", verbal: "言语V", motor: "运动M" });
export const gcsAbsentLabels = Object.freeze({ not_testable: "NT（不能测试）", not_recorded: "未记录" });
export const gcsCanonical = value => {
  const ordered = item => Array.isArray(item) ? item.map(ordered) : item && typeof item === "object" ? Object.fromEntries(Object.keys(item).sort().map(key => [key, ordered(item[key])])) : item;
  return JSON.stringify(ordered(value));
};
export const gcsId = value => /^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/.test(value || "");
export const gcsHash = value => /^[a-f0-9]{64}$/.test(value || "");
export function gcsComponentsValid(components) {
  return !!components && Object.keys(components).sort().join(",") === "eye,motor,verbal" && [["eye", 4], ["verbal", 5], ["motor", 6]].every(([key, max]) => {
    const item = components[key];
    return item && Object.keys(item).sort().join(",") === "absent_reason,score" && (item.score === null ? ["not_testable", "not_recorded"].includes(item.absent_reason) : Number.isInteger(item.score) && item.score >= 1 && item.score <= max && item.absent_reason === null);
  });
}
export function gcsObservationMatches(row, patientId, admissionId, compactProjection = false) {
  try {
    if (!row || !gcsId(row.gcs_observation_id) || !gcsId(row.admission_id) || !Number.isSafeInteger(row.patient_id) || row.patient_id < 1 || row.patient_id !== patientId || row.admission_id !== admissionId || row.schema_version !== "inpatient_gcs_v1" || !gcsHash(row.content_hash) || !gcsHash(row.governance_hash) || row.source_id !== `gcs_observation:${row.gcs_observation_id}:${row.content_hash.slice(0, 12)}` || !["active", "revoked"].includes(row.status) || !Number.isInteger(row.revision) || row.revision < 1 || observationTime(row.observed_at).microseconds > observationTime(row.recorded_at).microseconds) return false;
    const payload = row.payload;
    if (!payload || !gcsComponentsValid(payload.components) || (!compactProjection && typeof payload.note !== "string") || (payload.note != null && (typeof payload.note !== "string" || payload.note.length > 1000)) || typeof payload.same_exam_confirmed !== "boolean") return false;
    if (payload.anchor_point === null ? payload.same_exam_confirmed !== false || payload.same_exam_basis_note !== null : !payload.anchor_point || !gcsHash(payload.anchor_point.expected_content_hash) || !gcsId(payload.anchor_point.observation_id) || payload.same_exam_confirmed !== true || (!compactProjection && typeof payload.same_exam_basis_note !== "string") || (payload.same_exam_basis_note != null && (typeof payload.same_exam_basis_note !== "string" || payload.same_exam_basis_note.trim().length < 20))) return false;
    const anchor = row.anchor_point_snapshot;
    if (payload.anchor_point === null ? anchor !== null : !anchor || anchor.patient_id !== patientId || anchor.admission_id !== admissionId || anchor.observation_id !== payload.anchor_point.observation_id || anchor.content_hash !== payload.anchor_point.expected_content_hash || anchor.source_id !== `inpatient_observation:${anchor.observation_id}:${anchor.content_hash.slice(0, 12)}` || observationTime(anchor.observed_at).microseconds > observationTime(anchor.recorded_at).microseconds || observationTime(anchor.recorded_at).microseconds > observationTime(row.recorded_at).microseconds) return false;
    const scores = Object.values(payload.components).map(item => item.score), total = scores.some(score => score === null) ? null : scores.reduce((sum, score) => sum + score, 0);
    return row.derived_total === total;
  } catch { return false; }
}
