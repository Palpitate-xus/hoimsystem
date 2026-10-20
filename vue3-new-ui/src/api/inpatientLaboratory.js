import request from "@/utils/request";

const read = (url, params) => request({ url, method: "get", params, retry: 0 });
// Keep explicit nulls in signatures and future source contracts. The shared
// interceptor filters top-level nulls from ordinary object bodies.
const write = (url, data) => request({ url, method: "post", data: JSON.stringify(data), headers: { "Content-Type": "application/json" }, retry: 0 });
const sources = "inpatient-laboratory/sources", mappings = "ai/admin/lab-mappings";
export const getInpatientLabCandidates = params => read("inpatient-laboratory/candidates", params);
export const getInpatientLabSources = params => read(sources, params);
export const getInpatientLabSource = (id, params) => read(`${sources}/${encodeURIComponent(id)}`, params);
export const createInpatientLabSource = data => write(sources, data);
export const revokeInpatientLabSource = (id, data) => write(`${sources}/${encodeURIComponent(id)}/revoke`, data);
export const getLabMappingOptions = () => read(`${mappings}/options`);
export const getLabMappings = params => read(mappings, params);
export const getLabMapping = id => read(`${mappings}/${encodeURIComponent(id)}`);
export const createLabMapping = data => write(mappings, data);
export const publishLabMapping = (id, data) => write(`${mappings}/${encodeURIComponent(id)}/publish`, data);
export const revokeLabMapping = (id, data) => write(`${mappings}/${encodeURIComponent(id)}/revoke`, data);
export const getAdminLabSources = params => read("ai/admin/lab-sources", params);
export const getAdminLabSource = id => read(`ai/admin/lab-sources/${encodeURIComponent(id)}`);

export function labSourceMatches(source, patientId, admissionId) {
  if (source?.patient_id !== patientId || source.admission_id !== admissionId) return false;
  const frozen = source.snapshot;
  if (!frozen) return true;
  if (["lab_source_id", "patient_id", "admission_id", "observation_id", "mapping_id", "schema_version", "raw_original_hash", "mapping_content_hash", "collected_at_utc", "registered_at", "available_at"].some(key => frozen[key] !== source[key])) return false;
  const order = frozen.original?.order;
  const observation = frozen.original?.observation, report = frozen.original?.report;
  return !!order && !!observation && !!report && order.patient_id === patientId && observation.observation_id === source.observation_id && observation.lab_result_id === report.lab_result_id && report.lab_order_id === order.lab_order_id && frozen.mapping?.mapping_id === source.mapping_id;
}
