"""One complete text-model call, only after caller-held research authorization.

This adapter grants no research, clinical or export permission from a Source
hash. The dedicated execution service must current-authorize before dispatch
and acceptance, releasing every SQL transaction before this awaited function.
"""

import json
import math
import time

import httpx
from fastapi import HTTPException

from app.ai.governance import provider_credential, validate_endpoint
from app.ai.research_cohort_contract import canonical_json
from app.ai.research_cohort_draft import MAX_BYTES
from app.ai.research_cohort_protocol import _nonfinite, _object, model_wire, parse_draft_json
from app.ai.research_cohort_receipts import usage

ACTIONS = ("tool_calls", "function_call", "function_calls", "required_action", "actions", "audio", "tool_call_id")


class ResearchCallError(Exception):
    """Safe technical failure plus actual independent nullable usage, no body."""

    def __init__(self, code, message, receipt=None):
        self.code, self.message = code, message
        self.usage = receipt if receipt is not None else usage(0, 0, False)
        super().__init__(message)


def _counts(kind, value):
    original = value.get("usage") if type(value) is dict else None
    original = original if type(original) is dict else {}
    names = ("prompt_tokens", "completion_tokens") if kind == "chat" else ("input_tokens", "output_tokens")
    values = tuple(original.get(key) for key in names)
    return tuple(value if type(value) is int and 0 <= value <= 2147483647 else None for value in values)


def parse_reply(kind, value, source):
    """Retain separately known counts even when the returned content is refused."""
    inputs, outputs = _counts(kind, value)
    receipt = usage(inputs, outputs, True)
    try:
        if (
            kind not in {"chat", "responses"}
            or type(value) is not dict
            or value.get("error") is not None
            or value.get("incomplete_details") is not None
            or any(value.get(key) is not None for key in ACTIONS)
        ):
            raise ValueError("Only a complete configured text response is accepted")
        original_usage = value.get("usage")
        if (
            type(original_usage) is dict
            and "total_tokens" in original_usage
            and (inputs is None or outputs is None or type(original_usage["total_tokens"]) is not int or original_usage["total_tokens"] != inputs + outputs)
        ):
            raise ValueError("An optional total receipt must agree with two actual known counts")
        if kind == "chat":
            choices = value.get("choices")
            if type(choices) is not list or len(choices) != 1 or type(choices[0]) is not dict:
                raise ValueError("Exactly one assistant choice is required")
            choice = choices[0]
            message = choice.get("message")
            if (
                choice.get("finish_reason") != "stop"
                or "index" in choice
                and (type(choice["index"]) is not int or choice["index"] != 0)
                or any(choice.get(key) is not None for key in ACTIONS)
                or type(message) is not dict
                or message.get("role") != "assistant"
                or message.get("refusal") is not None
                or any(message.get(key) is not None for key in ACTIONS)
                or type(message.get("content")) is not str
            ):
                raise ValueError("Refused, incomplete, tool or nontext choice is not a research draft")
            raw = message["content"]
        else:
            output = value.get("output")
            if (
                value.get("status") != "completed"
                or type(output) is not list
                or any(type(item) is not dict or item.get("type") not in {"reasoning", "message"} or any(item.get(key) is not None for key in ACTIONS) for item in output)
            ):
                raise ValueError("A complete text response cannot contain an external action")
            if any(item.get("type") == "reasoning" and item.get("status") not in {None, "completed"} for item in output):
                raise ValueError("The reasoning item is incomplete")
            messages = [item for item in output if item["type"] == "message"]
            if len(messages) != 1 or messages[0].get("role") != "assistant" or messages[0].get("status") != "completed" or messages[0].get("refusal") is not None:
                raise ValueError("Exactly one completed assistant message is required")
            parts = messages[0].get("content")
            if (
                type(parts) is not list
                or not parts
                or any(
                    type(part) is not dict
                    or part.get("type") != "output_text"
                    or type(part.get("text")) is not str
                    or part.get("refusal") is not None
                    or any(part.get(key) is not None for key in ACTIONS)
                    for part in parts
                )
            ):
                raise ValueError("Refused or nontext content is not a draft")
            total = 0
            for part in parts:
                total += len(part["text"].encode("utf-8", errors="strict"))
                if total > MAX_BYTES:
                    raise ValueError("The whole completed text exceeds its UTF8 budget")
            raw = "".join(part["text"] for part in parts)
        return parse_draft_json(raw, source), receipt
    except (ValueError, TypeError, KeyError, UnicodeError, RecursionError, HTTPException) as exc:
        raise ResearchCallError("INVALID_RESEARCH_RESPONSE", "模型未返回完整可核对的科研待核问题草稿，未接收临床结果", receipt) from exc


