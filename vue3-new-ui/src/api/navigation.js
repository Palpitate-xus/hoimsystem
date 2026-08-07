import request from "@/utils/request";

export function getNavigationNodesAdmin() {
  return request({ url: "navigation/admin/nodes", method: "get" });
}

export function createNavigationNode(data) {
  return request({ url: "navigation/admin/nodes", method: "post", data });
}

export function deleteNavigationNode(data) {
  return request({ url: "navigation/admin/nodes", method: "delete", data });
}

export function getNavigationEdgesAdmin() {
  return request({ url: "navigation/admin/edges", method: "get" });
}

export function createNavigationEdge(data) {
  return request({ url: "navigation/admin/edges", method: "post", data });
}

export function deleteNavigationEdge(data) {
  return request({ url: "navigation/admin/edges", method: "delete", data });
}
