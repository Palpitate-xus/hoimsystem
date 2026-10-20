"""Bounded HTTP model adapters with strict results and server-owned citation IDs."""

import copy
import hashlib
import json
from decimal import Decimal, InvalidOperation
from typing import BinaryIO

import httpx
from fastapi import HTTPException
from pydantic import ValidationError

from app.ai.audio_files import AUDIO_FORMATS
from app.ai.catalog import COMMON_SYSTEM_PROMPT, FeatureSpec
from app.ai.ecg_model import LABELS, LEADS, PREPROCESSING, RELEASE_FILES, ECGModelManifest, canonical_json
from app.ai.governance import encode_json, provider_credential, validate_endpoint
from app.ai.models import AIProvider
from app.ai.schemas import AudioGenerationResult, ECGGenerationResult, GenerationResult
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


def validate_generation(value: object, evidence: list[dict], requires_knowledge: bool = False, *, audio_source: dict | None = None, ecg_source: dict | None = None, instructions_digest: str | None = None, model_version: str | None = None) -> GenerationResult:
    """Reject fabricated references and invalid structured output before UI exposure."""
    try:
        schema = AudioGenerationResult if audio_source is not None else ECGGenerationResult if ecg_source is not None else GenerationResult
        result = schema.model_validate(value)
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
        processing = transcript.processing
        if model_version and model_version.startswith("fw:") and (processing is None or model_version != "fw:" + processing.runtime_digest):
            raise AIExecutionError("SPEECH_RUNTIME_MISMATCH", "本地识别缺少登记模型的运行版本与完整处理报告")
        if processing and (abs(processing.decoded_duration_ms - audio_source["duration_ms"]) > 1 or (instructions_digest and processing.instructions_digest != instructions_digest)):
            raise AIExecutionError("SPEECH_PROCESSING_MISMATCH", "识别处理范围或任务Prompt与原录音任务不一致")
        previous_start = -1
        for segment in transcript.segments:
            if segment.end_ms > audio_source["duration_ms"] or segment.start_ms < previous_start or segment.source_id != audio_source["source_id"]:
                raise AIExecutionError("INVALID_AUDIO_SEGMENT", "转写时间、顺序或原录音引用不符合实际录音范围，结果已拒收")
            previous_start = segment.start_ms
        if result.sections and audio_source["source_id"] not in cited:
            raise AIExecutionError("UNGROUNDED_TRANSCRIPTION", "转写说明未引用所选原录音，结果已拒收")
    if ecg_source is not None:
        analysis, metadata = result.ecg_analysis, ecg_source["signal_metadata"]
        processing = analysis.processing
        if analysis.asset_id != ecg_source["asset_id"] or analysis.content_hash != ecg_source["content_hash"] or analysis.signal_hash != ecg_source["signal_hash"]:
            raise AIExecutionError("ECG_SOURCE_MISMATCH", "心电候选结果与所选原始波形不一致")
        if processing.input_sample_count != metadata["sample_count"] or processing.input_sample_rate_hz != metadata["sample_rate_hz"] or processing.input_leads != [lead["name"] for lead in metadata["leads"]] or (instructions_digest and processing.instructions_digest != instructions_digest):
            raise AIExecutionError("ECG_PROCESSING_MISMATCH", "心电输入采样、导联顺序或任务Prompt与实际任务不符")
        local = processing.local_runtime
        if local is not None or (model_version and model_version.startswith("ssl-ecg:")):
            if local is None or model_version != "ssl-ecg:" + local.runtime_digest:
                raise AIExecutionError("ECG_RUNTIME_MISMATCH", "本地心电结果缺少所登记实际运行版本，结果已拒收")
            manifest = ECGModelManifest(files={name: {"size": size, "sha256": digest} for name, (size, digest) in RELEASE_FILES.items()})
            if local.model_digest != manifest.digest or local.preprocessing_digest != hashlib.sha256(canonical_json(PREPROCESSING).encode()).hexdigest():
                raise AIExecutionError("ECG_RUNTIME_MISMATCH", "本地心电权重发布或预处理与已审查模型不一致")
            try:
                in_scope = metadata["sample_count"] == 1000 and Decimal(metadata["sample_rate_hz"]) == 100 and set(processing.input_leads) == set(LEADS) and len(processing.input_leads) == 12
            except InvalidOperation:
                in_scope = False
            if not in_scope or processing.used_leads != LEADS or processing.missing_sample_handling != "none_present" or any(lead["missing_samples"] for lead in metadata["leads"]):
                raise AIExecutionError("ECG_LOCAL_SCOPE_MISMATCH", "本地研究模型输入超出原始12导联、100Hz、10秒无缺失范围")
            if [finding.label for finding in analysis.findings] != LABELS or any(finding.location != "recording" or finding.leads != LEADS or finding.score is None or not 0 <= finding.score <= 1 for finding in analysis.findings):
                raise AIExecutionError("ECG_LOCAL_SCORE_MISMATCH", "本地研究模型须保留完整五类整段原始分数，不能改作诊断阈值或局部定位")
        used = {lead["name"]: lead for lead in metadata["leads"] if lead["name"] in processing.used_leads}
        has_missing = any(lead["missing_samples"] for lead in metadata["leads"])
        if has_missing and (processing.missing_sample_handling != "masked" or not processing.preprocessing_notes):
            raise AIExecutionError("ECG_MISSING_SAMPLE_MISMATCH", "原波形含缺失样本，模型须如实报告其处理与适用限制")
        if all(lead["missing_samples"] == metadata["sample_count"] for lead in used.values()):
            raise AIExecutionError("ECG_NO_USABLE_SIGNAL", "模型使用的导联没有可用采样，不能生成候选判读")
        for finding in analysis.findings:
            if not set(finding.leads) <= set(used) or finding.source_id != ecg_source["source_id"]:
                raise AIExecutionError("INVALID_ECG_FINDING", "心电候选引用了未使用的导联或其他原波形")
            if finding.location == "sample_interval" and finding.end_sample_exclusive > metadata["sample_count"]:
                raise AIExecutionError("INVALID_ECG_FINDING", "心电候选的定位超出原始采样范围")
        if result.sections and ecg_source["source_id"] not in cited:
            raise AIExecutionError("UNGROUNDED_ECG_OUTPUT", "心电判读说明未引用所选原始波形")
    return result


