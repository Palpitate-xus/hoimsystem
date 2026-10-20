import request from "@/utils/request";
import { labSourceMatches } from "@/api/inpatientLaboratory";

const read = (url, params) => request({ url, method: "get", params, retry: 0 });
// Explicit nullable baseline, weight and RRT facts must survive interception.
const write = (url, data) => request({ url, method: "post", data: JSON.stringify(data), headers: { "Content-Type": "application/json" }, retry: 0 });
const assessments = "ai/aki-assessments";
export const getAkiCandidates = params => read(`${assessments}/candidates`, params);
export const getAkiAssessments = params => read(assessments, params);
export const getAkiAssessment = (id, params) => read(`${assessments}/${encodeURIComponent(id)}`, params);
export const createAkiAssessment = data => write(assessments, data);
export const revokeAkiAssessment = (id, data) => write(`${assessments}/${encodeURIComponent(id)}/revoke`, data);
export const getAdminAkiAssessments = params => read("ai/admin/aki-assessments", params);
export const getAdminAkiAssessment = id => read(`ai/admin/aki-assessments/${encodeURIComponent(id)}`);
export const checkAkiProvider = (id, expectedRevision) => write(`ai/admin/providers/${encodeURIComponent(id)}/aki-capabilities`, { expected_revision: expectedRevision });

export const akiCanonical = value => {
  const ordered = item => Array.isArray(item) ? item.map(ordered) : item && typeof item === "object" ? Object.fromEntries(Object.keys(item).sort().map(key => [key, ordered(item[key])])) : item;
  return JSON.stringify(ordered(value));
};

