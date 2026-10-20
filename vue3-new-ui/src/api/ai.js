import request from "@/utils/request";

const admin = "ai/admin";

export const getAIFeatures = () => request({ url: "ai/features", method: "get" });
export const getAIPatients = (params) => request({ url: "ai/patients", method: "get", params });
export const getAIEncounters = (params) => request({ url: "ai/encounters", method: "get", params });
export const getAIPrescriptions = (params) => request({ url: "ai/prescriptions", method: "get", params });
export const getAIServiceOptions = (params) => request({ url: "ai/service-options", method: "get", params });
export const getAIClinicalContext = ({ feature_key, patient_id, encounter_ref, ...source_refs }) => request({ url: "ai/context", method: "post", data: { feature_key, patient_id, encounter_ref, source_refs } });
export const createAIRun = (data) => request({ url: "ai/runs", method: "post", data });
export const getAIRuns = (params = {}) => request({ url: "ai/runs", method: "get", params });
export const getAIRun = (id) => request({ url: `ai/runs/${id}`, method: "get" });
export const cancelAIRun = (id) => request({ url: `ai/runs/${id}/cancel`, method: "post" });
export const reviewAIRun = (id, data) => request({ url: `ai/runs/${id}/feedback`, method: "post", data });

export const getAIAdminFeatures = () => request({ url: `${admin}/features`, method: "get" });
export const saveAIFeature = (key, data) => request({ url: `${admin}/features/${key}`, method: "put", data });
export const getAIProviders = () => request({ url: `${admin}/providers`, method: "get" });
export const saveAIProvider = (id, data) => request({ url: id ? `${admin}/providers/${id}` : `${admin}/providers`, method: id ? "put" : "post", data });
export const getAIPrompts = (key) => request({ url: `${admin}/prompts/${key}`, method: "get" });
export const createAIPrompt = (key, data) => request({ url: `${admin}/prompts/${key}`, method: "post", data });
export const activateAIPrompt = (key, data) => request({ url: `${admin}/prompts/${key}/activate`, method: "post", data });
export const getAIKnowledge = () => request({ url: `${admin}/knowledge`, method: "get" });
export const getAIKnowledgeDetail = (id) => request({ url: `${admin}/knowledge/${id}`, method: "get" });
export const createAIKnowledge = (data) => request({ url: `${admin}/knowledge`, method: "post", data });
export const reviewAIKnowledge = (id, data) => request({ url: `${admin}/knowledge/${id}/review`, method: "post", data });
export const getAIPatientGrants = () => request({ url: `${admin}/grants`, method: "get" });
export const createAIPatientGrant = (data) => request({ url: `${admin}/grants`, method: "post", data });
export const revokeAIPatientGrant = (id) => request({ url: `${admin}/grants/${id}`, method: "delete" });
export const getAIAudit = () => request({ url: `${admin}/audit`, method: "get" });
export const getAIUsage = () => request({ url: `${admin}/usage`, method: "get" });
export const getAIAdminRuns = (params) => request({ url: `${admin}/runs`, method: "get", params });
export const getAIAdminRunTrace = (id) => request({ url: `${admin}/runs/${id}`, method: "get" });
