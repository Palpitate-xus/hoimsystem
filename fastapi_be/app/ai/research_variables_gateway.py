"""One76 text attempt with a whole-wire bound and real nullable usage.

All SQL authority/configuration belongs to the preceding committed dispatch.
This module receives only detached frozen values and an already resolved secret;
it never opens a Session, retries, follows redirects, enables tools or uses RAG.
"""

import asyncio

import httpx
from fastapi import HTTPException

from app.ai.gateway import AIExecutionError, result_json_schema
from app.ai.governance import validate_endpoint
from app.ai.research_variables_draft import VariableDraft
from app.ai.research_variables_protocol import VariableReplyError, parse_provider_draft
from app.ai.research_variables_storage_contract import checked_snapshot, instructions_digest
from app.ai.research_variables_task_binding import VariableTaskBinding
from app.ai.research_variables_task_contract import MAX_WIRE_BYTES, canonical, strict_json, validate_frozen_source
from app.ai.research_variables_task_result import result_for_draft


class VariableGatewayError(AIExecutionError):
    def __init__(self, code, message, *, inputs=None, outputs=None, attempted=False):
        super().__init__(code, message)
        self.input_tokens, self.output_tokens = inputs, outputs
        self.model_call_attempted = attempted


def build_request(snapshot, binding, source):
    try:
        binding = VariableTaskBinding.model_validate(binding)
        snapshot = checked_snapshot(snapshot, binding)
        source = validate_frozen_source(source.model_dump(mode="json") if hasattr(source, "model_dump") else source, binding.source_projection_hash)
        if source.external_model_use != "recorded_permitted":
            raise ValueError("The original Source explicitly permitting model use is required")
        provider = snapshot.provider_snapshot
        if provider.allows_patient_data is not True:
            raise ValueError("The actual provider explicitly permitting patient data is required")
        endpoint = validate_endpoint(provider.api_base)
        instruction = snapshot.system_prompt + "\n\n" + snapshot.task_prompt
        public = {"research_variable_source": source.model_dump(mode="json"), "question": snapshot.payload.input.question}
        if provider.kind == "responses":
            payload = {
                "model": provider.model,
                "instructions": instruction,
                "input": [{"role": "user", "content": canonical(public)}],
                "max_output_tokens": provider.effective_output_limit,
                "store": False,
                "text": {"format": {"type": "json_schema", "name": "hoim_research_variable_literal_draft", "strict": True, "schema": result_json_schema(VariableDraft)}},
            }
            suffix = "/responses"
        else:
            payload = {
                "model": provider.model,
                "messages": [{"role": "system", "content": instruction}, {"role": "user", "content": canonical(public)}],
                "max_tokens": provider.effective_output_limit,
                "temperature": provider.temperature,
                "store": False,
                "response_format": {"type": "json_object"},
            }
            suffix = "/chat/completions"
        raw = canonical(payload).encode("utf-8", errors="strict")
        return endpoint + suffix, raw, source, instructions_digest(snapshot), provider
    except (HTTPException, ValueError, TypeError, KeyError, AttributeError, UnicodeError) as exc:
        raise VariableGatewayError("VARIABLE_REQUEST_REJECTED", "完整已授权来源、固定Prompt、实际模型或含协议头的8MiB请求无法核对；未发送或截断") from exc


async def generate_research_variables(snapshot, binding, source, *, credential, transport=None):
    attempted = False
    inputs = outputs = None
    try:
        endpoint, raw, source, instructions, provider = build_request(snapshot, binding, source)
        if type(credential) is not str or len(credential.encode("utf-8", errors="strict")) > 8192 or any(ord(char) < 32 or ord(char) == 127 for char in credential):
            raise ValueError("An actual bounded header-safe credential must be resolved before dispatch without logging it")
        credential.encode("ascii", errors="strict")
        headers = {"Accept": "application/json", "Content-Type": "application/json"}
        if credential:
            headers["Authorization"] = "Bearer " + credential
        timeout = httpx.Timeout(provider.timeout_seconds, connect=min(provider.timeout_seconds, 10))
        async with asyncio.timeout(provider.timeout_seconds):
            async with httpx.AsyncClient(timeout=timeout, follow_redirects=False, trust_env=False, transport=transport) as client:
                attempted = True
                async with client.stream("POST", endpoint, content=raw, headers=headers) as response:
                    if response.status_code != 200:
                        raise VariableGatewayError("VARIABLE_PROVIDER_HTTP", f"模型返回HTTP{response.status_code}，未接受科研变量草稿", attempted=True)
                    body = bytearray()
                    async for chunk in response.aiter_bytes():
                        if len(body) + len(chunk) > MAX_WIRE_BYTES:
                            raise VariableGatewayError("VARIABLE_RESPONSE_LIMIT", "完整模型响应超过8MiB，未截断接受", attempted=True)
                        body.extend(chunk)
        parsed = strict_json(bytes(body).decode("utf-8", errors="strict"))
        try:
            draft, inputs, outputs = parse_provider_draft(provider.kind, parsed, source, instructions)
        except VariableReplyError as exc:
            raise VariableGatewayError("VARIABLE_REPLY_INVALID", "模型未返回完整逐字候选或合法实际用量；未形成变量矩阵", inputs=exc.input_tokens, outputs=exc.output_tokens, attempted=True) from exc
        return result_for_draft(draft, source, instructions), inputs, outputs
    except VariableGatewayError:
        raise
    except (httpx.HTTPError, HTTPException, ValueError, TypeError, KeyError, UnicodeError, TimeoutError) as exc:
        raise VariableGatewayError("VARIABLE_PROVIDER_ERROR", "本次模型请求或完整草稿未能接受；未知用量保持未知", inputs=inputs, outputs=outputs, attempted=attempted) from exc
    except Exception as exc:
        # Preserve this layer's observed call flag instead of leaking an
        # untyped service/transport error into the worker's initial0/0 state.
        raise VariableGatewayError("VARIABLE_PROVIDER_ERROR", "本次模型请求发生未分类异常；实际未知用量保持未知", inputs=inputs, outputs=outputs, attempted=attempted) from exc
