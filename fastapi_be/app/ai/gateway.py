"""Bounded HTTP model adapters with strict results and server-owned citation IDs."""

import copy
import json
from typing import BinaryIO

import httpx
from fastapi import HTTPException
from pydantic import ValidationError

from app.ai.audio_files import AUDIO_FORMATS
from app.ai.catalog import COMMON_SYSTEM_PROMPT, FeatureSpec
from app.ai.governance import encode_json, provider_credential, validate_endpoint
from app.ai.models import AIProvider
from app.ai.schemas import AudioGenerationResult, GenerationResult
from app.config import settings

MAX_RESPONSE_BYTES = 512 * 1024


class AIExecutionError(Exception):
    """A stable error code and safe user message without provider response bodies."""

    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        self.input_tokens = None
        self.output_tokens = None
        super().__init__(message)


def result_json_schema() -> dict:
    """Make all output properties required for strict Structured Outputs."""
    schema = copy.deepcopy(GenerationResult.model_json_schema())

    def visit(node: object) -> None:
        if isinstance(node, dict):
            node.pop("default", None)
            if node.get("type") == "object":
                node["required"] = list(node.get("properties", {}))
                node["additionalProperties"] = False
            for value in node.values():
                visit(value)
        elif isinstance(node, list):
            for value in node:
                visit(value)

    visit(schema)
    return schema


def validate_generation(value: object, evidence: list[dict], requires_knowledge: bool = False, *, audio_source: dict | None = None) -> GenerationResult:
    """Reject fabricated references and invalid structured output before UI exposure."""
    try:
        result = (AudioGenerationResult if audio_source is not None else GenerationResult).model_validate(value)
    except ValidationError as exc:
        raise AIExecutionError("INVALID_OUTPUT", "模型返回的结果不符合任务结构，请调整模型或重试") from exc
    allowed = {item["source_id"] for item in evidence}
    cited = {source for section in result.sections for source in section.source_ids}
    if not cited <= allowed:
        raise AIExecutionError("INVALID_CITATION", "模型引用了未提供的来源，结果已拒绝展示")
    if requires_knowledge and result.sections:
        knowledge_ids = {item["source_id"] for item in evidence if item.get("kind") == "knowledge"}
        if not cited.intersection(knowledge_ids):
            raise AIExecutionError("UNGROUNDED_OUTPUT", "该任务的回答缺少已审核知识依据，结果已拒绝展示")
    if audio_source is not None:
        transcript = result.transcription
        if transcript.asset_id != audio_source["asset_id"] or transcript.content_hash != audio_source["content_hash"]:
            raise AIExecutionError("AUDIO_SOURCE_MISMATCH", "转写结果与所选原录音不一致，结果已拒收")
        previous_start = -1
        for segment in transcript.segments:
            if segment.end_ms > audio_source["duration_ms"] or segment.start_ms < previous_start or segment.source_id != audio_source["source_id"]:
                raise AIExecutionError("INVALID_AUDIO_SEGMENT", "转写时间、顺序或原录音引用不符合实际录音范围，结果已拒收")
            previous_start = segment.start_ms
        if result.sections and audio_source["source_id"] not in cited:
            raise AIExecutionError("UNGROUNDED_TRANSCRIPTION", "转写说明未引用所选原录音，结果已拒收")
    return result


def _request(provider: AIProvider, spec: FeatureSpec, task_prompt: str, data: dict) -> tuple[str, dict]:
    endpoint = validate_endpoint(provider.api_base)
    budget = min(provider.max_output_tokens, settings.AI_MAX_OUTPUT_TOKENS)
    instructions = COMMON_SYSTEM_PROMPT + "\n\n" + task_prompt
    if spec.number == 21 and provider.kind != "specialist":
        raise AIExecutionError("AUDIO_ADAPTER_REQUIRED", "医疗录音须通过已登记的专用语音服务处理")
    if provider.kind == "responses":
        return endpoint + "/responses", {
            "model": provider.model,
            "instructions": instructions,
            "input": [{"role": "user", "content": encode_json(data)}],
            "max_output_tokens": budget,
            "store": False,
            "text": {"format": {"type": "json_schema", "name": "hoim_assistance", "strict": True, "schema": result_json_schema()}},
        }
    if provider.kind == "chat":
        return endpoint + "/chat/completions", {
            "model": provider.model,
            "messages": [{"role": "system", "content": instructions}, {"role": "user", "content": encode_json(data)}],
            "max_tokens": budget,
            "temperature": float(provider.temperature),
            "response_format": {"type": "json_object"},
            "stream": False,
        }
    if provider.kind == "specialist":
        return endpoint + "/tasks", {
            "schema_version": "2" if spec.number == 21 else "1",
            "feature_key": spec.key,
            "engine": spec.engine,
            "model": provider.model,
            "instructions": instructions,
            **({"store": False} if spec.number == 21 else {}),
            "input": data,
        }
    raise AIExecutionError("UNSUPPORTED_PROVIDER", "模型接口类型不受支持")