const object = value => !!value && typeof value === "object" && !Array.isArray(value);
const hash = value => /^[a-f0-9]{64}$/.test(value || "");
const equalFields = (left, right, fields) => fields.every(key => left?.[key] === right?.[key]);
// The hospital wrapper proves original scope and raw inputs. The minimized
// specialist projection alone is deliberately insufficient for UI selection.
export function akiAssessmentMatches(row, patientId, admissionId, windowId = null, requireProjection = false) {
  try {
    if (!object(row) || row.patient_id !== patientId || row.admission_id !== admissionId || (windowId && row.window_id !== windowId) || !hash(row.content_hash) || row.source_id !== `aki_assessment:${row.assessment_id}:${row.content_hash.slice(0, 12)}`) return false;
    const frozen = row.snapshot, source = row.specialist_source;
    if (frozen == null) return !requireProjection && source == null;
    if (!object(frozen) || !equalFields(frozen, row, ["assessment_id", "patient_id", "admission_id", "window_id", "window_content_hash", "rule_profile_id", "rule_profile_content_hash", "recipe_digest", "evaluation_at"]) || frozen.window_binding?.window_id !== row.window_id || frozen.window_binding?.content_hash !== row.window_content_hash || frozen.rule_profile?.rule_profile_id !== row.rule_profile_id || frozen.rule_profile?.content_hash !== row.rule_profile_content_hash || frozen.rule_profile?.rule_id !== "kdigo_aki_2012" || frozen.rule_profile?.recipe_digest !== row.recipe_digest || !object(frozen.attestation) || frozen.attestation.patient_id !== patientId || frozen.attestation.admission_id !== admissionId || frozen.attestation.window_id !== row.window_id || frozen.attestation.expected_window_hash !== row.window_content_hash || frozen.attestation.rule_profile_id !== row.rule_profile_id || frozen.attestation.expected_rule_profile_hash !== row.rule_profile_content_hash || !Array.isArray(frozen.urine_intervals)) return false;
    const request = frozen.attestation;
    for (const role of ["index_creatinine", "comparison_48h", "baseline_creatinine"]) {
      const raw = frozen[role], reference = request[role];
      const mayUseOriginalAdmission = role === "baseline_creatinine" && request.baseline_mode === "presumed_within_7d";
      if (raw == null ? reference !== null : !object(raw) || raw.assessment_projection !== "aki_lab_projection_v1" || !object(raw.snapshot) || !labSourceMatches(raw, patientId, mayUseOriginalAdmission ? raw.admission_id : admissionId) || raw.lab_source_id !== reference?.lab_source_id || raw.content_hash !== reference?.expected_content_hash) return false;
    }
    const point = frozen.weight_point;
    if (point == null ? request.weight_point !== null : point.patient_id !== patientId || point.admission_id !== admissionId || point.observation_id !== request.weight_point?.observation_id || point.content_hash !== request.weight_point?.expected_content_hash || !object(point.payload?.measurements?.body_weight)) return false;
    if (!Array.isArray(request.urine_intervals) || request.urine_intervals.length !== frozen.urine_intervals.length || frozen.urine_intervals.length > 64 || new Set(frozen.urine_intervals.map(item => item?.interval_id)).size !== frozen.urine_intervals.length || frozen.urine_intervals.some(item => item?.patient_id !== patientId || item.admission_id !== admissionId || !object(item.payload) || !request.urine_intervals.some(ref => ref.interval_id === item.interval_id && ref.expected_content_hash === item.content_hash))) return false;
    if (!source) return !requireProjection;
    if (!object(source) || source.rule_id !== "kdigo_aki_2012" || !Number.isInteger(source.age_at_evaluation_years) || source.age_at_evaluation_years < 0 || source.age_at_evaluation_years > 130 || typeof source.creatinine_review?.serum_creatinine_confirmed !== "boolean" || typeof source.weight_applicability_confirmed !== "boolean" || !["unknown", "observed_within_7d", "presumed_within_7d"].includes(source.baseline_mode) || !["unknown", "not_initiated", "acute_initiated_for_aki", "maintenance"].includes(source.rrt?.status) || !equalFields(source, row, ["assessment_id", "source_id", "content_hash", "window_id", "window_content_hash", "rule_profile_id", "rule_profile_content_hash", "recipe_digest", "evaluation_at"]) || source.source_governance_hash !== row.governance_hash || source.window_source_id !== frozen.window_binding.source_id || !equalFields(source, frozen.window_binding, ["start_at", "end_at", "as_of"]) || source.rule_profile_source_id !== frozen.rule_profile.source_id || source.rule_profile_governance_hash !== frozen.rule_profile.governance_hash || source.age_at_evaluation_years !== request.age_at_evaluation_years || source.baseline_mode !== request.baseline_mode || source.creatinine_review?.serum_creatinine_confirmed !== request.serum_creatinine_confirmed || source.weight_applicability_confirmed !== request.weight_applicability_confirmed || source.rrt?.status !== request.rrt_status || source.rrt?.started_at !== request.rrt_started_at || source.rrt?.acute_aki_confirmed !== request.rrt_acute_aki_confirmed || akiCanonical(source.urine_coverage_issues) !== akiCanonical(frozen.urine_coverage_issues)) return false;
    if (source.creatinine_review.serum_creatinine_confirmed && !hash(source.creatinine_review.evidence_hash) || source.weight_applicability_confirmed && !hash(source.weight_evidence_hash) || source.rrt.status !== "unknown" && !hash(source.rrt.evidence_hash)) return false;
    if (request.baseline_rise_within_7d_confirmed != null && (request.baseline_review_note != null || frozen.provenance_note_hashes?.baseline_review_note) ? !object(source.baseline_review) || source.baseline_review.rise_within_7d_confirmed !== request.baseline_rise_within_7d_confirmed || !hash(source.baseline_review.evidence_hash) : source.baseline_review !== null) return false;
    for (const [key, evidence] of [["creatinine_review_note", source.creatinine_review.evidence_hash], ["baseline_review_note", source.baseline_review?.evidence_hash], ["weight_basis_note", source.weight_evidence_hash], ["rrt_basis_note", source.rrt.evidence_hash]]) if (frozen.provenance_note_hashes?.[key] && frozen.provenance_note_hashes[key] !== evidence) return false;
    for (const role of ["index_creatinine", "comparison_48h", "baseline_creatinine"]) {
      const raw = frozen[role], item = source[role];
      if (raw == null ? item !== null : !object(item) || !equalFields(item, raw, ["lab_source_id", "source_id", "content_hash", "governance_hash", "collected_at_utc", "registered_at", "available_at", "mapping_id", "mapping_content_hash", "identity_hash", "conflict"]) || item.mapping_governance_hash !== raw.mapping_current?.governance_hash || item.value !== raw.snapshot.original?.observation?.value_num || item.unit !== raw.snapshot.original?.observation?.unit) return false;
    }
    const weight = source.weight;
    if (point == null ? weight !== null : !object(weight) || weight.point_id !== point.observation_id || !equalFields(weight, point, ["source_id", "content_hash", "governance_hash", "observed_at", "recorded_at", "conflict"]) || !equalFields(weight, point.payload.measurements.body_weight, ["value", "unit", "absent_reason"])) return false;
    if (!Array.isArray(source.urine_intervals) || source.urine_intervals.length !== frozen.urine_intervals.length || new Set(source.urine_intervals.map(item => item?.interval_id)).size !== source.urine_intervals.length || source.urine_intervals.some(item => { const raw = frozen.urine_intervals.find(original => original.interval_id === item.interval_id); return !raw || !equalFields(item, raw, ["source_id", "content_hash", "governance_hash", "start_at", "end_at", "recorded_at"]) || !equalFields(item, raw.payload, ["volume_ml", "absent_reason", "collection_completeness", "patient_total"]); })) return false;
    return true;
  } catch { return false; }
}
