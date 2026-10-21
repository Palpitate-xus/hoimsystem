"""One billable text request, public comparison only, complete8MiB JSON limits.

This is a dedicated adapter, not an authorization boundary. Its caller resolves
current Source SQL before releasing the transaction. Neither prompts nor private
Scope/target bodies are accepted from the provider. No retry or redirect occurs.
"""

import asyncio
import copy

import httpx
from fastapi import HTTPException

from app.ai import document_change_contract as c
from app.ai.document_change_context import public_payload
from app.ai.document_change_draft import SYSTEM_PROMPT, ProviderReply
from app.ai.document_change_json import parse_case_json, require_case_json
from app.ai.document_change_protocol import DocumentChangeReplyError, parse_provider_draft, reported_usage
from app.ai.document_change_result import result_for_draft
from app.ai.document_extraction_view_contract import DocumentFrozenProvider
from app.ai.gateway import AIExecutionError
from app.ai.governance import provider_credential, validate_endpoint


def _error(code, message, counts=(None, None), attempted=False):
    result = AIExecutionError(code, message)
    result.input_tokens, result.output_tokens = counts
    result.model_call_attempted = attempted
    return result


def _schema():
    schema = copy.deepcopy(ProviderReply.model_json_schema())

    def close(node):
        if isinstance(node, dict):
            node.pop("default", None)
            if node.get("type") == "object":
                node["required"] = list(node.get("properties", {}))
                node["additionalProperties"] = False
            for child in node.values():
                close(child)
        elif isinstance(node, list):
            for child in node:
                close(child)

    close(schema)
    return schema


def build_request(provider, task_prompt, payload, source):
    """Return the exact final HTTP JSON bytes; includes System/Task/schema overhead."""
    from app.ai.runtime import provider_snapshot

    try:
        config = DocumentFrozenProvider.model_validate(provider_snapshot(provider))
        if type(task_prompt) is not str or not task_prompt.strip():
            raise ValueError("The complete frozen Task Prompt is required")
        public = public_payload(payload, source)
        endpoint = validate_endpoint(config.api_base)
        instructions = SYSTEM_PROMPT + "\n\n" + task_prompt
        content = require_case_json(public)
        if config.kind == "chat":
            body = {
                "model": config.model,
                "messages": [{"role": "system", "content": instructions}, {"role": "user", "content": content}],
                "max_tokens": config.effective_output_limit,
                "temperature": config.temperature,
                "response_format": {"type": "json_object"},
                "store": False,
            }
            endpoint += "/chat/completions"
        else:
            body = {
                "model": config.model,
                "instructions": instructions,
                "input": [{"role": "user", "content": content}],
                "max_output_tokens": config.effective_output_limit,
                "store": False,
                "text": {"format": {"type": "json_schema", "name": "hoim_document_change_questions", "strict": True, "schema": _schema()}},
            }
            endpoint += "/responses"
        return endpoint, c.e.utf8(require_case_json(body))
    except HTTPException as exc:
        raise _error("DOCUMENT_CHANGE_CONFIGURATION", str(exc.detail)) from exc
    except (ValueError, TypeError, KeyError, UnicodeError, RecursionError) as exc:
        raise _error("DOCUMENT_CHANGE_REQUEST_REJECTED", "完整版本核对原件、Prompt或协议超过8MiB或未通过闭合核对，未发送或裁剪") from exc


async def generate_document_change(provider, task_prompt, payload, source, *, transport=None):
    """Actual reported counts survive malformed questions and failed acceptance."""
    counts, attempted = (None, None), False
    try:
        endpoint, raw = build_request(provider, task_prompt, payload, source)
        credential = provider_credential(provider)
        headers = {"Accept": "application/json", "Accept-Encoding": "identity", "Content-Type": "application/json"}
        if credential:
            headers["Authorization"] = "Bearer " + credential
        timeout = httpx.Timeout(provider.timeout_seconds, connect=min(provider.timeout_seconds, 10))
        # A read timeout alone is reset by each chunk. The whole upload/response
        # deadline prevents a slow continuous response from occupying a worker.
        async with asyncio.timeout(provider.timeout_seconds):
            async with httpx.AsyncClient(timeout=timeout, follow_redirects=False, trust_env=False, transport=transport) as client:
                attempted = True
                async with client.stream("POST", endpoint, content=raw, headers=headers) as response:
                    if response.headers.get("content-encoding", "identity").strip().lower() != "identity":
                        raise _error("DOCUMENT_CHANGE_RESPONSE_ENCODING", "模型响应须为有界未压缩JSON，未尝试解压", counts, attempted)
                    length = response.headers.get("content-length")
                    if length is not None and (not length.isascii() or not length.isdecimal() or int(length) > c.MAX_CASE_BYTES):
                        raise _error("DOCUMENT_CHANGE_RESPONSE_LIMIT", "模型完整响应超过8MiB或声明长度无效", counts, attempted)
                    body = bytearray()
                    async for chunk in response.aiter_bytes():
                        if len(body) + len(chunk) > c.MAX_CASE_BYTES:
                            raise _error("DOCUMENT_CHANGE_RESPONSE_LIMIT", "模型完整响应超过8MiB，未保存或裁剪", counts, attempted)
                        body.extend(chunk)
                    parsed = parse_case_json(bytes(body))
                    counts = reported_usage(provider.kind, parsed)
                    if response.status_code != 200:
                        raise _error("DOCUMENT_CHANGE_PROVIDER_HTTP", f"模型服务返回HTTP {response.status_code}，未接收草稿", counts, attempted)
        digest = c.e.bytes_hash(SYSTEM_PROMPT + "\n\n" + task_prompt)
        draft, first, second = parse_provider_draft(provider.kind, parsed, source, digest)
        counts = first, second
        return result_for_draft(draft, source, digest), first, second
    except DocumentChangeReplyError as exc:
        raise _error("DOCUMENT_CHANGE_PROVIDER_REPLY", "模型未返回完整逐字问题草稿，未确认影响或修改目标", (exc.input_tokens, exc.output_tokens), attempted) from exc
    except AIExecutionError as exc:
        if not hasattr(exc, "model_call_attempted"):
            exc.model_call_attempted = attempted
        raise
    except HTTPException as exc:
        raise _error("DOCUMENT_CHANGE_CONFIGURATION", str(exc.detail), counts, attempted) from exc
    except (httpx.TimeoutException, TimeoutError) as exc:
        raise _error("DOCUMENT_CHANGE_PROVIDER_TIMEOUT", "模型请求超过完整调用截止，实际用量以已收到记录为准", counts, attempted) from exc
    except httpx.HTTPError as exc:
        raise _error("DOCUMENT_CHANGE_PROVIDER_NETWORK", "模型请求未完整返回，未重试；实际用量可能未知", counts, attempted) from exc
    except asyncio.CancelledError as exc:
        exc.input_tokens, exc.output_tokens, exc.model_call_attempted = *counts, attempted
        raise
    except (ValueError, TypeError, KeyError, UnicodeError, RecursionError) as exc:
        raise _error("DOCUMENT_CHANGE_RESULT_REJECTED", "完整JSON、逐字证据或固定说明未通过核对，未裁剪或修改目标", counts, attempted) from exc
