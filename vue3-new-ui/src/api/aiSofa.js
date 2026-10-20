import request from "@/utils/request";
import { observationTime } from "@/api/inpatientObservations";
import { supportCanonical, supportDigest, supportHash, supportId, supportUtc, verifySupportLab, verifySupportPoint, verifySupportSource } from "@/api/inpatientSupport";
import { gcsObservationMatches } from "@/api/inpatientGcs";
import { sofaSchemaMatches } from "./sofaSchema";
import { projectSofaChangeSource, projectSofaSource } from "./aiSofaProjection";

export const sofaRuleId = "sofa1_native_observed_v1";
export const sofaAxes = Object.freeze(["respiratory", "coagulation", "liver", "cardiovascular", "cns", "renal"]);
export const sofaAxisLabels = Object.freeze({ respiratory: "呼吸", coagulation: "凝血", liver: "肝脏", cardiovascular: "心血管", cns: "中枢神经", renal: "肾脏" });
export const sofaReviewDefinitions = Object.freeze({ laboratory: "LaboratoryReview", map: "MapReview", respiratory_support: "RespiratorySupportReview", arterial_pair: "ArterialPairReview", vasoactive: "VasoactiveReview", gcs: "GcsReview", urine: "UrineReview" });
const daily = "ai/sofa-assessments", change = "ai/sofa-change-assessments";
const read = (url, params) => request({ url, method: "get", params, retry: 0 });
// Explicit unknowns, false declarations and original zero must survive the interceptor.
const write = (url, data) => request({ url, method: "post", data: JSON.stringify(data), headers: { "Content-Type": "application/json" }, retry: 0 });
const segment = id => { if (!supportId(id)) throw new Error("SOFA来源标识须为规范UUID"); return id; };
export const getSofaCandidates = data => write(`${daily}/candidates`, data);
export const getSofaAssessments = params => read(daily, params);
export const getSofaAssessment = (id, params) => read(`${daily}/${segment(id)}`, params);
export const createSofaAssessment = data => write(daily, data);
export const revokeSofaAssessment = (id, data) => write(`${daily}/${segment(id)}/revoke`, data);
export const getAdminSofaAssessments = params => read("ai/admin/sofa-assessments", params);
export const getAdminSofaAssessment = id => read(`ai/admin/sofa-assessments/${segment(id)}`);
export const getSofaChangeCandidates = data => write(`${change}/candidates`, data);
export const getSofaChangeAssessments = params => read(change, params);
export const getSofaChangeAssessment = (id, params) => read(`${change}/${segment(id)}`, params);
export const createSofaChangeAssessment = data => write(change, data);
export const revokeSofaChangeAssessment = (id, data) => write(`${change}/${segment(id)}/revoke`, data);
export const getAdminSofaChangeAssessments = params => read("ai/admin/sofa-change-assessments", params);
export const getAdminSofaChangeAssessment = id => read(`ai/admin/sofa-change-assessments/${segment(id)}`);
export const checkSofaProvider = (id, expectedRevision) => { if (!Number.isSafeInteger(id) || id < 1 || id > 2147483647) throw new Error("SOFA服务配置标识须为正整数"); return write(`ai/admin/providers/${id}/sofa-capabilities`, { expected_revision: expectedRevision }); };

export function sofaReferencesValid(value) {
  if (!value || typeof value !== "object" || Array.isArray(value)) return false;
  const keys = Object.keys(value);
  return keys.length === 1 && ["sofa_assessment_id", "sofa_change_assessment_id"].includes(keys[0]) && supportId(value[keys[0]]);
}

export function sofaPeriodRequest(patientId, admissionId, values) {
  if (!Number.isSafeInteger(patientId) || patientId < 1 || patientId > 2147483647 || !supportId(admissionId)) throw new Error("请选择实际患者及原住院记录");
  const period_start = supportUtc(values.period_start), period_end = supportUtc(values.period_end), as_of = supportUtc(values.as_of);
  const start = observationTime(period_start).microseconds, end = observationTime(period_end).microseconds, cutoff = observationTime(as_of).microseconds;
  if (end - start !== 86400000000n || end > cutoff) throw new Error("SOFA日范围必须恰为24小时，结束不得晚于资料可用截止");
  return { patient_id: patientId, admission_id: admissionId, period_start, period_end, as_of };
}

