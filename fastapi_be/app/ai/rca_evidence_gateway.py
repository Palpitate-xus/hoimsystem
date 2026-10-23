"""One bounded RCA text attempt; no SQL, retries, redirects or external tools."""

import asyncio
import math
from decimal import Decimal

import httpx
from fastapi import HTTPException

from app.ai import rca_evidence_contract as c
from app.ai.gateway import AIExecutionError, result_json_schema
from app.ai.governance import provider_credential, validate_endpoint
from app.ai.rca_evidence_protocol import RcaEvidenceReplyError, parse_provider_draft
from app.ai.rca_evidence_result import result_for_draft
from app.ai.rca_evidence_task_contract import instructions_digest, public_payload
from app.ai.rca_evidence_task_prompt import SYSTEM_PROMPT
from app.config import settings


class RcaEvidenceGatewayError(AIExecutionError):
    def __init__(self, code, message, *, inputs=None, outputs=None, attempted=False):
        super().__init__(code, message)
        self.input_tokens = inputs
        self.output_tokens = outputs
        self.model_call_attempted = attempted


def build_request(provider, task_prompt, data):
    if type(provider.kind) is not str or provider.kind not in {"chat", "responses"} or type(provider.allows_patient_data) is not int or provider.allows_patient_data != 1:
        raise RcaEvidenceGatewayError("RCA_PROVIDER_SCOPE", "受审事件资料须使用明确获准处理病例相关资料的文字模型")
    try:
        if type(task_prompt) is not str or not task_prompt.strip() or len(c.utf8(task_prompt)) > 65535:
            raise ValueError("The whole actual Task prompt is required")
        if type(provider.model) is not str or not provider.model.strip() or len(c.utf8(provider.model)) > 800:
            raise ValueError("The exact configured model identity is required")
        public = public_payload(data)
        endpoint = validate_endpoint(provider.api_base)
        if type(provider.max_output_tokens) is not int or type(settings.AI_MAX_OUTPUT_TOKENS) is not int:
            raise ValueError("Actual integer output-token limits required")
        limit = min(provider.max_output_tokens, settings.AI_MAX_OUTPUT_TOKENS)
        if not 1 <= limit <= 16000 or type(provider.timeout_seconds) is not int or not 3 <= provider.timeout_seconds <= 120:
            raise ValueError("Actual bounded output/time limits required")
        instruction = SYSTEM_PROMPT + "\n\n" + task_prompt
        if provider.kind == "responses":
            payload = {
                "model": provider.model,
                "instructions": instruction,
                "input": [{"role": "user", "content": c.canonical(public)}],
                "max_output_tokens": limit,
                "store": False,
                "text": {"format": {"type": "json_schema", "name": "hoim_rca_unverified_hypotheses", "strict": True, "schema": result_json_schema(c.ProviderDraft)}},
            }
            suffix = "/responses"
        else:
            if type(provider.temperature) is bool or not isinstance(provider.temperature, (int, float, Decimal)):
                raise ValueError("The explicit real provider temperature is required")
            temperature = float(provider.temperature)
            if not math.isfinite(temperature) or not 0 <= temperature <= 2:
                raise ValueError("The explicit real provider temperature must be finite within its configured domain")
            payload = {
                "model": provider.model,
                "messages": [{"role": "system", "content": instruction}, {"role": "user", "content": c.canonical(public)}],
                "max_tokens": limit,
                "temperature": temperature,
                "store": False,
                "response_format": {"type": "json_object"},
            }
            suffix = "/chat/completions"
        raw = c.utf8(c.canonical(payload))
        return endpoint + suffix, raw, c.validate_source(public["rca_source"]), instructions_digest(SYSTEM_PROMPT, task_prompt)
    except (HTTPException, ValueError, TypeError, KeyError, UnicodeError, OverflowError) as exc:
        raise RcaEvidenceGatewayError("RCA_REQUEST_REJECTED", "完整受审来源、任务提示、服务配置或含协议头的整个8MiB请求无法核对；未发送或裁剪") from exc


async def generate_rca_evidence(provider, task_prompt, data, *, transport=None):
    attempted = False
    inputs = outputs = None
    try:
        endpoint, raw, source, instructions = build_request(provider, task_prompt, data)
        credential = provider_credential(provider)
        headers = {"Accept": "application/json", "Content-Type": "application/json"}
        if credential:
            headers["Authorization"] = "Bearer " + credential
        timeout = httpx.Timeout(provider.timeout_seconds, connect=min(provider.timeout_seconds, 10))
        # A timeout per received chunk alone does not bound a slow endless stream.
        async with asyncio.timeout(provider.timeout_seconds):
            async with httpx.AsyncClient(timeout=timeout, follow_redirects=False, trust_env=False, transport=transport) as client:
                attempted = True
                async with client.stream("POST", endpoint, content=raw, headers=headers) as response:
                    if response.status_code != 200:
                        raise RcaEvidenceGatewayError("PROVIDER_HTTP_ERROR", f"模型服务返回HTTP{response.status_code}，未接受调查草稿", attempted=True)
                    body = bytearray()
                    async for chunk in response.aiter_bytes():
                        if len(body) + len(chunk) > c.MAX_WIRE_BYTES:
                            raise RcaEvidenceGatewayError("RCA_RESPONSE_LIMIT", "完整模型响应超过8MiB；未截断接受", attempted=True)
                        body.extend(chunk)
        parsed = c._strict_reply(bytes(body).decode("utf-8", errors="strict"))
        try:
            draft, inputs, outputs = parse_provider_draft(provider.kind, parsed, source, instructions)
        except RcaEvidenceReplyError as exc:
            raise RcaEvidenceGatewayError(
                "RCA_PROVIDER_REPLY_INVALID", "模型未返回完整逐字调查假设或真实用量；未改写事件/RCA/PDCA", inputs=exc.input_tokens, outputs=exc.output_tokens, attempted=True
            ) from exc
        return result_for_draft(draft, source, instructions), inputs, outputs
    except RcaEvidenceGatewayError:
        raise
    except (httpx.HTTPError, HTTPException, ValueError, TypeError, KeyError, UnicodeError, TimeoutError) as exc:
        raise RcaEvidenceGatewayError("RCA_PROVIDER_ERROR", "本次模型请求或完整结果无法接受；实际未知用量保持未知", inputs=inputs, outputs=outputs, attempted=attempted) from exc
    except Exception as exc:
        # An unexpected transport/service exception is not evidence of an
        # uncalled model. Preserve this layer's actual attempted flag and any
        # independently received counters; never leave the worker's initial0.
        raise RcaEvidenceGatewayError("RCA_PROVIDER_ERROR", "本次模型请求发生未分类异常；实际未知用量保持未知", inputs=inputs, outputs=outputs, attempted=attempted) from exc
