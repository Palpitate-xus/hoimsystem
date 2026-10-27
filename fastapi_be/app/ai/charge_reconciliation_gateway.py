"""One bounded text-provider call for a verified minimal recorded-ledger source."""

import json

import httpx
from fastapi import HTTPException

from app.ai.charge_reconciliation_context import public_payload
from app.ai.charge_reconciliation_draft import MAX_BYTES, ChargeReconciliationDraft
from app.ai.charge_reconciliation_prompt import CHARGE_RECONCILIATION_SYSTEM_PROMPT
from app.ai.charge_reconciliation_protocol import ChargeReplyError, parse_provider_draft
from app.ai.charge_reconciliation_result import result_for_draft
from app.ai.gateway import AIExecutionError, _finite_response_constant, _unique_response_pairs, result_json_schema
from app.ai.governance import encode_json, provider_credential, validate_endpoint
from app.ai.text_retry import text_retries
from app.config import settings


def matches_charge_request(spec, data):
    if spec.number == 69:
        return True
    if not isinstance(data, dict):
        return False
    context, values = data.get("context"), data.get("input")
    return bool(isinstance(context, dict) and {"charge_binding", "charge_source", "charge_case"} & context.keys() or isinstance(values, dict) and "charge_case_id" in values)


def request(provider, spec, task_prompt, data):
    if spec.number != 69 or spec.key != "charge_reconciliation" or provider.kind not in {"chat", "responses"}:
        raise AIExecutionError("CHARGE_TEXT_PROVIDER_REQUIRED", "受审完整账目仅由本功能登记的文本模型处理")
    try:
        if type(task_prompt) is not str or not task_prompt.strip():
            raise ValueError("The complete actual task Prompt is required")
        task_prompt.encode("utf-8", errors="strict")
        visible = public_payload(data)
    except (HTTPException, ValueError, TypeError, KeyError, UnicodeError, RecursionError) as exc:
        raise AIExecutionError("CHARGE_SOURCE_REQUIRED", "须选择本次实际住院受审完整账目并核对唯一公开投影") from exc
    endpoint = validate_endpoint(provider.api_base)
    instructions = CHARGE_RECONCILIATION_SYSTEM_PROMPT + "\n\n" + task_prompt
    budget = min(provider.max_output_tokens, settings.AI_MAX_OUTPUT_TOKENS)
    if provider.kind == "chat":
        payload = {
            "model": provider.model,
            "messages": [{"role": "system", "content": instructions}, {"role": "user", "content": encode_json(visible)}],
            "response_format": {"type": "json_object"},
            "temperature": float(provider.temperature),
            "max_tokens": budget,
        }
        endpoint = endpoint.rstrip("/") + "/chat/completions"
    else:
        payload = {
            "model": provider.model,
            "instructions": instructions,
            "input": encode_json(visible),
            "text": {"format": {"type": "json_schema", "name": "hoim_charge_record_questions", "strict": True, "schema": result_json_schema(ChargeReconciliationDraft)}},
            "max_output_tokens": budget,
            "store": False,
        }
        endpoint = endpoint.rstrip("/") + "/responses"
    if len(encode_json(payload).encode("utf-8", errors="strict")) > MAX_BYTES:
        raise AIExecutionError("CHARGE_REQUEST_LIMIT", "完整账目投影、固定契约和实际Prompt超过8MiB，未发送或截断")
    return endpoint, payload


@text_retries()
async def generate_charge(provider, spec, task_prompt, data, *, transport=None):
    inputs = outputs = None
    attempted = False
    try:
        endpoint, payload = request(provider, spec, task_prompt, data)
        credential = provider_credential(provider)
        headers = {"Accept": "application/json"}
        if credential:
            headers["Authorization"] = "Bearer " + credential
        timeout = httpx.Timeout(provider.timeout_seconds, connect=min(provider.timeout_seconds, 10))
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=False, trust_env=False, transport=transport) as client:
            attempted = True
            async with client.stream("POST", endpoint, json=payload, headers=headers) as response:
                if response.status_code != 200:
                    raise AIExecutionError("PROVIDER_HTTP_ERROR", f"模型服务返回HTTP {response.status_code}，请联系管理员检查配置")
                body = bytearray()
                async for chunk in response.aiter_bytes():
                    body.extend(chunk)
                    if len(body) > MAX_BYTES:
                        raise AIExecutionError("RESPONSE_TOO_LARGE", "完整账目模型响应超过8MiB，未接收或截断")
        parsed = json.loads(body.decode("utf-8", errors="strict"), object_pairs_hook=_unique_response_pairs, parse_constant=_finite_response_constant)
        draft, inputs, outputs = parse_provider_draft(provider.kind, parsed, data["context"]["charge_source"], data["context"]["charge_binding"]["projection_hash"])
        result = result_for_draft(data["context"]["charge_source"], draft, data["context"]["charge_binding"]["projection_hash"])
        return result, inputs, outputs
    except AIExecutionError as exc:
        exc.input_tokens, exc.output_tokens = inputs, outputs
        exc.model_call_attempted = attempted
        raise
    except ChargeReplyError as exc:
        error = AIExecutionError("INVALID_PROVIDER_RESPONSE", "模型未返回完整可核对的账目草稿，未生成可用结果")
        error.input_tokens, error.output_tokens = exc.input_tokens, exc.output_tokens
        error.model_call_attempted = attempted
        raise error from exc
    except HTTPException as exc:
        error = AIExecutionError("PROVIDER_CONFIGURATION", str(exc.detail))
        error.model_call_attempted = attempted
        raise error from exc
    except httpx.TimeoutException as exc:
        error = AIExecutionError("PROVIDER_TIMEOUT", "模型服务响应超时，未自动重试")
        error.model_call_attempted = attempted
        raise error from exc
    except httpx.HTTPError as exc:
        error = AIExecutionError("PROVIDER_UNAVAILABLE", "无法连接模型服务，请联系管理员检查部署")
        error.model_call_attempted = attempted
        raise error from exc
    except (ValueError, TypeError, KeyError, UnicodeError, RecursionError) as exc:
        error = AIExecutionError("INVALID_PROVIDER_RESPONSE", "模型返回了无法核对的完整账目响应，未生成可用结果")
        error.input_tokens, error.output_tokens = inputs, outputs
        error.model_call_attempted = attempted
        raise error from exc
    except Exception as exc:
        error = AIExecutionError("CHARGE_GATEWAY_ERROR", "完整账目模型调用未能正常完成，请联系管理员核对状态")
        error.input_tokens, error.output_tokens = inputs, outputs
        error.model_call_attempted = attempted
        raise error from exc