const object = value => value !== null && typeof value === "object" && !Array.isArray(value);
const pick = (value, names) => Object.fromEntries(names.map(key => [key, value[key]]));
const governanceFields = ["status", "revision", "revoked_at", "revoked_by", "revoke_reason"];
const frozenFields = ["assessment_id", "patient_id", "admission_id", "rule_profile_id", "rule_profile_content_hash", "recipe_digest", "policy_digest", "manifest_digest", "created_by", "schema_version", "period_start", "period_end", "as_of", "evaluation_at", "created_at"];
const clock = value => typeof value === "string" && /^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{6}Z$/.test(value) && supportUtc(value) === value;
const micros = value => observationTime(value).microseconds;
const equal = (left,right) => supportCanonical(left) === supportCanonical(right);
function dependenciesInScope(value, period) {
  if (Array.isArray(value)) return value.every(item => dependenciesInScope(item, period));
  if (!object(value)) return true;
  if (Object.hasOwn(value,"patient_id") && value.patient_id !== period.patient_id || Object.hasOwn(value,"admission_id") && value.admission_id !== period.admission_id) return false;
  for (const key of ["recorded_at","registered_at","available_at","published_at"]) if (value[key] != null && (!clock(value[key]) || micros(value[key]) > micros(period.as_of))) return false;
  return Object.values(value).every(item => dependenciesInScope(item,period));
}
export async function verifySofaProfile(row) {
  try {
    if (!object(row) || row.rule_id !== sofaRuleId || !supportId(row.rule_profile_id) || !supportHash(row.content_hash) || !supportHash(row.governance_hash) || !supportHash(row.recipe_digest) || row.source_id !== `risk_rule_profile:${row.rule_profile_id}:${row.content_hash.slice(0, 12)}` || row.clinical_validation !== "not_provided" || row.review_basis !== "human_implementation_review_not_clinical_validation" || !object(row.recipe) || !object(row.input_policy) || typeof row.implementation_current !== "boolean" || typeof row.eligible !== "boolean" || !Array.isArray(row.exclusion_reasons) || row.exclusion_reasons.some(value => typeof value !== "string") || row.eligible !== (row.exclusion_reasons.length === 0)) return false;
    const content = pick(row, ["rule_profile_id", "schema_version", "created_by", "created_at", "name", "rule_id", "evidence_reference", "rationale", "recipe_digest", "recipe", "input_policy", "clinical_validation", "review_basis"]);
    const governance = pick(row, ["status", "revision", "published_at", "published_by", "implementation_terms_confirmed", "review_note", "review_evidence_reference", "revoked_at", "revoked_by", "revoke_reason"]);
    if (row.status === "draft" ? row.revision !== 1 || row.published_at !== null || row.revoked_at !== null || row.implementation_terms_confirmed !== false : row.status === "published" ? row.revision !== 2 || row.implementation_terms_confirmed !== true || !row.published_at || row.revoked_at !== null : row.status !== "revoked" || ![2, 3].includes(row.revision) || !row.revoked_at || row.eligible) return false;
    return await supportDigest(content) === row.content_hash && await supportDigest(governance) === row.governance_hash && await supportDigest(row.recipe) === row.recipe_digest;
  } catch { return false; }
}

