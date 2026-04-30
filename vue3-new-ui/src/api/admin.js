import request from "@/utils/request";

export function getDoctorList(keyword = "") {
  return request({ url: "doctorManagement/getList", method: "get", params: { keyword } });
}

export function registerDoctor(data) {
  return request({ url: "doctorManagement/register", method: "post", data });
}

export function updateDoctor(data) {
  return request({ url: "doctorManagement/update", method: "post", data });
}

export function deleteDoctor(data) {
  return request({ url: "doctorManagement/delete", method: "post", data });
}

export function getPatientList(keyword = "") {
  return request({ url: "patientManagement/getList", method: "get", params: { keyword } });
}

export function updatePatient(data) {
  return request({ url: "patientManagement/update", method: "post", data });
}

export function getDepartmentList(keyword = "") {
  return request({ url: "departmentManagement/getList", method: "get", params: { keyword } });
}

export function createDepartment(data) {
  return request({ url: "departmentManagement/create", method: "post", data });
}

export function updateDepartment(data) {
  return request({ url: "departmentManagement/update", method: "post", data });
}

export function deleteDepartment(data) {
  return request({ url: "departmentManagement/delete", method: "post", data });
}

export function getNoticeList(keyword = "") {
  return request({ url: "notice/getList", method: "get", params: { keyword } });
}

export function createNotice(data) {
  return request({ url: "notice/create", method: "post", data });
}

export function updateNotice(data) {
  return request({ url: "notice/update", method: "post", data });
}

export function deleteNotice(data) {
  return request({ url: "notice/delete", method: "post", data });
}
