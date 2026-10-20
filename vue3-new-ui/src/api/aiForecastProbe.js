import request from "@/utils/request";

export const checkAIForecastProvider = (id, revision) => request({ url: `ai/admin/providers/${id}/forecast-capabilities`, method: "post", data: { expected_revision: revision }, timeout: 15000 });
