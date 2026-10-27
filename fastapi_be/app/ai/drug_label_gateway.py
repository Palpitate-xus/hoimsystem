"""Validated text requests with bounded transient transport retries and no SQL."""

import hashlib

import httpx
from fastapi import HTTPException

from app.ai import document_evidence_contract as d
from app.ai.drug_label_context_contract import public_payload
from app.ai.drug_label_draft import MAX_JSON_BYTES, SYSTEM_PROMPT, ProviderReply
from app.ai.drug_label_protocol import DrugLabelReplyError, parse_provider_draft
from app.ai.drug_label_result import result_for_draft
from app.ai.gateway import AIExecutionError, result_json_schema
from app.ai.governance import provider_credential, validate_endpoint
from app.ai.text_retry import text_retries
from app.config import settings


class DrugLabelGatewayError(AIExecutionError):
    def __init__(self, code, message, *, inputs=None, outputs=None, attempted=False):
        super().__init__(code, message)
        self.input_tokens = inputs
        self.output_tokens = outputs
        self.model_call_attempted = attempted


def build_request(provider, task_prompt, data):
    if provider.kind not in {"chat", "responses"} or provider.allows_patient_data != 1:
        raise DrugLabelGatewayError("DRUG_LABEL_PROVIDER_SCOPE", "完整说明书须由明确获准处理原文的文字模型服务读取")
    if type(task_prompt) is not str or not task_prompt.strip():
        raise DrugLabelGatewayError("DRUG_LABEL_PROMPT_REQUIRED", "须保留本功能完整原样任务提示")
    try:
        public = public_payload(data)
        endpoint = validate_endpoint(provider.api_base)
        limit = min(provider.max_output_tokens, settings.AI_MAX_OUTPUT_TOKENS)
        if type(limit) is not int or not 1 <= limit <= 16000 or type(provider.timeout_seconds) is not int or not 3 <= provider.timeout_seconds <= 120:
            raise ValueError("Actual output/time limits required")
        instruction = SYSTEM_PROMPT + "\n\n" + task_prompt
        if provider.kind == "responses":
            payload = {
                "model": provider.model,
                "instructions": instruction,
                "input": [{"role": "user", "content": d.canonical_json(public)}],
                "max_output_tokens": limit,
                "store": False,
                "text": {"format": {"type": "json_schema", "name": "hoim_drug_label_literal_fields", "strict": True, "schema": result_json_schema(ProviderReply)}},
            }
            suffix = "/responses"
        else:
            payload = {
                "model": provider.model,
                "messages": [{"role": "system", "content": instruction}, {"role": "user", "content": d.canonical_json(public)}],
                "max_tokens": limit,
                "temperature": float(provider.temperature),
                "response_format": {"type": "json_object"},
            }
            suffix = "/chat/completions"
        raw = d.utf8(d.canonical_json(payload))
        if len(raw) > MAX_JSON_BYTES:
            raise ValueError("Complete provider wrapper exceeds 8MiB")
        return endpoint + suffix, raw, public["drug_label_source"], hashlib.sha256(d.utf8(instruction)).hexdigest()
    except (HTTPException, ValueError, TypeError, KeyError, UnicodeError) as exc:
        raise DrugLabelGatewayError("DRUG_LABEL_REQUEST_REJECTED", "完整来源、提示、模型配置或整个请求容量无法核对；未发送或裁剪") from exc


@text_retries()
async def generate_drug_label(provider, task_prompt, data, *, transport=None):
    endpoint, raw, source, instructions = build_request(provider, task_prompt, data)
    attempted = False
    inputs = outputs = None
    try:
        credential = provider_credential(provider)
        headers = {"Accept": "application/json", "Content-Type": "application/json"}
        if credential:
            headers["Authorization"] = "Bearer " + credential
        timeout = httpx.Timeout(provider.timeout_seconds, connect=min(provider.timeout_seconds, 10))
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=False, trust_env=False, transport=transport) as client:
            attempted = True
            async with client.stream("POST", endpoint, content=raw, headers=headers) as response:
                if response.status_code != 200:
                    raise DrugLabelGatewayError("PROVIDER_HTTP_ERROR", f"模型服务返回 HTTP {response.status_code}，未接受说明书草稿", attempted=True)
                body = bytearray()
                async for chunk in response.aiter_bytes():
                    if len(body) + len(chunk) > MAX_JSON_BYTES:
                        raise DrugLabelGatewayError("DRUG_LABEL_RESPONSE_LIMIT", "模型完整响应超过8MiB；未截断接受", attempted=True)
                    body.extend(chunk)
        parsed = d.parse_json(bytes(body).decode("utf-8", errors="strict"))
        try:
            draft, inputs, outputs = parse_provider_draft(provider.kind, parsed, source, instructions)
        except DrugLabelReplyError as exc:
            raise DrugLabelGatewayError(
                "DRUG_LABEL_PROVIDER_REPLY_INVALID", "模型未返回完整逐字字段草稿或明确用量；未新增目录或临床规则", inputs=exc.input_tokens, outputs=exc.output_tokens, attempted=True
            ) from exc
        return result_for_draft(draft, source, instructions), inputs, outputs
    except DrugLabelGatewayError:
        raise
    except (httpx.HTTPError, HTTPException, ValueError, TypeError, KeyError, UnicodeError) as exc:
        raise DrugLabelGatewayError("DRUG_LABEL_PROVIDER_ERROR", "说明书模型请求或完整结果无法接受，请核对任务实际用量", inputs=inputs, outputs=outputs, attempted=attempted) from exc
