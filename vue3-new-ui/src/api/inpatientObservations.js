import request from "@/utils/request";

const sources = "inpatient-observations";
const windows = "ai/observation-windows";
const read = (url, params) => request({ url, method: "get", params, retry: 0 });
// The shared interceptor drops top-level nulls from plain objects. These explicit
// JSON contracts must retain unknown volume, absent reason and collection scope.
const write = (url, data) => request({ url, method: "post", data: JSON.stringify(data), headers: { "Content-Type": "application/json" }, retry: 0 });

export const getInpatientPoints = params => read(`${sources}/points`, params);
export const getInpatientPoint = (id, params) => read(`${sources}/points/${encodeURIComponent(id)}`, params);
export const createInpatientPoint = data => write(`${sources}/points`, data);
export const revokeInpatientPoint = (id, data) => write(`${sources}/points/${encodeURIComponent(id)}/revoke`, data);
export const getUrineIntervals = params => read(`${sources}/urine-intervals`, params);
export const getUrineInterval = (id, params) => read(`${sources}/urine-intervals/${encodeURIComponent(id)}`, params);
export const createUrineInterval = data => write(`${sources}/urine-intervals`, data);
export const revokeUrineInterval = (id, data) => write(`${sources}/urine-intervals/${encodeURIComponent(id)}/revoke`, data);
export const getObservationWindows = params => read(windows, params);
export const getObservationWindow = (id, params) => read(`${windows}/${encodeURIComponent(id)}`, params);
export const createObservationWindow = data => write(windows, data);
export const revokeObservationWindow = (id, data) => write(`${windows}/${encodeURIComponent(id)}/revoke`, data);
export const getAdminObservationWindows = params => read("ai/admin/observation-windows", params);
export const getAdminObservationWindow = id => read(`ai/admin/observation-windows/${encodeURIComponent(id)}`);

// Return the entered ISO verbatim, including its offset and up to six fractional
// digits. Integer microseconds are used only to compare window boundaries.
export function observationTime(value) {
  const text = String(value ?? "").trim();
  const match = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.(\d{1,6}))?(Z|[+-]\d{2}:\d{2})$/.exec(text);
  if (!match) throw new Error("时间须为带时区的完整ISO，例如 2026-10-20T08:30:00.123456+08:00");
  const [, year, month, day, hour, minute, second, fraction = "", zone] = match;
  const y = Number(year), m = Number(month), d = Number(day);
  const days = [31, y % 4 === 0 && (y % 100 !== 0 || y % 400 === 0) ? 29 : 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31];
  const base = Date.parse(`${year}-${month}-${day}T${hour}:${minute}:${second}${zone}`);
  const utcYear = new Date(base).getUTCFullYear();
  if (y < 1 || m < 1 || m > 12 || d < 1 || d > days[m - 1] || Number(hour) > 23 || Number(minute) > 59 || Number(second) > 59 || (zone !== "Z" && (Number(zone.slice(1, 3)) > 23 || Number(zone.slice(4)) > 59)) || !Number.isFinite(base) || utcYear < 1 || utcYear > 9999) throw new Error("请输入合法的日期、时间和时区");
  return { text, microseconds: BigInt(base) * 1000n + BigInt(fraction.padEnd(6, "0")) };
}

export const observationMetricFields = Object.freeze([
  { key: "heart_rate", label: "心率", unit: "/min" },
  { key: "pulse_rate", label: "脉搏", unit: "/min" },
  { key: "respiratory_rate", label: "呼吸率", unit: "/min" },
  { key: "systolic_bp", label: "收缩压", unit: "mm[Hg]" },
  { key: "diastolic_bp", label: "舒张压", unit: "mm[Hg]" },
  { key: "temperature", label: "体温", unit: "Cel" },
  { key: "spo2", label: "SpO₂", unit: "%" },
  { key: "body_weight", label: "体重", unit: "kg" },
  { key: "oxygen_flow", label: "氧流量", unit: "L/min" },
  { key: "fio2", label: "FiO₂", unit: "%" },
]);
export const observationAbsentReasons = Object.freeze({ unknown: "未知", not_performed: "未测量", measurement_error: "测量失败" });
export const observationOxygenLabels = Object.freeze({ yes: "正在吸氧", no: "未吸氧", unknown: "吸氧情况未知" });

export function observationWindowMatches(row, patientId, admissionId) {
  if (row?.patient_id !== patientId || row.admission_id !== admissionId) return false;
  if (row.snapshot == null) return true;
  const snapshot = row.snapshot;
  return snapshot.window_id === row.window_id && snapshot.patient_id === patientId && snapshot.admission_id === admissionId && Array.isArray(snapshot.points) && Array.isArray(snapshot.urine_intervals) && [...snapshot.points, ...snapshot.urine_intervals].every(item => item?.patient_id === patientId && item.admission_id === admissionId);
}