export async function verifySofaManifest(manifest, period) {
  try {
    if (!object(manifest) || manifest.schema_version !== "sofa1_period_manifest_v1" || !supportHash(manifest.content_hash) || Object.keys(period).some(key => manifest[key] !== period[key]) || !Array.isArray(manifest.members) || manifest.members.length > 4096 || !Array.isArray(manifest.conflict_groups)) return false;
    const keys = manifest.members.map(row => row?.member_key);
    if (new Set(keys).size !== keys.length || manifest.members.some(row => !object(row) || typeof row.member_key !== "string" || !row.member_key || !["laboratory", "map", "respiratory_support", "arterial_pair", "vasoactive", "gcs", "urine"].includes(row.kind) || !supportId(row.identifier) || typeof row.source_id !== "string" || !supportHash(row.content_hash) || !supportHash(row.governance_hash) || !["period", "prefix"].includes(row.temporal_role) || typeof row.eligible !== "boolean" || !Array.isArray(row.exclusion_reasons) || row.exclusion_reasons.some(value => typeof value !== "string") || !object(row.full_source) || row.full_source.patient_id !== period.patient_id || row.full_source.admission_id !== period.admission_id || row.full_source.content_hash !== row.content_hash)) return false;
    if (!equal(Object.keys(manifest).sort(),["schema_version","patient_id","admission_id","period_start","period_end","as_of","members","conflict_groups","content_hash"].sort())) return false;
    const content = Object.fromEntries(Object.entries(manifest).filter(([key]) => key !== "content_hash"));
    if (new TextEncoder().encode(supportCanonical(manifest)).length > 8388608 || await supportDigest(content) !== manifest.content_hash) return false;
    const sortKeys=manifest.members.map(row=>`${row.kind}:${row.identifier}`);if(!equal(sortKeys,[...sortKeys].sort()))return false;
    for (const member of manifest.members) {
      const source=member.full_source;
      if (member.member_key!==`${member.kind}:${member.identifier}` || member.source_id!==source.source_id || !dependenciesInScope(source,period) || await supportDigest(pick(source,governanceFields))!==member.governance_hash || source.governance_hash && source.governance_hash!==member.governance_hash) return false;
      const exclusions=[...new Set([...(source.exclusion_reasons||[]),...(source.status!=="active"?["source_revoked"]:[])])].sort();if(member.eligible!==(exclusions.length===0)||!equal(member.exclusion_reasons,exclusions))return false;
      if (member.kind === "laboratory") { if(!await verifySupportLab(source,period.patient_id,period.admission_id))return false; }
      else if (["map","respiratory_support","arterial_pair","vasoactive"].includes(member.kind)) { if(!await verifySupportSource(source,member.kind,period.patient_id,period.admission_id,true))return false; }
      else if (member.kind === "gcs") {
        if (!gcsObservationMatches(source,period.patient_id,period.admission_id) || await supportDigest(pick(source,["gcs_observation_id","patient_id","admission_id","observed_at","recorded_at","created_by","schema_version","payload","anchor_point_snapshot"]))!==source.content_hash || source.anchor_point_snapshot!==null&&!await verifySupportPoint(source.anchor_point_snapshot,period.patient_id,period.admission_id)) return false;
      } else if (await supportDigest(pick(source,["interval_id","patient_id","admission_id","recorded_at","created_by","schema_version","payload","start_at","end_at"]))!==source.content_hash) return false;
      const instant=member.kind==="laboratory"?source.collected_at_utc:member.kind==="gcs"?source.observed_at:member.kind==="map"?source.payload.observed_at:member.kind==="arterial_pair"?source.reference_snapshots.pao2.collected_at_utc:null;
      if (instant!==null && (member.temporal_role!=="period"||!clock(instant)||micros(instant)<micros(period.period_start)||micros(instant)>=micros(period.period_end)))return false;
      if (instant===null) {const p=member.kind==="urine"?source:source.payload,end=p.verified_until_at||p.end_at,start=p.start_at,lower=micros(period.period_start)-(member.kind==="vasoactive"?3600000000n:0n);if(!clock(start)||!clock(end)||micros(start)>=micros(end)||micros(start)>=micros(period.period_end)||micros(end)<=lower||member.temporal_role!== (micros(end)<=micros(period.period_start)?"prefix":"period"))return false;}
    }
    return true;
  } catch { return false; }
}