def _parse_response(provider: AIProvider, spec: FeatureSpec, value: dict) -> tuple[object, int, int]:
    if provider.kind == "responses":
        if value.get("status") != "completed":
            raise AIExecutionError("INCOMPLETE_RESPONSE", "模型响应未完成，请检查输出额度或模型状态")
        content = [part for item in value.get("output", []) if item.get("type") == "message" for part in item.get("content", [])]
        if any(part.get("type") == "refusal" for part in content):
            raise AIExecutionError("MODEL_REFUSAL", "模型未提供可用结果")
        raw = "".join(part.get("text", "") for part in content if part.get("type") == "output_text")
        usage = value.get("usage") or {}
        return json.loads(raw), int(usage.get("input_tokens") or 0), int(usage.get("output_tokens") or 0)
    if provider.kind == "chat":
        choice = value["choices"][0]
        if choice.get("finish_reason") != "stop" or choice["message"].get("refusal"):
            raise AIExecutionError("INCOMPLETE_RESPONSE", "模型未返回完整结果，请检查输出额度或模型状态")
        usage = value.get("usage") or {}
        return json.loads(choice["message"]["content"]), int(usage.get("prompt_tokens") or 0), int(usage.get("completion_tokens") or 0)
    if value.get("schema_version") != ("2" if spec.number == 21 else "1") or value.get("feature_key") != spec.key or value.get("model_version") != provider.model:
        raise AIExecutionError("ADAPTER_CONTRACT_MISMATCH", "专用模型返回的功能或模型版本与登记信息不一致")
    if value.get("applicable") is not True:
        raise AIExecutionError("OUTSIDE_VALIDATED_SCOPE", "本次输入不在专用模型声明的适用范围内")
    if spec.number == 21:
        if not isinstance(value["result"], dict) or "transcription" in value["result"]:
            raise ValueError("transcription belongs to the versioned envelope")
        usage = value.get("usage") or {}
        return {**value["result"], "transcription": value["transcription"]}, int(usage.get("input_tokens") or 0), int(usage.get("output_tokens") or 0)
    return value["result"], 0, 0


async def generate(
    provider: AIProvider,
    spec: FeatureSpec,
    task_prompt: str,
    data: dict,
    *,
    transport: httpx.AsyncBaseTransport | None = None,
    audio: BinaryIO | None = None,
) -> tuple[GenerationResult, int, int]:
    """Call only a configured endpoint; never retry billable tasks or follow redirects."""
    inputs = outputs = None
    try:
        endpoint, payload = _request(provider, spec, task_prompt, data)
        credential = provider_credential(provider)
    except HTTPException as exc:
        raise AIExecutionError("PROVIDER_CONFIGURATION", str(exc.detail)) from exc
    headers = {"Accept": "application/json"}
    if credential:
        headers["Authorization"] = "Bearer " + credential
    source = data.get("context", {}).get("audio_source") if spec.number == 21 else None
    if spec.number == 21:
        if audio is None or not source or source.get("extension") not in AUDIO_FORMATS or source.get("media_type") != AUDIO_FORMATS[source["extension"]][1]:
            raise AIExecutionError("AUDIO_FILE_REQUIRED", "缺少已核实的原录音附件，不能以文字资料冒充语音识别")
        request_body = {"data": {"task": encode_json(payload)}, "files": {"audio": ("recording" + source["extension"], audio, source["media_type"])}}
    else:
        if audio is not None:
            raise AIExecutionError("UNEXPECTED_AUDIO_FILE", "该任务不接受录音附件")
        request_body = {"json": payload}
    try:
        timeout = httpx.Timeout(provider.timeout_seconds, connect=min(provider.timeout_seconds, 10))
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=False, trust_env=False, transport=transport) as client:
            async with client.stream("POST", endpoint, **request_body, headers=headers) as response:
                if response.status_code != 200:
                    raise AIExecutionError("PROVIDER_HTTP_ERROR", f"模型服务返回 HTTP {response.status_code}，请联系管理员检查配置")
                body = bytearray()
                async for chunk in response.aiter_bytes():
                    body.extend(chunk)
                    if len(body) > MAX_RESPONSE_BYTES:
                        raise AIExecutionError("RESPONSE_TOO_LARGE", "模型响应超过允许大小")
        parsed = json.loads(body)
        if not isinstance(parsed, dict):
            raise ValueError("response must be an object")
        output, inputs, outputs = _parse_response(provider, spec, parsed)
        if min(inputs, outputs) < 0 or max(inputs, outputs) > 2000000:
            raise ValueError("invalid token accounting")
        result = validate_generation(output, data.get("evidence", []), spec.requires_knowledge, audio_source=source)
        return result, inputs, outputs
    except AIExecutionError as exc:
        exc.input_tokens, exc.output_tokens = inputs, outputs
        raise
    except httpx.TimeoutException as exc:
        raise AIExecutionError("PROVIDER_TIMEOUT", "模型服务响应超时，请稍后重试或调整模型配置") from exc
    except httpx.HTTPError as exc:
        raise AIExecutionError("PROVIDER_UNAVAILABLE", "无法连接模型服务，请联系管理员检查部署") from exc
    except (ValueError, TypeError, KeyError, IndexError, UnicodeError) as exc:
        raise AIExecutionError("INVALID_PROVIDER_RESPONSE", "模型返回了无法解析的响应，未生成可用建议") from exc
