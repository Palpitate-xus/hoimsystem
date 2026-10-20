import request from "@/utils/request";
import { supportCanonical, supportDigest, supportHash, supportId, supportUtc } from "@/api/inpatientSupport";
const base = "ai/admin/vasoactive-drug-mappings";
const read = (url, params) => request({ url, method: "get", params, retry: 0 });
const write = (url, data) => request({ url, method: "post", data: JSON.stringify(data), headers: { "Content-Type": "application/json" }, retry: 0 });
export const getVasoactiveMappingOptions = params => read(`${base}/options`, params);
export const getVasoactiveMappings = params => read(base, params);
export const getVasoactiveMapping = id => read(`${base}/${encodeURIComponent(id)}`);
export const createVasoactiveMapping = data => write(base, data);
export const publishVasoactiveMapping = (id, data) => write(`${base}/${encodeURIComponent(id)}/publish`, data);
export const revokeVasoactiveMapping = (id, data) => write(`${base}/${encodeURIComponent(id)}/revoke`, data);
export const mappingContentKeys = ["mapping_id", "schema_version", "name", "source_namespace", "pharmaceutical_id", "expected_original_drug_identity_hash", "drug_key", "active_moiety_basis", "allowed_rate_units", "evidence_reference", "rationale", "original_drug_identity", "created_by", "created_at"];
export const mappingGovernanceKeys = ["status", "revision", "published_at", "published_by", "review_note", "revoked_at", "revoked_by", "revoke_reason"];
export async function verifyVasoactiveMapping(row) {
  try {
    if (!row || !supportId(row.mapping_id) || !row.original_drug_identity || Object.keys(row.original_drug_identity).sort().join(",") !== "barcode,name,pharmaceutical_id" || typeof row.original_drug_identity.name !== "string" || !row.original_drug_identity.name.trim() || ![null,"string"].includes(row.original_drug_identity.barcode === null ? null : typeof row.original_drug_identity.barcode) || typeof row.created_at !== "string" || supportUtc(row.created_at) !== row.created_at || !Number.isSafeInteger(row.created_by) || row.created_by < 1 || row.schema_version !== "vasoactive_drug_mapping_v1" || !supportHash(row.content_hash) || !supportHash(row.governance_hash) || !supportHash(row.identity_hash) || row.source_id !== `vasoactive_drug_mapping:${row.mapping_id}:${row.content_hash.slice(0,12)}` || !["draft","published","revoked"].includes(row.status) || !Number.isInteger(row.revision) || typeof row.original_identity_current !== "boolean" || typeof row.eligible !== "boolean" || !Array.isArray(row.exclusion_reasons) || row.eligible !== (row.exclusion_reasons.length === 0) || row.original_drug_identity?.pharmaceutical_id !== row.pharmaceutical_id || !Number.isSafeInteger(row.pharmaceutical_id) || row.pharmaceutical_id < 1 || !["dopamine","dobutamine","epinephrine","norepinephrine","other"].includes(row.drug_key) || !["base","salt","unknown"].includes(row.active_moiety_basis) || !Array.isArray(row.allowed_rate_units) || !row.allowed_rate_units.length || new Set(row.allowed_rate_units).size !== row.allowed_rate_units.length || row.allowed_rate_units.some(unit => !["ug/kg/min","ug/min","mg/h","mL/h"].includes(unit))) return false;
    const content = Object.fromEntries(mappingContentKeys.map(key=>[key,row[key]])), governance=Object.fromEntries(mappingGovernanceKeys.map(key=>[key,row[key]]));
    if (new TextEncoder().encode(supportCanonical(content)).length > 32768) return false;
    if (await supportDigest(content) !== row.content_hash || await supportDigest(governance) !== row.governance_hash || await supportDigest(row.original_drug_identity) !== row.expected_original_drug_identity_hash || await supportDigest({source_namespace:row.source_namespace,original_drug_identity:row.original_drug_identity}) !== row.identity_hash) return false;
    for (const key of ["published_at","revoked_at"]) if (row[key] !== null && (typeof row[key] !== "string" || supportUtc(row[key]) !== row[key] || row[key] < row.created_at)) return false;
    const emptyPublish = row.published_at === null && row.published_by === null && row.review_note === "", emptyRevoke = row.revoked_at === null && row.revoked_by === null && row.revoke_reason === "";
    return row.status === "draft" ? row.revision === 1 && emptyPublish && emptyRevoke : row.status === "published" ? row.revision === 2 && !emptyPublish && emptyRevoke && Number.isSafeInteger(row.published_by) && row.published_by > 0 && typeof row.review_note === "string" && row.review_note.trim().length >= 20 : [2,3].includes(row.revision) && !emptyRevoke && Number.isSafeInteger(row.revoked_by) && row.revoked_by > 0 && typeof row.revoke_reason === "string" && row.revoke_reason.trim().length >= 5 && (row.revision === 2 ? emptyPublish : !emptyPublish);
  } catch { return false; }
}
export const sameMappingContent = (left,right) => supportCanonical(Object.fromEntries(mappingContentKeys.map(key=>[key,left[key]]))) === supportCanonical(Object.fromEntries(mappingContentKeys.map(key=>[key,right[key]])));
