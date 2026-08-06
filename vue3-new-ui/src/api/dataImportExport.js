import request from "@/utils/request";

export function importData(entity, file) {
  const formData = new FormData();
  formData.append("file", file);
  return request({
    url: `dataImportExport/import/${entity}`,
    method: "post",
    data: formData,
    headers: { "Content-Type": "multipart/form-data" },
  });
}

export function downloadData(entity, template = false) {
  return request({
    url: `dataImportExport/${template ? "template" : "export"}/${entity}`,
    method: "get",
    responseType: "blob",
  });
}
