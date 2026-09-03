import request from "@/utils/request";

export const getOperationalTrend = (params = {}) => request({ url: "/analytics/operations", method: "get", params });
export const refreshOperationalMetric = (params = {}) => request({ url: "/analytics/refresh", method: "post", params });
export const getIntegrationOutbox = (params = {}) => request({ url: "/integration/outbox", method: "get", params });
export const retryIntegrationEvent = (eventId) => request({ url: `/integration/outbox/${eventId}/retry`, method: "post" });
export const getIntegrationReconciliation = () => request({ url: "/integration/reconciliation", method: "get" });