def _request(provider: AIProvider, spec: FeatureSpec, task_prompt: str, data: dict) -> tuple[str, dict]:
    endpoint = validate_endpoint(provider.api_base)
    budget = min(provider.max_output_tokens, settings.AI_MAX_OUTPUT_TOKENS)
    instructions = COMMON_SYSTEM_PROMPT + "\n\n" + task_prompt
    if spec.number == 21 and provider.kind != "specialist":
        raise AIExecutionError("AUDIO_ADAPTER_REQUIRED", "医疗录音须通过已登记的专用语音服务处理")
    if spec.number == 37 and provider.kind != "specialist":
        raise AIExecutionError("ECG_ADAPTER_REQUIRED", "原始心电须通过已登记的专用波形模型处理")
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
            "schema_version": {21: "2", 37: "3"}.get(spec.number, "1"),
            "feature_key": spec.key,
            "engine": spec.engine,
            "model": provider.model,
            "instructions": instructions,
            **({"store": False} if spec.number in {21, 37} else {}),
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
    if value.get("schema_version") != {21: "2", 37: "3"}.get(spec.number, "1") or value.get("feature_key") != spec.key or value.get("model_version") != provider.model:
        raise AIExecutionError("ADAPTER_CONTRACT_MISMATCH", "专用模型返回的功能或模型版本与登记信息不一致")
    if value.get("applicable") is not True:
        raise AIExecutionError("OUTSIDE_VALIDATED_SCOPE", "本次输入不在专用模型声明的适用范围内")
    if spec.number in {21, 37}:
        name = "transcription" if spec.number == 21 else "ecg_analysis"
        if not isinstance(value["result"], dict) or name in value["result"]:
            raise ValueError("native result belongs to the versioned envelope")
        usage = value.get("usage") or {}
        return {**value["result"], name: value[name]}, int(usage.get("input_tokens") or 0), int(usage.get("output_tokens") or 0)
    return value["result"], 0, 0


async def generate(
    provider: AIProvider,
    spec: FeatureSpec,
    task_prompt: str,
    data: dict,
    *,
    transport: httpx.AsyncBaseTransport | None = None,
    audio: BinaryIO | None = None,
    ecg: BinaryIO | None = None,
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
    ecg_source = data.get("context", {}).get("ecg_source") if spec.number == 37 else None
    if spec.number == 21:
        if audio is None or not source or source.get("extension") not in AUDIO_FORMATS or source.get("media_type") != AUDIO_FORMATS[source["extension"]][1]:
            raise AIExecutionError("AUDIO_FILE_REQUIRED", "缺少已核实的原录音附件，不能以文字资料冒充语音识别")
        request_body = {"data": {"task": encode_json(payload)}, "files": {"audio": ("recording" + source["extension"], audio, source["media_type"])}}
    elif spec.number == 37:
        if ecg is None or not ecg_source or ecg_source.get("signal_metadata", {}).get("format") != "wfdb16" or audio is not None:
            raise AIExecutionError("ECG_FILE_REQUIRED", "须提供已核实的原始心电采样附件，不能以文字或外部链接代替")
        request_body = {"data": {"task": encode_json(payload)}, "files": {"waveform": ("signal.dat", ecg, "application/octet-stream")}}
    else:
        if audio is not None:
            raise AIExecutionError("UNEXPECTED_AUDIO_FILE", "该任务不接受录音附件")
        request_body = {"json": payload}
    if ecg is not None and spec.number != 37:
        raise AIExecutionError("UNEXPECTED_ECG_FILE", "该任务不接受原始心电附件")
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
        result = validate_generation(output, data.get("evidence", []), spec.requires_knowledge, audio_source=source, ecg_source=ecg_source, instructions_digest=hashlib.sha256(payload.get("instructions", "").encode()).hexdigest(), model_version=provider.model)
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
