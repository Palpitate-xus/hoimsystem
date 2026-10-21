"""One bounded text-provider call after current satisfaction Source authorization.

The caller expands current authorized Source data before entering this pure HTTP
adapter. Only the closed safe Source and question leave the hospital boundary;
this module does not grant authority from a public hash or frozen audit proof.
"""

import json

import httpx
from fastapi import HTTPException

from app.ai.gateway import AIExecutionError, _finite_response_constant, _unique_response_pairs, result_json_schema
from app.ai.governance import provider_credential, validate_endpoint
from app.ai.satisfaction_context import public_payload
from app.ai.satisfaction_draft import MAX_BYTES, SatisfactionEvidenceDraft, canonical_json
from app.ai.satisfaction_prompt import SATISFACTION_SYSTEM_PROMPT
from app.ai.satisfaction_protocol import SatisfactionReplyError, parse_provider_draft
from app.ai.satisfaction_result import result_for_draft
from app.config import settings

TASK_BYTES = 65535


def matches_satisfaction_request(spec, data):
    """Retained markers must never fall back to a generic feature adapter."""
    if spec.number == 70 or spec.key == "feedback_analysis":
        return True
    if not isinstance(data, dict):
        return False
    context, values = data.get("context"), data.get("input")
    return bool(isinstance(context, dict) and {"satisfaction_binding", "satisfaction_source", "satisfaction_case"} & context.keys() or isinstance(values, dict) and "satisfaction_case_id" in values)


def request(provider, spec, task_prompt, data):
    if spec.number != 70 or spec.key != "feedback_analysis" or provider.kind not in {"chat", "responses"}:
        raise AIExecutionError("SATISFACTION_TEXT_PROVIDER_REQUIRED", "受审评价证据仅由本功能登记的文本模型处理")
    try:
        # Actual versioned Task may differ from the default. Runtime binds its
        # current immutable Prompt/version before and after the model call.
        if type(task_prompt) is not str or not task_prompt.strip() or len(task_prompt.encode("utf-8", errors="strict")) > TASK_BYTES:
            raise ValueError("The actual versioned Task must be a complete nonempty UTF8 scalar within TEXT bytes")
        visible = public_payload(data)
    except (HTTPException, ValueError, TypeError, KeyError, AttributeError, UnicodeError, RecursionError) as exc:
        raise AIExecutionError("SATISFACTION_SOURCE_REQUIRED", "须核对当前完整评价来源及其唯一安全投影，不得混入原评论或其他范围") from exc
    endpoint = validate_endpoint(provider.api_base)
    instructions = SATISFACTION_SYSTEM_PROMPT + "\n\n" + task_prompt
    budget = min(provider.max_output_tokens, settings.AI_MAX_OUTPUT_TOKENS)
    if provider.kind == "chat":
        payload = {
            "model": provider.model,
            "messages": [{"role": "system", "content": instructions}, {"role": "user", "content": canonical_json(visible)}],
            "response_format": {"type": "json_object"},
            "temperature": float(provider.temperature),
            "max_tokens": budget,
            "store": False,
        }
        endpoint = endpoint.rstrip("/") + "/chat/completions"
    else:
        payload = {
            "model": provider.model,
            "instructions": instructions,
            "input": canonical_json(visible),
            "text": {"format": {"type": "json_schema", "name": "hoim_satisfaction_partial_themes", "strict": True, "schema": result_json_schema(SatisfactionEvidenceDraft)}},
            "max_output_tokens": budget,
            "store": False,
        }
        endpoint = endpoint.rstrip("/") + "/responses"
    if len(canonical_json(payload).encode("utf-8", errors="strict")) > MAX_BYTES:
        raise AIExecutionError("SATISFACTION_REQUEST_LIMIT", "完整安全评价来源、固定契约和本次Prompt超过8MiB，未发送或截断")
    return endpoint, payload


async def generate_satisfaction(provider, spec, task_prompt, data, *, transport=None):
    inputs = outputs = None
    attempted = False
    try:
        endpoint, payload = request(provider, spec, task_prompt, data)
        credential = provider_credential(provider)
        headers = {"Accept": "application/json", "Content-Type": "application/json"}
        if credential:
            headers["Authorization"] = "Bearer " + credential
        timeout = httpx.Timeout(provider.timeout_seconds, connect=min(provider.timeout_seconds, 10))
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=False, trust_env=False, transport=transport) as client:
            attempted = True
            async with client.stream("POST", endpoint, content=canonical_json(payload).encode("utf-8"), headers=headers) as response:
                if response.status_code != 200:
                    raise AIExecutionError("PROVIDER_HTTP_ERROR", f"模型服务返回HTTP {response.status_code}，请联系管理员检查配置")
                body = bytearray()
                async for chunk in response.aiter_bytes():
                    if len(body) + len(chunk) > MAX_BYTES:
                        raise AIExecutionError("RESPONSE_TOO_LARGE", "评价模型完整响应超过8MiB，未接收或截断")
                    body.extend(chunk)
        parsed = json.loads(body.decode("utf-8", errors="strict"), object_pairs_hook=_unique_response_pairs, parse_constant=_finite_response_constant)
        draft, inputs, outputs = parse_provider_draft(provider.kind, parsed, data["context"]["satisfaction_source"])
        return result_for_draft(data["context"]["satisfaction_source"], draft), inputs, outputs
    except AIExecutionError as exc:
        exc.input_tokens, exc.output_tokens = inputs, outputs
        exc.model_call_attempted = attempted
        raise
    except SatisfactionReplyError as exc:
        error = AIExecutionError("INVALID_PROVIDER_RESPONSE", "模型未返回完整可核对的部分摘录主题草稿，未生成可用结果")
        error.input_tokens, error.output_tokens = exc.input_tokens, exc.output_tokens
        error.model_call_attempted = attempted
        raise error from exc
    except HTTPException as exc:
        error = AIExecutionError("PROVIDER_CONFIGURATION", str(exc.detail))
        error.model_call_attempted = attempted
        raise error from exc
    except httpx.TimeoutException as exc:
        error = AIExecutionError("PROVIDER_TIMEOUT", "评价模型服务响应超时，未自动重试")
        error.model_call_attempted = attempted
        raise error from exc
    except httpx.HTTPError as exc:
        error = AIExecutionError("PROVIDER_UNAVAILABLE", "无法连接评价模型服务，请联系管理员检查部署")
        error.model_call_attempted = attempted
        raise error from exc
    except (ValueError, TypeError, KeyError, AttributeError, UnicodeError, RecursionError) as exc:
        error = AIExecutionError("INVALID_PROVIDER_RESPONSE", "模型返回了无法核对的完整评价响应，未生成可用结果")
        error.input_tokens, error.output_tokens = inputs, outputs
        error.model_call_attempted = attempted
        raise error from exc
    except Exception as exc:
        error = AIExecutionError("SATISFACTION_GATEWAY_ERROR", "评价模型调用未能正常完成，请联系管理员核对状态")
        error.input_tokens, error.output_tokens = inputs, outputs
        error.model_call_attempted = attempted
        raise error from exc