export function sofaBasisValid(value) { return typeof value === "string" && value.length <= 1000 && Array.from(value).filter(char => !/[\s\u0085\u001c-\u001f]/u.test(char)).length >= 20; }
function basesValid(value) {
  if (Array.isArray(value)) return value.every(basesValid);
  if (!object(value)) return true;
  return Object.entries(value).every(([key, item]) => key.endsWith("basis_note") || key === "mass_basis_note" ? sofaBasisValid(item) : basesValid(item));
}
export function sofaMemberReviewValid(review, member) {
  return !!member && review?.member_key === member.member_key && review.expected_content_hash === member.content_hash && review.kind === member.kind && sofaSchemaMatches("AssessmentCreate", review, sofaReviewDefinitions[member.kind]) && basesValid(review) && (review.status === "excluded") === (review.exclusion_reason !== null) && (member.eligible || review.status === "excluded");
}
export function sofaClinicalRequestValid(values, manifest, profile) {
  if (!sofaSchemaMatches("AssessmentCreate", values) || !basesValid(values) || values.expected_manifest_hash !== manifest?.content_hash || values.rule_profile_id !== profile?.rule_profile_id || values.expected_rule_profile_hash !== profile?.content_hash || profile.status !== "published" || !profile.eligible) return false;
  if (["patient_id", "admission_id", "period_start", "period_end", "as_of"].some(key => values[key] !== manifest[key]) || values.member_reviews.length !== manifest.members.length) return false;
  const reviews = new Map(values.member_reviews.map(row => [row.member_key, row]));
  if (reviews.size !== manifest.members.length || manifest.members.some(row => !sofaMemberReviewValid(reviews.get(row.member_key), row))) return false;
  const drugs = new Set(manifest.members.filter(row => row.kind === "vasoactive").map(row => row.full_source.reference_snapshots?.drug_mapping?.drug_key));
  if (values.vasoactive_group_reviews.length !== drugs.size || new Set(values.vasoactive_group_reviews.map(row => row.drug_key)).size !== drugs.size || values.vasoactive_group_reviews.some(row => !drugs.has(row.drug_key))) return false;
  const conflicts = new Map(values.conflict_reviews.map(row => [row.group_id, row]));
  if (conflicts.size !== manifest.conflict_groups.length || values.conflict_reviews.length !== conflicts.size) return false;
  return manifest.conflict_groups.every(group => {
    const review = conflicts.get(group.group_id), members = group.member_source_ids;
    if (!review || review.expected_group_digest !== group.group_digest || !Array.isArray(members)) return false;
    const accepted = review.accepted_source_ids, excluded = review.excluded_source_ids;
    if (new Set(accepted).size !== accepted.length || new Set(excluded).size !== excluded.length || accepted.some(id => excluded.includes(id))) return false;
    const bySource=new Map(manifest.members.map(member=>[member.source_id,reviews.get(member.member_key)]));
    return review.status === "unresolved" ? !accepted.length && !excluded.length : equal([...accepted, ...excluded].sort(),[...members].sort()) && accepted.every(id=>bySource.get(id)?.status==="confirmed") && excluded.every(id=>bySource.get(id)?.status==="excluded");
  });
}

export async function verifySofaAssessment(row,patientId,admissionId,auditOnly=false) {
  try {
    if(!object(row)||row.patient_id!==patientId||row.admission_id!==admissionId||!supportId(row.assessment_id)||row.schema_version!=="sofa1_assessment_v1"||!supportHash(row.content_hash)||!supportHash(row.governance_hash)||!supportHash(row.projection_hash)||row.source_id!==`sofa_assessment:${row.assessment_id}:${row.content_hash.slice(0,12)}`||typeof row.eligible!=="boolean"||!Array.isArray(row.exclusion_reasons)||row.eligible!==(row.exclusion_reasons.length===0)||!auditOnly&&(row.status!=="active"||!row.eligible)||await supportDigest(pick(row,governanceFields))!==row.governance_hash)return false;
    if(row.status==="active"?row.revision!==1||row.revoked_at!==null||row.revoked_by!==null||row.revoke_reason!=="":row.status!=="revoked"||row.revision!==2||!clock(row.revoked_at)||!Number.isSafeInteger(row.revoked_by)||row.revoked_by<1||!row.revoke_reason.trim()||row.eligible)return false;
    const snapshot=row.snapshot,source=row.specialist_source;
    if(!object(snapshot)||!sofaSchemaMatches("SofaSource",source)||frozenFields.some(key=>snapshot[key]!==row[key])||new TextEncoder().encode(supportCanonical(snapshot)).length>8388608||new TextEncoder().encode(supportCanonical(source)).length>2097152||await supportDigest(snapshot)!==row.content_hash||await supportDigest(source)!==row.projection_hash)return false;
    const period=sofaPeriodRequest(patientId,admissionId,row),profile=snapshot.rule_profile;
    if(!equal(pick(row,["period_start","period_end","as_of"]),pick(period,["period_start","period_end","as_of"]))||!clock(row.evaluation_at)||row.created_at!==row.evaluation_at||micros(row.as_of)>micros(row.evaluation_at)||!await verifySofaManifest(snapshot.manifest,period)||!await verifySofaProfile(profile)||profile.rule_profile_id!==row.rule_profile_id||profile.content_hash!==row.rule_profile_content_hash||profile.recipe_digest!==row.recipe_digest||await supportDigest(profile.input_policy)!==row.policy_digest||snapshot.manifest.content_hash!==row.manifest_digest||!sofaClinicalRequestValid(snapshot.attestation,snapshot.manifest,profile))return false;
    const q=snapshot.author_qualification;
    if(!object(q)||q.actor_id!==row.created_by||q.doctor_user_id!==row.created_by||!Number.isSafeInteger(q.doctor_id)||q.doctor_id<1||!["doctor","director","super_admin"].includes(q.role_at_creation)||q.clinical_review_signed!==true||q.care_authorization!=="authorized_original_admission_at_creation"||q.authorized_at!==row.created_at||snapshot.review_mode!=="current_retrospective_review"||snapshot.historical_prediction!==false||snapshot.clinical_statements_recorded_at!==row.created_at||!equal(snapshot.clinical_scope_applies_to,pick(row,["period_start","period_end"]))||snapshot.source_verification!=="explicit_current_retrospective_human_review_not_independently_verified")return false;
    const roots=new Set(snapshot.manifest.members.filter(member=>member.kind==="respiratory_support").map(member=>member.source_id));
    const origins=Object.fromEntries(snapshot.manifest.members.filter(member=>member.kind==="arterial_pair").map(member=>[member.member_key,{support:roots.has(member.full_source.reference_snapshots.support.source_id)?"root_member":"pair_dependency"}]));
    return equal(snapshot.dependency_review_origins,origins)&&equal(await projectSofaSource(row),source);
  } catch { return false; }
}

