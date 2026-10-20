"""Read a local speech adapter's bounded, typed capabilities without patient data or inference."""

import json

import httpx
from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from app.ai.gateway import AIExecutionError
from app.ai.governance import provider_credential, validate_endpoint


class SpeechCapabilities(BaseModel):
    model_config = ConfigDict(extra="ignore")
    schema_version: str = Field(pattern=r"^2$")
    feature_key: str = Field(pattern=r"^medical_transcription$")
    model_version: str = Field(pattern=r"^fw:[a-f0-9]{64}$")
    engine: str = Field(pattern=r"^faster-whisper$")
    engine_versions: dict[str, str] = Field(min_length=1, max_length=6)
    model_repository: str = Field(pattern=r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$", max_length=160)
    model_revision: str = Field(pattern=r"^[a-f0-9]{40}$")
    model_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    runtime_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    decoding_options_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    language: str = Field(pattern=r"^[a-z]{2,3}$|^auto$")
    max_bytes: int = Field(ge=1024, le=268435456, strict=True)
    max_duration_seconds: int = Field(ge=1, le=3600, strict=True)
    timeout_seconds: int = Field(ge=3, le=110, strict=True)
    prompt_handling: str = Field(pattern=r"^acoustic_only$")
    diarization: bool = Field(strict=True)
    clinical_validation: str = Field(pattern=r"^not_provided$")

    @model_validator(mode="after")
    def known_runtime(self):
        import re

        packages = {"faster-whisper", "ctranslate2", "onnxruntime", "av", "tokenizers", "numpy"}
        if (
            self.model_version != "fw:" + self.runtime_digest
            or self.diarization
            or set(self.engine_versions) != packages
            or any(not re.fullmatch(r"[0-9A-Za-z.+_-]{1,40}", value) for value in self.engine_versions.values())
        ):
            raise ValueError("语音运行版本或处理范围声明不一致")
        return self


async def inspect_speech_capabilities(provider, *, transport=None):
    try:
        endpoint, credential = validate_endpoint(provider.api_base), provider_credential(provider)
    except HTTPException as exc:
        raise AIExecutionError("PROVIDER_CONFIGURATION", str(exc.detail)) from exc
    headers = {"Accept": "application/json"}
    if credential:
        headers["Authorization"] = "Bearer " + credential
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(10, connect=3), follow_redirects=False, trust_env=False, transport=transport) as client:
            async with client.stream("GET", endpoint + "/capabilities", headers=headers) as response:
                if response.status_code != 200:
                    raise AIExecutionError("SPEECH_CHECK_HTTP_ERROR", f"语音服务检查返回HTTP {response.status_code}，请核对地址、密钥和部署状态")
                body = bytearray()
                async for chunk in response.aiter_bytes():
                    body.extend(chunk)
                    if len(body) > 16384:
                        raise AIExecutionError("SPEECH_CHECK_TOO_LARGE", "语音服务能力报告超过允许大小")
        return SpeechCapabilities.model_validate(json.loads(body)).model_dump()
    except httpx.HTTPError as exc:
        raise AIExecutionError("SPEECH_CHECK_UNAVAILABLE", "无法读取语音服务能力，请检查部署、证书及连接") from exc
    except (ValidationError, ValueError, TypeError, UnicodeError) as exc:
        raise AIExecutionError("SPEECH_CHECK_INVALID", "语音服务能力报告与本地识别契约不一致") from exc
