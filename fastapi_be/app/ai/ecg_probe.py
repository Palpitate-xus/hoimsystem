"""Inspect a saved local ECG service without sending signals or approving clinical use."""

import json
import re
from typing import Literal

import httpx
from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from app.ai.gateway import AIExecutionError
from app.ai.governance import provider_credential, validate_endpoint


class ECGCapabilities(BaseModel):
    model_config = ConfigDict(extra="ignore")
    schema_version: Literal["3"]
    feature_key: Literal["ecg_analysis"]
    model_version: str = Field(pattern=r"^ssl-ecg:[a-f0-9]{64}$")
    engine: Literal["ssl-ecg-cnn"]
    engine_versions: dict[str, str] = Field(min_length=3, max_length=3)
    model_repository: Literal["Tumo505/SSL-ECG-Classification-model-card"]
    model_revision: str = Field(pattern=r"^[a-f0-9]{40}$")
    model_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    runtime_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    preprocessing_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    required_leads: list[str] = Field(min_length=12, max_length=12)
    sample_rate_hz: int = Field(ge=100, le=100, strict=True)
    samples_per_lead: int = Field(ge=1000, le=1000, strict=True)
    labels: list[str] = Field(min_length=5, max_length=5)
    missing_sample_policy: Literal["reject"]
    prompt_handling: Literal["signal_only"]
    max_bytes: int = Field(ge=1024, le=134217728, strict=True)
    timeout_seconds: int = Field(ge=3, le=110, strict=True)
    clinical_validation: Literal["not_provided"]

    @model_validator(mode="after")
    def known_runtime(self):
        if (
            self.model_version != "ssl-ecg:" + self.runtime_digest
            or set(self.engine_versions) != {"torch", "numpy", "safetensors"}
            or any(not re.fullmatch(r"[0-9A-Za-z.+_-]{1,40}", value) for value in self.engine_versions.values())
            or self.required_leads != ["I", "II", "III", "aVR", "aVL", "aVF", "V1", "V2", "V3", "V4", "V5", "V6"]
            or self.labels != ["NORM", "CD", "HYP", "MI", "STTC"]
        ):
            raise ValueError("心电运行版本、导联或分类声明不一致")
        return self


async def inspect_ecg_capabilities(provider, *, transport=None):
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
                    raise AIExecutionError("ECG_CHECK_HTTP_ERROR", f"心电服务检查返回HTTP {response.status_code}，请核对地址、密钥和部署状态")
                body = bytearray()
                async for chunk in response.aiter_bytes():
                    body.extend(chunk)
                    if len(body) > 16384:
                        raise AIExecutionError("ECG_CHECK_TOO_LARGE", "心电服务能力报告超过允许大小")
        return ECGCapabilities.model_validate(json.loads(body)).model_dump()
    except httpx.HTTPError as exc:
        raise AIExecutionError("ECG_CHECK_UNAVAILABLE", "无法读取心电服务能力，请检查部署、证书及连接") from exc
    except (ValidationError, ValueError, TypeError, UnicodeError) as exc:
        raise AIExecutionError("ECG_CHECK_INVALID", "心电服务能力报告与本地分类契约不一致") from exc
