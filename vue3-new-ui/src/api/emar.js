import request from "@/utils/request";

export const getMedicationExecutions = (params = {}) =>
  request({ url: "/inpatientOrder/getExecutionList", method: "get", params: { ...params, medication_only: true } });
export const verifyMedication = (data) => request({ url: "/emar/verify", method: "post", data });
export const administerMedication = (data) => request({ url: "/emar/administer", method: "post", data });
export const getMedicationAdministrations = (params = {}) => request({ url: "/emar/list", method: "get", params });
export const setMedicationBarcode = (data) => request({ url: "/emar/medication/barcode", method: "post", data });