export function sofaChangeRequestValid(values,current,baseline,infection){
 try{
  if(!sofaSchemaMatches("ChangeCreate",values)||!basesValid(values)||values.patient_id!==current.patient_id||values.admission_id!==current.admission_id||values.current_assessment_id!==current.assessment_id||values.expected_current_content_hash!==current.content_hash||values.expected_current_projection_hash!==current.projection_hash||values.infection_source_id!==infection.support_source_id||values.expected_infection_content_hash!==infection.content_hash||values.expected_infection_governance_hash!==infection.governance_hash||infection.patient_id!==values.patient_id||infection.admission_id!==values.admission_id||values.infection_review.onset_review==="known"&&infection.payload.onset_at===null)return false;
  if(values.baseline.mode!=="observed")return baseline===null;
  return !!baseline&&baseline.patient_id===current.patient_id&&baseline.assessment_id!==current.assessment_id&&values.baseline.assessment_id===baseline.assessment_id&&values.baseline.expected_content_hash===baseline.content_hash&&values.baseline.expected_projection_hash===baseline.projection_hash&&baseline.period_end<=current.period_start&&baseline.as_of<=current.as_of&&["recipe_digest","policy_digest"].every(key=>baseline[key]===current[key])&&(infection.payload.onset_at===null||baseline.period_end<=infection.payload.onset_at);
 }catch{return false;}
}

export async function verifySofaChangeAssessment(row,patientId,admissionId,auditOnly=false){
 try{
  if(!object(row)||row.patient_id!==patientId||row.admission_id!==admissionId||!supportId(row.change_assessment_id)||row.schema_version!=="sofa1_change_assessment_v1"||!supportHash(row.content_hash)||!supportHash(row.projection_hash)||row.source_id!==`sofa_change_assessment:${row.change_assessment_id}:${row.content_hash.slice(0,12)}`||typeof row.eligible!=="boolean"||!Array.isArray(row.exclusion_reasons)||row.eligible!==(row.exclusion_reasons.length===0)||!auditOnly&&(row.status!=="active"||!row.eligible)||await supportDigest(pick(row,governanceFields))!==row.governance_hash)return false;
  if(row.status==="active"?row.revision!==1||row.revoked_at!==null||row.revoked_by!==null||row.revoke_reason!=="":row.status!=="revoked"||row.revision!==2||!clock(row.revoked_at)||!Number.isSafeInteger(row.revoked_by)||row.revoked_by<1||!row.revoke_reason.trim()||row.eligible)return false;
  const snap=row.snapshot,source=row.specialist_source,fields=["change_assessment_id","patient_id","admission_id","current_assessment_id","baseline_assessment_id","infection_source_id","created_by","schema_version","evaluation_at","created_at"];
  if(!object(snap)||!sofaSchemaMatches("SofaChangeSource",source)||fields.some(key=>snap[key]!==row[key])||!clock(row.evaluation_at)||row.evaluation_at!==row.created_at||new TextEncoder().encode(supportCanonical(snap)).length>8388608||new TextEncoder().encode(supportCanonical(source)).length>6291456||await supportDigest(snap)!==row.content_hash||await supportDigest(source)!==row.projection_hash)return false;
  const current=snap.current_assessment,baseline=snap.baseline_assessment,infection=snap.infection_source,q=snap.author_qualification;
  if(!await verifySofaAssessment(current,patientId,admissionId,auditOnly)||baseline!==null&&!await verifySofaAssessment(baseline,patientId,baseline.admission_id,auditOnly)||!await verifySupportSource(infection,"infection_episode",patientId,admissionId,true)||!sofaChangeRequestValid(snap.attestation,current,baseline,infection)||row.current_assessment_id!==current.assessment_id||row.baseline_assessment_id!==(baseline?.assessment_id??null)||row.infection_source_id!==infection.support_source_id||current.evaluation_at>row.evaluation_at||infection.recorded_at>row.evaluation_at||baseline!==null&&baseline.evaluation_at>row.evaluation_at)return false;
  if(!object(q)||q.actor_id!==row.created_by||q.doctor_user_id!==row.created_by||!Number.isSafeInteger(q.doctor_id)||q.doctor_id<1||!["doctor","director","super_admin"].includes(q.role_at_creation)||q.clinical_review_signed!==true||q.care_authorization!=="authorized_original_admission_at_creation"||q.authorized_at!==row.created_at||snap.review_mode!=="current_retrospective_review"||snap.historical_prediction!==false||snap.clinical_statements_recorded_at!==row.created_at||snap.source_verification!=="explicit_current_retrospective_human_review_not_independently_verified")return false;
  return equal(await projectSofaChangeSource(row),source);
 }catch{return false;}
}

