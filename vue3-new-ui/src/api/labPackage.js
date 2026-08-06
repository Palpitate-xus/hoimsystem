import request from "@/utils/request";

export function getLabPackageList(params) { return request({ url: "/labPackage/list", method: "get", params }); }
export function createLabPackage(data) { return request({ url: "/labPackage/create", method: "post", data }); }
export function updateLabPackage(data) { return request({ url: "/labPackage/update", method: "put", data }); }