def request(provider, source, question, task_prompt):
    """The actual arbitrary authorized versioned Task follows fixed System."""
    try:
        if (
            provider.kind not in {"chat", "responses"}
            or type(provider.model) is not str
            or not provider.model.strip()
            or type(provider.timeout_seconds) is not int
            or not 1 <= provider.timeout_seconds <= 300
            or type(provider.max_output_tokens) is not int
            or not 1 <= provider.max_output_tokens <= 1000000
            or not math.isfinite(float(provider.temperature))
        ):
            raise ValueError("The complete provider parameters must be explicit")
        wire, instructions_hash = model_wire(source, question, task_prompt)
        endpoint = validate_endpoint(provider.api_base)
        from app.config import settings

        budget = min(provider.max_output_tokens, settings.AI_MAX_OUTPUT_TOKENS)
        if provider.kind == "chat":
            visible = {**wire["input"], "response_schema": wire["response_schema"]}
            payload = {
                "model": provider.model,
                "messages": [{"role": "system", "content": wire["instructions"]}, {"role": "user", "content": canonical_json(visible)}],
                "response_format": {"type": "json_object"},
                "temperature": float(provider.temperature),
                "max_tokens": budget,
                "store": False,
            }
            endpoint += "/chat/completions"
        else:
            payload = {
                "model": provider.model,
                "instructions": wire["instructions"],
                "input": canonical_json(wire["input"]),
                "text": {"format": {"type": "json_schema", "name": "hoim_research_cohort_questions", "strict": True, "schema": wire["response_schema"]}},
                "max_output_tokens": budget,
                "store": False,
            }
            endpoint += "/responses"
        if len(canonical_json(payload).encode("utf-8")) > MAX_BYTES:
            raise ResearchCallError("RESEARCH_REQUEST_LIMIT", "科研完整Source、Prompt、schema与实际模型请求超过8MiB，未发送或截断")
        return endpoint, payload, instructions_hash
    except ResearchCallError:
        raise
    except (ValueError, TypeError, KeyError, AttributeError, UnicodeError, RecursionError, HTTPException) as exc:
        raise ResearchCallError("RESEARCH_REQUEST_INVALID", "当前授权科研Source、问题、Prompt或模型参数不能形成完整请求") from exc


async def generate_research(provider, source, question, task_prompt, *, transport=None):
    """No retries/redirects/tools or SQL; no provider body enters error text."""
    attempted = False
    started = time.monotonic()
    try:
        endpoint, payload, _ = request(provider, source, question, task_prompt)
        credential = provider_credential(provider)
        headers = {"Accept": "application/json", "Content-Type": "application/json"}
        if credential:
            headers["Authorization"] = "Bearer " + credential
        timeout = httpx.Timeout(provider.timeout_seconds, connect=min(provider.timeout_seconds, 10))
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=False, trust_env=False, transport=transport) as client:
            attempted = True
            async with client.stream("POST", endpoint, content=canonical_json(payload).encode("utf-8"), headers=headers) as response:
                if response.status_code != 200:
                    raise ResearchCallError("PROVIDER_HTTP_ERROR", "科研模型服务未返回成功状态；未自动重试", usage(None, None, True))
                body = bytearray()
                async for chunk in response.aiter_bytes():
                    if len(body) + len(chunk) > MAX_BYTES:
                        raise ResearchCallError("RESEARCH_RESPONSE_LIMIT", "科研模型完整响应超过8MiB，未接收或截断", usage(None, None, True))
                    body.extend(chunk)
        value = json.loads(body.decode("utf-8", errors="strict"), object_pairs_hook=_object, parse_constant=_nonfinite)
        draft, receipt = parse_reply(provider.kind, value, source)
        return draft, receipt, max(0, int((time.monotonic() - started) * 1000))
    except ResearchCallError:
        raise
    except HTTPException as exc:
        raise ResearchCallError("PROVIDER_CONFIGURATION", "模型凭据或实际请求配置不可用", usage(None, None, True) if attempted else usage(0, 0, False)) from exc
    except httpx.TimeoutException as exc:
        raise ResearchCallError("PROVIDER_TIMEOUT", "科研模型服务超时；实际用量未知且未自动重试", usage(None, None, True)) from exc
    except httpx.HTTPError as exc:
        raise ResearchCallError("PROVIDER_UNAVAILABLE", "科研模型服务连接失败；未自动重试", usage(None, None, True) if attempted else usage(0, 0, False)) from exc
    except (ValueError, TypeError, KeyError, AttributeError, UnicodeError, RecursionError) as exc:
        raise ResearchCallError("INVALID_RESEARCH_RESPONSE", "科研模型未返回唯一键、有限数值和完整UTF8响应", usage(None, None, True) if attempted else usage(0, 0, False)) from exc
