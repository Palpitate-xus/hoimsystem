"""One bounded75 Chat/Responses call; no SQL and no paid-call retry."""

import httpx

from app.ai.deidentification_draft import bounded_json
from app.ai.deidentification_http import parse_json
from app.ai.deidentification_protocol import DeidentificationReplyError, _usage, build_model_wire, parse_provider_draft, wire_bytes
from app.ai.deidentification_result import build_result
from app.ai.governance import validate_endpoint


class DeidentificationExecutionError(Exception):
    def __init__(self, code, message, inputs=None, outputs=None):
        super().__init__(message)
        self.code, self.message = code, message
        self.input_tokens, self.output_tokens = inputs, outputs


def prepare_request(provider, credential, body, values):
    options = {"max_output_tokens": provider["effective_output_limit"], "temperature": provider["temperature"]}
    if "question" in values:
        options["question"] = values["question"]
    wire = build_model_wire(provider["kind"], provider["model"], body["public_source"], body["prompt"]["task_prompt"], **options)
    wire["response_format"] = {"type": "json_object"} if provider["kind"] == "chat" else None
    if provider["kind"] == "responses":
        del wire["response_format"]
        wire["store"] = False
        wire["text"] = {"format": {"type": "json_object"}}
    # Precheck the final actual wrapper after every adapter field is added.
    raw = wire_bytes(wire)
    endpoint = validate_endpoint(provider["api_base"]) + ("/chat/completions" if provider["kind"] == "chat" else "/responses")
    headers = {"Content-Type": "application/json"}
    if credential:
        headers["Authorization"] = "Bearer " + credential
    return endpoint, headers, raw


async def generate(request, provider, body, *, transport=None, on_attempt=None):
    counts = (None, None)
    try:
        endpoint, headers, raw = request
        async with httpx.AsyncClient(timeout=provider["timeout_seconds"], trust_env=False, follow_redirects=False, transport=transport) as client:
            if on_attempt is not None:
                on_attempt()
            async with client.stream("POST", endpoint, headers=headers, content=raw) as response:
                parts, total = [], 0
                async for part in response.aiter_bytes():
                    total += len(part)
                    if total > 8 * 1024 * 1024:
                        raise DeidentificationExecutionError("RESPONSE_TOO_LARGE", "完整模型响应超8MiB，未截断或重试")
                    parts.append(part)
                value = parse_json(b"".join(parts))
                if isinstance(value, dict):
                    counts = _usage(provider["kind"], value)
                if not response.is_success:
                    raise DeidentificationExecutionError("PROVIDER_HTTP_ERROR", "模型服务返回失败，实际付费用量仅按独立回执保留", *counts)
                draft, inputs, outputs = parse_provider_draft(provider["kind"], value, body["public_source"])
                counts = inputs, outputs
                result = build_result(body["public_source"], draft, body["prompt"]["instructions_digest"])
                bounded_json(result)
                return result, inputs, outputs
    except DeidentificationExecutionError:
        raise
    except DeidentificationReplyError as exc:
        raise DeidentificationExecutionError("PROVIDER_REPLY_INVALID", "模型未返回完整闭集逐字候选，未接收或重试", exc.input_tokens, exc.output_tokens) from exc
    except (ValueError, TypeError, UnicodeError, RecursionError) as exc:
        raise DeidentificationExecutionError("RESULT_INVALID", "完整模型候选、UTF8或容量核验失败，未接收或重试", *counts) from exc
    except httpx.HTTPError as exc:
        raise DeidentificationExecutionError("PROVIDER_TRANSPORT_ERROR", "模型调用中断，实际用量未知且未重试", *counts) from exc