export async function sofaRevocationMatches(row,original,patientId,admissionId,changeMode=false){
 try{const key=changeMode?"change_assessment_id":"assessment_id";return row?.[key]===original[key]&&row.patient_id===patientId&&row.admission_id===admissionId&&row.content_hash===original.content_hash&&row.projection_hash===original.projection_hash&&row.status==="revoked"&&row.revision===original.revision+1&&row.eligible===false&&clock(row.revoked_at)&&Number.isSafeInteger(row.revoked_by)&&row.revoked_by>0&&typeof row.revoke_reason==="string"&&!!row.revoke_reason.trim()&&await supportDigest(pick(row,governanceFields))===row.governance_hash&&(row.snapshot===null&&row.specialist_source===null||await(changeMode?verifySofaChangeAssessment:verifySofaAssessment)(row,patientId,admissionId,true));}catch{return false;}
}

export async function verifySofaContext(packet,patientId,admissionId,references=null){
 try{
  const daily=object(packet?.sofa_source)&&object(packet.sofa_assessment),change=object(packet?.sofa_change_source)&&object(packet.sofa_change_assessment);
  if(daily===change||daily&&(packet.sofa_change_source!=null||packet.sofa_change_assessment!=null)||change&&(packet.sofa_source!=null||packet.sofa_assessment!=null))return false;
  const row=daily?packet.sofa_assessment:packet.sofa_change_assessment,source=daily?packet.sofa_source:packet.sofa_change_source,key=daily?"sofa_assessment_id":"sofa_change_assessment_id",id=daily?row.assessment_id:row.change_assessment_id;
  if(references!==null&&(!sofaReferencesValid(references)||references[key]!==id)||packet.scope!==undefined&&packet.scope!==(daily?"inpatient_sofa1_assessment":"inpatient_sofa1_change")||packet.selected_sources!==undefined&&!equal(packet.selected_sources,{[key]:id}))return false;
  if(!await(daily?verifySofaAssessment:verifySofaChangeAssessment)(row,patientId,admissionId)||!equal(source,row.specialist_source))return false;
  if(packet.sofa_binding!==undefined){const rule=daily?source:source.current,expected={schema_version:"sofa_context_binding_v1",kind:daily?"daily":"change",patient_id:patientId,admission_id:admissionId,assessment_id:id,source_id:source.source_id,content_hash:source.content_hash,governance_hash:source.assessment_governance_hash,projection_hash:row.projection_hash,rule_id:sofaRuleId,recipe_digest:rule.recipe_digest,policy_digest:rule.policy_digest};if(!equal(packet.sofa_binding,expected))return false;}
  return true;
 }catch{return false;}
}

