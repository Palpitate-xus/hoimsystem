"""One complete operations text-model call; caller must close SQL before await."""

import json
import math
import time

import httpx
from fastapi import HTTPException

from app.ai import operations_support_contract as c
from app.ai.governance import provider_credential, validate_endpoint
from app.ai.operations_support_protocol import MAX_BYTES, model_wire, parse_draft
from app.ai.operations_support_usage_contract import usage
from app.ai.text_retry import text_retries

ACTIONS = ("tool_calls", "function_call", "function_calls", "required_action", "actions", "audio", "tool_call_id")


class OperationsCallError(Exception):
    def __init__(self, code, message, receipt=None):
        self.code, self.message = code, message
        self.usage = usage(0, 0, False) if receipt is None else receipt
        super().__init__(message)


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate model envelope key")
        result[key] = value
    return result


def _nonfinite(value):
    raise ValueError("Nonfinite model envelope number")


def _counts(kind, value):
    actual = value.get("usage") if type(value) is dict else None
    actual = actual if type(actual) is dict else {}
    keys = ("prompt_tokens", "completion_tokens") if kind == "chat" else ("input_tokens", "output_tokens")
    return tuple(number if type(number) is int and 0 <= number <= 2147483647 else None for number in (actual.get(key) for key in keys))


def parse_reply(kind, value, source, selection):
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
            raise ValueError("A single completed text response is required")
        reported = value.get("usage")
        if type(reported) is dict and "total_tokens" in reported:
            total = reported["total_tokens"]
            if type(total) is not int or total < 0 or inputs is not None and outputs is not None and total != inputs + outputs:
                raise ValueError("An optional valid total must agree when both actual component counts are known")
            # A total never manufactures an omitted component count. Valid
            # content and independently nullable actual usage are separate.
        if kind == "chat":
            choices = value.get("choices")
            if type(choices) is not list or len(choices) != 1 or type(choices[0]) is not dict:
                raise ValueError("Exactly one choice is required")
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
                raise ValueError("Refused, incomplete, tool or nontext choice is not an operations draft")
            raw = message["content"]
        else:
            output = value.get("output")
            if (
                value.get("status") != "completed"
                or type(output) is not list
                or any(type(item) is not dict or item.get("type") not in {"reasoning", "message"} or any(item.get(key) is not None for key in ACTIONS) for item in output)
            ):
                raise ValueError("Response output cannot contain any external action")
            if any(item.get("type") == "reasoning" and item.get("status") not in {None, "completed"} for item in output):
                raise ValueError("Incomplete reasoning item")
            messages = [item for item in output if item.get("type") == "message"]
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
                raise ValueError("Only complete text parts are accepted")
            length = 0
            for part in parts:
                length += len(part["text"].encode("utf-8"))
                if length > MAX_BYTES:
                    raise ValueError("All text parts together exceed the full response budget")
            raw = "".join(part["text"] for part in parts)
        return parse_draft(raw, source, selection), receipt
    except (ValueError, TypeError, KeyError, UnicodeError, RecursionError) as exc:
        raise OperationsCallError("INVALID_OPERATIONS_RESPONSE", "模型未返回完整可引用的运维草稿，未接收结果", receipt) from exc


def request(provider, source, selection, task_prompt):
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
            or not 0 <= float(provider.temperature) <= 2
        ):
            raise ValueError("Explicit configured provider parameters required")
        wire, instructions_hash = model_wire(source, selection, task_prompt)
        endpoint = validate_endpoint(provider.api_base)
        from app.config import settings

        budget = min(provider.max_output_tokens, settings.AI_MAX_OUTPUT_TOKENS)
        if provider.kind == "chat":
            visible = {**wire["input"], "response_schema": wire["response_schema"]}
            payload = {
                "model": provider.model,
                "messages": [{"role": "system", "content": wire["instructions"]}, {"role": "user", "content": c.canonical_json(visible)}],
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
                "input": c.canonical_json(wire["input"]),
                "text": {"format": {"type": "json_schema", "name": "hoim_operations_support_draft", "strict": True, "schema": wire["response_schema"]}},
                "max_output_tokens": budget,
                "store": False,
            }
            endpoint += "/responses"
        if len(c.canonical_json(payload).encode("utf-8")) > MAX_BYTES:
            raise OperationsCallError("OPERATIONS_REQUEST_LIMIT", "完整运维Source、Prompt和实际模型请求超过8MiB，未发送或截断")
        return endpoint, payload, instructions_hash
    except OperationsCallError:
        raise
    except (ValueError, TypeError, KeyError, AttributeError, UnicodeError, RecursionError, HTTPException) as exc:
        raise OperationsCallError("OPERATIONS_REQUEST_INVALID", "当前运维来源、目标、Prompt或模型参数不能形成完整请求") from exc


@text_retries()
async def generate_operations(provider, source, selection, task_prompt, *, transport=None):
    attempted = False
    started = time.monotonic()
    try:
        endpoint, payload, _ = request(provider, source, selection, task_prompt)
        credential = provider_credential(provider)
        headers = {"Accept": "application/json", "Content-Type": "application/json"}
        if credential:
            headers["Authorization"] = "Bearer " + credential
        timeout = httpx.Timeout(provider.timeout_seconds, connect=min(provider.timeout_seconds, 10))
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=False, trust_env=False, transport=transport) as client:
            attempted = True
            async with client.stream("POST", endpoint, content=c.canonical_json(payload).encode("utf-8"), headers=headers) as response:
                if response.status_code != 200:
                    raise OperationsCallError("PROVIDER_HTTP_ERROR", "运维模型服务未返回成功状态；未自动重试", usage(None, None, True))
                body = bytearray()
                async for chunk in response.aiter_bytes():
                    if len(body) + len(chunk) > MAX_BYTES:
                        raise OperationsCallError("OPERATIONS_RESPONSE_LIMIT", "运维模型完整响应超过8MiB，未接收或截断", usage(None, None, True))
                    body.extend(chunk)
        value = json.loads(body.decode("utf-8", errors="strict"), object_pairs_hook=_object, parse_constant=_nonfinite)
        draft, receipt = parse_reply(provider.kind, value, source, selection)
        return draft, receipt, max(0, int((time.monotonic() - started) * 1000))
    except OperationsCallError:
        raise
    except HTTPException as exc:
        raise OperationsCallError("PROVIDER_CONFIGURATION", "运维模型凭据或请求配置不可用", usage(None, None, True) if attempted else usage(0, 0, False)) from exc
    except httpx.TimeoutException as exc:
        raise OperationsCallError("PROVIDER_TIMEOUT", "运维模型服务超时；实际用量未知且未自动重试", usage(None, None, True) if attempted else usage(0, 0, False)) from exc
    except httpx.HTTPError as exc:
        raise OperationsCallError("PROVIDER_UNAVAILABLE", "运维模型连接失败；未自动重试", usage(None, None, True) if attempted else usage(0, 0, False)) from exc
    except (ValueError, TypeError, KeyError, AttributeError, UnicodeError, RecursionError) as exc:
        raise OperationsCallError("INVALID_OPERATIONS_RESPONSE", "运维模型未返回唯一键、有限数值和完整UTF8响应", usage(None, None, True) if attempted else usage(0, 0, False)) from exc
    except Exception as exc:
        # Preserve the actual HTTP-entry flag when an unexpected transport or
        # response-processing exception has no independently reported usage.
        raise OperationsCallError("OPERATIONS_DELIVERY_INTERRUPTED", "运维模型交付意外中断；实际未知用量保持未知，未自动重试", usage(None, None, True) if attempted else usage(0, 0, False)) from exc
