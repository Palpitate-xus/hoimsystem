import request from "@/utils/request";

export function createBackup() {
  return request({ url: "backup/create", method: "post" });
}

export function getBackupList() {
  return request({ url: "backup/getList", method: "get" });
}

export function deleteBackup(data) {
  return request({ url: "backup/delete", method: "post", data });
}

export function restoreBackup(data) {
  return request({ url: "backup/restore", method: "post", data });
}

export function downloadBackupUrl(filename) {
  return `/api/backup/download/${filename}`;
}