function analysisSourceIds(source){const ids=new Set();function walk(value){if(Array.isArray(value))value.forEach(walk);else if(object(value)){if(typeof value.source_id==="string")ids.add(value.source_id);Object.values(value).forEach(walk);}}walk(source);return ids;}
function rationalValid(value){try{if(!object(value)||typeof value.numerator!=="string"||typeof value.denominator!=="string"||value.numerator==="-0")return false;let a=BigInt(value.numerator),b=BigInt(value.denominator);if(b<=0n)return false;if(a<0n)a=-a;while(b!==0n){const next=a%b;a=b;b=next;}return a===1n;}catch{return false;}}
export async function verifySofaAnalysis(source,analysis,projectionHash=null){
 try{
  if(!sofaSchemaMatches("SofaSource",source)||!sofaSchemaMatches("SofaAnalysis",analysis)||new TextEncoder().encode(supportCanonical(analysis)).length>8388608)return false;
  const digest=await supportDigest(source),binding={...pick(source,["assessment_id","source_id","content_hash","assessment_governance_hash","rule_profile_id","rule_profile_source_id","rule_profile_content_hash","rule_profile_governance_hash","rule_id","recipe_digest","policy_digest","source_set_digest"]),projection_hash:digest};
  if(projectionHash!==null&&digest!==projectionHash||!equal(analysis.source_binding,binding)||analysis.rule_id!==source.rule_id||analysis.recipe_digest!==source.recipe_digest||analysis.policy_digest!==source.policy_digest||analysis.local_runtime.recipe_digest!==source.recipe_digest||analysis.local_runtime.policy_digest!==source.policy_digest||!equal(Object.keys(analysis.local_runtime.core_sha256).sort(),["sofa_contract.py","sofa_model.py","sofa_config.py","sofa_server.py"].sort())||!equal(analysis.domains.map(row=>row.axis),sofaAxes))return false;
  const ids=analysisSourceIds(source),idsValid=values=>new Set(values).size===values.length&&values.every(id=>ids.has(id));
  for(const domain of analysis.domains){if(domain.lower_bound>domain.upper_bound||domain.exact_numeric_score!==(domain.lower_bound===domain.upper_bound?domain.lower_bound:null)||!idsValid(domain.deciding_source_ids))return false;
   const observed=domain.candidates.filter(row=>row.score!==null).map(row=>row.score);if(domain.observed_max_score!==(observed.length?Math.max(...observed):null))return false;
   for(const candidate of domain.candidates){if(candidate.lower_bound>candidate.upper_bound||candidate.score!==null&&(candidate.score!==candidate.lower_bound||candidate.score!==candidate.upper_bound)||!idsValid(candidate.source_ids))return false;for(const proof of candidate.calculations){if(!idsValid(proof.source_ids)||proof.kind!=="continuous_tier"&&!rationalValid(proof.exact))return false;if(proof.kind==="continuous_tier"&&(!clock(proof.start_at)||!clock(proof.end_at)||micros(proof.end_at)-micros(proof.start_at)!==BigInt(proof.duration_microseconds)))return false;}}
  }
  const observed=analysis.domains.filter(row=>row.observed_max_score!==null),complete=analysis.domains.filter(row=>row.protocol_complete),lower=analysis.domains.reduce((sum,row)=>sum+row.lower_bound,0),upper=analysis.domains.reduce((sum,row)=>sum+row.upper_bound,0);
  return analysis.observed_scored_domain_count===observed.length&&analysis.protocol_complete_domain_count===complete.length&&analysis.known_subtotal===(observed.length?observed.reduce((sum,row)=>sum+row.observed_max_score,0):null)&&analysis.lower_bound===lower&&analysis.upper_bound===upper&&analysis.exact_numeric_total===(lower===upper?lower:null)&&(analysis.complete_total_score===null||complete.length===6&&analysis.scope_status==="within_declared_scope"&&analysis.complete_total_score===analysis.exact_numeric_total);
 }catch{return false;}
}

