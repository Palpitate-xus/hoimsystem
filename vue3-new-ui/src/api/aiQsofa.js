import request from "@/utils/request";
import { observationTime } from "@/api/inpatientObservations";
import { gcsCanonical, gcsHash, gcsId, gcsObservationMatches } from "@/api/inpatientGcs";
const read = (url, params) => request({ url, method: "get", params, retry: 0 });
const write = (url, data) => request({ url, method: "post", data: JSON.stringify(data), headers: { "Content-Type": "application/json" }, retry: 0 });
const base = "ai/qsofa-assessments";
export const getQsofaCandidates = params => read(`${base}/candidates`, params);
export const getQsofaAssessments = params => read(base, params);
export const getQsofaAssessment = (id, params) => read(`${base}/${encodeURIComponent(id)}`, params);
export const createQsofaAssessment = data => write(base, data);
export const revokeQsofaAssessment = (id, data) => write(`${base}/${encodeURIComponent(id)}/revoke`, data);
export const getAdminQsofaAssessments = params => read("ai/admin/qsofa-assessments", params);
export const getAdminQsofaAssessment = id => read(`ai/admin/qsofa-assessments/${encodeURIComponent(id)}`);
export const checkQsofaProvider = (id, expectedRevision) => write(`ai/admin/providers/${encodeURIComponent(id)}/qsofa-capabilities`, { expected_revision: expectedRevision });
export const qsofaCanonical = gcsCanonical;
const fieldsEqual = (left, right, fields) => fields.every(key => left?.[key] === right?.[key]);
const object = value => !!value && typeof value === "object" && !Array.isArray(value);
const pointKeys = ["respiratory_rate", "systolic_bp"];
export function qsofaAssessmentMatches(row, patientId, admissionId, windowId = null, requireProjection = false) {
  try {
    if (!object(row) || row.patient_id !== patientId || row.admission_id !== admissionId || !gcsId(row.assessment_id) || !gcsId(row.window_id) || !gcsId(row.point_id) || !gcsId(row.rule_profile_id) || ![row.window_content_hash, row.point_content_hash, row.rule_profile_content_hash, row.recipe_digest].every(gcsHash) || row.created_at !== row.evaluation_at || (windowId && row.window_id !== windowId) || row.schema_version !== "qsofa_assessment_v1" || !gcsHash(row.content_hash) || row.source_id !== `qsofa_assessment:${row.assessment_id}:${row.content_hash.slice(0,12)}`) return false;
    const frozen = row.snapshot, source = row.specialist_source, compact = row.context_projection === "qsofa_review_v1";
    if (!frozen) return !requireProjection && source == null;
    if (!object(frozen) || !fieldsEqual(frozen, row, ["assessment_id", "patient_id", "admission_id", "window_id", "window_content_hash", "point_id", "point_content_hash", "rule_profile_id", "rule_profile_content_hash", "recipe_digest", "evaluation_at", "created_at", "created_by"])) return false;
    const qualification = frozen.author_qualification;
    if (!object(qualification) || qualification.actor_id !== row.created_by || qualification.doctor_user_id !== row.created_by || !Number.isSafeInteger(qualification.doctor_id) || qualification.doctor_id < 1 || !["doctor", "director", "super_admin"].includes(qualification.role_at_creation) || qualification.clinical_review_signed !== true || frozen.review_mode !== "current_retrospective_review" || frozen.historical_prediction !== false) return false;
    const point = frozen.point, window = frozen.window_binding, profile = frozen.rule_profile, request = frozen.attestation, gcs = frozen.gcs_observation;
    if (!object(request) || !object(point) || point.patient_id !== patientId || point.admission_id !== admissionId || point.observation_id !== row.point_id || point.content_hash !== row.point_content_hash || point.source_id !== `inpatient_observation:${row.point_id}:${row.point_content_hash.slice(0,12)}` || window?.window_id !== row.window_id || window.content_hash !== row.window_content_hash || profile?.rule_profile_id !== row.rule_profile_id || profile.content_hash !== row.rule_profile_content_hash || profile.rule_id !== "qsofa_sepsis3_2016" || profile.recipe_digest !== row.recipe_digest || request.patient_id !== patientId || request.admission_id !== admissionId || request.window_id !== row.window_id || request.expected_window_hash !== row.window_content_hash || request.point_id !== row.point_id || request.expected_point_hash !== row.point_content_hash || request.rule_profile_id !== row.rule_profile_id || request.expected_rule_profile_hash !== row.rule_profile_content_hash) return false;
    if (gcs == null ? request.gcs_observation !== null : !gcsObservationMatches(gcs, patientId, admissionId, compact) || gcs.gcs_observation_id !== request.gcs_observation?.gcs_observation_id || gcs.content_hash !== request.gcs_observation?.expected_content_hash || gcs.payload.anchor_point?.observation_id !== point.observation_id || gcs.payload.anchor_point?.expected_content_hash !== point.content_hash) return false;
    if (!Array.isArray(frozen.gcs_group) || frozen.gcs_group.length > 1000 || new Set(frozen.gcs_group.map(member => member?.gcs_observation_id)).size !== frozen.gcs_group.length || frozen.gcs_group.some(member => !gcsObservationMatches(member, patientId, admissionId, compact) || member.payload.anchor_point?.observation_id !== point.observation_id || member.payload.anchor_point?.expected_content_hash !== point.content_hash || observationTime(member.recorded_at).microseconds > observationTime(window.as_of).microseconds)) return false;
    if (gcs && !frozen.gcs_group.some(member => member.gcs_observation_id === gcs.gcs_observation_id && member.content_hash === gcs.content_hash && member.governance_hash === gcs.governance_hash)) return false;
    if (!source) return !requireProjection;
    if (!object(source) || ![source.source_governance_hash, source.window_content_hash, source.point_content_hash, source.point_governance_hash, source.rule_profile_content_hash, source.rule_profile_governance_hash, source.recipe_digest].every(gcsHash) || !fieldsEqual(source, row, ["assessment_id", "source_id", "content_hash", "window_id", "window_content_hash", "point_id", "point_content_hash", "rule_profile_id", "rule_profile_content_hash", "recipe_digest", "evaluation_at"]) || source.source_governance_hash !== row.governance_hash || source.rule_id !== "qsofa_sepsis3_2016" || source.review_mode !== "current_retrospective_review" || source.historical_prediction !== false || source.clinical_statements_recorded_at !== row.evaluation_at || source.clinical_scope_applies_to !== point.observed_at || !fieldsEqual(source, point, ["observed_at", "recorded_at"]) || source.point_source_id !== point.source_id || source.point_governance_hash !== point.governance_hash || source.window_source_id !== window.source_id || !fieldsEqual(source, window, ["start_at", "end_at", "as_of"]) || source.rule_profile_source_id !== profile.source_id || source.rule_profile_governance_hash !== profile.governance_hash || !fieldsEqual(source, request, ["age_at_observation_years", "care_setting", "infection_status", "gcs_interpretability"]) || !gcsHash(source.scope_evidence_hash)) return false;
    if (source.age_at_observation_years !== null && (!Number.isInteger(source.age_at_observation_years) || source.age_at_observation_years < 0 || source.age_at_observation_years > 130) || !["non_icu", "icu", "unknown"].includes(source.care_setting) || !["suspected", "documented", "not_suspected", "unknown"].includes(source.infection_status) || !["confirmed", "limited", "unknown"].includes(source.gcs_interpretability) || !Array.isArray(source.point_conflicts) || new Set(source.point_conflicts).size !== source.point_conflicts.length || source.point_conflicts.some(key => !pointKeys.includes(key))) return false;
    const measurements = Object.fromEntries(Object.entries(point.payload?.measurements || {}).filter(([key]) => pointKeys.includes(key)));
    if (qsofaCanonical(source.measurements) !== qsofaCanonical(measurements)) return false;
    for (const [key, item] of Object.entries(source.measurements)) if (!object(item) || item.unit !== (key === "respiratory_rate" ? "/min" : "mm[Hg]") || (item.value === null ? !["unknown", "not_performed", "measurement_error"].includes(item.absent_reason) : typeof item.value !== "string" || !/^(?:0|[1-9]\d{0,15})(?:\.\d{1,8})?$/.test(item.value) || item.absent_reason !== null)) return false;
    if (qsofaCanonical(source.point_conflicts) !== qsofaCanonical(frozen.point_conflicts)) return false;
    if (compact && (frozen.provenance_note_hashes?.scope_evidence_hash !== source.scope_evidence_hash || frozen.provenance_note_hashes?.gcs_review_evidence_hash !== source.gcs_review_evidence_hash)) return false;
    const clock = value => observationTime(value).microseconds;
    if (!(clock(source.start_at) <= clock(source.observed_at) && clock(source.observed_at) <= clock(source.end_at) && clock(source.end_at) <= clock(source.as_of) && clock(source.observed_at) <= clock(source.recorded_at) && clock(source.recorded_at) <= clock(source.as_of) && clock(source.as_of) <= clock(source.evaluation_at))) return false;
    if (gcs == null) return source.gcs === null && source.gcs_interpretability === "unknown" && source.gcs_review_evidence_hash === null;
    const actual = source.gcs;
    if (compact && (gcs.provenance_note_hashes?.same_exam_basis_note !== actual?.same_exam_evidence_hash || frozen.provenance_note_hashes?.gcs_review_note !== source.gcs_review_evidence_hash || frozen.gcs_group.some(member => !gcsHash(member.provenance_note_hashes?.same_exam_basis_note)))) return false;
    const activeMembers = frozen.gcs_group.filter(member => member.status === "active"), conflict = new Set(activeMembers.map(member => qsofaCanonical(member.payload.components))).size > 1;
    if (actual?.conflict !== conflict) return false;
    return object(actual) && fieldsEqual(actual, gcs, ["gcs_observation_id", "source_id", "content_hash", "governance_hash", "schema_version", "observed_at", "recorded_at"]) && qsofaCanonical(actual.components) === qsofaCanonical(gcs.payload.components) && actual.anchor_point_id === point.observation_id && actual.anchor_point_source_id === point.source_id && actual.anchor_point_content_hash === point.content_hash && actual.same_exam_confirmed === true && typeof actual.conflict === "boolean" && gcsHash(actual.same_exam_evidence_hash) && gcsHash(source.gcs_review_evidence_hash) && clock(source.start_at) <= clock(actual.observed_at) && clock(actual.observed_at) <= clock(source.end_at) && clock(actual.recorded_at) <= clock(source.as_of);
  } catch { return false; }
}
// Expand only these fixed, source-bound paths; never execute a provider path.
export function resolveQsofaEvidence(item, context, patientId, admissionId) {
  if (!item) return item;
  let ref; try { ref = JSON.parse(item.content); } catch { return item; }
  if (!object(ref) || !("context_path" in ref)) return item;
  const unavailable = () => ({ ...item, content: "原资料索引与当前冻结来源不一致，无法展开。请重新核对原评估。" });
  const scope = context?.qsofa_assessment, source = context?.qsofa_source;
  if (Object.keys(ref).length !== 1 || !qsofaAssessmentMatches({ ...scope, specialist_source: source }, patientId, admissionId, scope?.window_id, true)) return unavailable();
  const candidates = [["context.qsofa_assessment", scope], ["context.observation_window_binding", scope.snapshot.window_binding], ["context.qsofa_assessment.snapshot.point", scope.snapshot.point], ["context.qsofa_assessment.snapshot.rule_profile", scope.snapshot.rule_profile], ["context.qsofa_source.gcs", source.gcs]];
  const match = candidates.find(([path, value]) => path === ref.context_path && value?.source_id === item.source_id);
  return match ? { ...item, title: "冻结原始依据", content: JSON.stringify(match[1], null, 2) } : unavailable();
}
