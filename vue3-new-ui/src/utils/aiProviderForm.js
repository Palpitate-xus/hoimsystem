export function providerAttemptLimit(provider = {}) {
  if (provider?.kind === "specialist") return 1;
  return provider != null && Object.prototype.hasOwnProperty.call(provider, "max_attempts") ? provider.max_attempts : 3;
}

export function createProviderForm(row) {
  return {
    name: row?.name || "", kind: row?.kind || "chat", api_base: row?.api_base || "", model: row?.model || "",
    api_key: "", api_key_env: row?.api_key_env || "", clear_api_key: false,
    enabled: !!row?.enabled, allows_patient_data: !!row?.allows_patient_data,
    timeout_seconds: row?.timeout_seconds || 30, max_output_tokens: row?.max_output_tokens || 2000,
    max_attempts: providerAttemptLimit(row),
    temperature: Number(row?.temperature ?? 0.2), supported_features: [...(row?.supported_features || [])],
    validation_report: row?.validation_report || "", expected_revision: row?.revision || 0,
  };
}

export function providerWritePayload(form) {
  return { ...form, max_attempts: providerAttemptLimit(form), api_key: form.api_key || null };
}