export async function verifySofaChangeAnalysis(source,analysis,projectionHash=null){
 try{
  if(!sofaSchemaMatches("SofaChangeSource",source)||!sofaSchemaMatches("SofaChangeAnalysis",analysis)||new TextEncoder().encode(supportCanonical(analysis)).length>8388608)return false;
  const current=source.current,observed=source.baseline.mode==="observed"?source.baseline.source:null,digest=await supportDigest(source),binding={...pick(source,["change_assessment_id","source_id","content_hash","assessment_governance_hash"]),projection_hash:digest,current_assessment_id:current.assessment_id,current_content_hash:current.content_hash,current_projection_hash:await supportDigest(current),baseline_mode:source.baseline.mode,baseline_assessment_id:observed?.assessment_id??null,baseline_content_hash:observed?.content_hash??null,baseline_projection_hash:observed?await supportDigest(observed):null,infection_source_id:source.infection.source_id,infection_content_hash:source.infection.content_hash,infection_governance_hash:source.infection.governance_hash,rule_id:current.rule_id,recipe_digest:current.recipe_digest,policy_digest:current.policy_digest};
  if(projectionHash!==null&&projectionHash!==digest||!equal(analysis.source_binding,binding)||!await verifySofaAnalysis(current,analysis.current_analysis)||!equal(analysis.local_runtime,analysis.current_analysis.local_runtime)||analysis.instructions_digest!==analysis.current_analysis.instructions_digest||analysis.rule_id!==current.rule_id||analysis.recipe_digest!==current.recipe_digest||analysis.policy_digest!==current.policy_digest||["acute_change","attribution","temporal_relation"].some(key=>analysis[key]!==source.review[key]))return false;
  const baseline=analysis.baseline_analysis;if(baseline.mode!==source.baseline.mode)return false;let lower,upper,total;
  if(observed){if(!await verifySofaAnalysis(observed,baseline.analysis)||baseline.analysis.instructions_digest!==analysis.instructions_digest||!equal(baseline.analysis.local_runtime,analysis.local_runtime))return false;({lower_bound:lower,upper_bound:upper,complete_total_score:total}=baseline.analysis);}
  else{const confirmed=source.baseline.mode==="conditional_zero"&&source.baseline.no_known_preexisting_organ_dysfunction&&source.baseline.preinfection_baseline_assumption_confirmed;lower=0;upper=confirmed?0:24;total=confirmed?0:null;if(baseline.lower_bound!==lower||baseline.upper_bound!==upper||baseline.basis_hash!==source.baseline.basis_hash||source.baseline.mode==="conditional_zero"&&(baseline.assumptions_confirmed!==confirmed||baseline.assumed_total_score!==total))return false;}
  const deltaLower=analysis.current_analysis.lower_bound-upper,deltaUpper=analysis.current_analysis.upper_bound-lower,deltaComplete=analysis.current_analysis.complete_total_score!==null&&total!==null?analysis.current_analysis.complete_total_score-total:null;
  return analysis.delta_lower_bound===deltaLower&&analysis.delta_upper_bound===deltaUpper&&analysis.exact_numeric_delta===(deltaLower===deltaUpper?deltaLower:null)&&analysis.complete_delta===deltaComplete;
 }catch{return false;}
}

export function sofaContextBinding(packet,patientId,admissionId){
 const change=!!packet?.sofa_change_source,source=change?packet.sofa_change_source:packet?.sofa_source,row=change?packet.sofa_change_assessment:packet?.sofa_assessment;if(!source||!row)return null;const rule=change?source.current:source;
 return{schema_version:"sofa_context_binding_v1",kind:change?"change":"daily",patient_id:patientId,admission_id:admissionId,assessment_id:change?row.change_assessment_id:row.assessment_id,source_id:source.source_id,content_hash:source.content_hash,governance_hash:source.assessment_governance_hash,projection_hash:row.projection_hash,rule_id:sofaRuleId,recipe_digest:rule.recipe_digest,policy_digest:rule.policy_digest};
}
export async function resolveSofaEvidence(item,packet,patientId,admissionId,references=null){
 if(!item)return null;const invalid=()=>({...item,title:"SOFA原依据未能核对",content:"原资料索引与当前完整冻结来源不一致，无法展开。"});let index;try{index=JSON.parse(item.content);}catch{return item.kind==="knowledge"?item:invalid();}
 if(item.kind==="knowledge"&&(!object(index)||!Object.hasOwn(index,"sofa_binding")))return item;
 if(!object(index)||Object.keys(index).join(",")!=="sofa_binding"||!await verifySofaContext(packet,patientId,admissionId,references)||!equal(index.sofa_binding,sofaContextBinding(packet,patientId,admissionId)))return invalid();
 const changed=!!packet.sofa_change_source,row=changed?packet.sofa_change_assessment:packet.sofa_assessment,current=changed?row.snapshot.current_assessment:row,candidates=[[row.source_id,"clinical_record",row],[current.snapshot.rule_profile.source_id,"rule",current.snapshot.rule_profile]];
 if(changed){candidates.push([current.source_id,"clinical_record",current],[row.snapshot.infection_source.source_id,"clinical_record",row.snapshot.infection_source]);if(row.snapshot.baseline_assessment)candidates.push([row.snapshot.baseline_assessment.source_id,"clinical_record",row.snapshot.baseline_assessment]);}
 const match=candidates.find(([id,kind])=>id===item.source_id&&kind===item.kind);return match?{...item,title:"本地完整冻结依据（完整正文不发送模型）",content:JSON.stringify(match[2],null,2)}:invalid();
}
