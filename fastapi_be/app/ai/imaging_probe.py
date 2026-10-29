"""Inspect saved chest-image runtime declarations without sending pixels or approving care."""

import hashlib
import json
from typing import Any, Literal

import httpx
from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from app.ai.gateway import AIExecutionError
from app.ai.governance import provider_credential, validate_endpoint
from app.ai.imaging_config import CPU_ENGINE_VERSIONS, HISTORICAL_CPU_ENGINE_VERSIONS
from app.ai.imaging_model import LABELS, RELEASE_FILES, ImagingModelManifest, canonical_json


class ImagingCapabilities(BaseModel):
    model_config = ConfigDict(extra="ignore")
    schema_version: Literal["4"]
    feature_key: Literal["imaging_detection"]
    model_version: str = Field(pattern=r"^xrv:[a-f0-9]{64}$")
    engine: Literal["torchxrayvision-densenet121"]
    engine_versions: dict[str, str] = Field(min_length=3, max_length=3)
    model_repository: Literal["torchxrayvision/densenet121-res224-all"]
    model_revision: Literal["588eadcc6a744da71f8dce768bc974ec629443f5"]
    model_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    runtime_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    preprocessing_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    preprocessing: dict[str, Any]
    profile: Literal["xrv_stored_range_v1"]
    labels: list[str] = Field(min_length=18, max_length=18)
    prompt_handling: Literal["pixels_only"]
    clinical_validation: Literal["not_provided"]
    population_applicability: Literal["not_verified"]
    max_bytes: int = Field(ge=1024, le=67108864, strict=True)
    timeout_seconds: int = Field(ge=3, le=110, strict=True)

    @model_validator(mode="after")
    def known_runtime_and_preprocessing(self):
        from app.ai.imaging_preprocessing import PREPROCESSING

        manifest = ImagingModelManifest(files={name: {"size": size, "sha256": value} for name, (size, value) in RELEASE_FILES.items()})
        if (
            self.model_version != "xrv:" + self.runtime_digest
            or self.engine_versions not in (CPU_ENGINE_VERSIONS, HISTORICAL_CPU_ENGINE_VERSIONS)
            or self.model_digest != manifest.digest
            or self.labels != LABELS
            or canonical_json(self.preprocessing) != canonical_json(PREPROCESSING)
            or self.preprocessing_digest != hashlib.sha256(canonical_json(PREPROCESSING).encode()).hexdigest()
        ):
            raise ValueError("影像研究模型的固定权重、实际版本、原标签或预处理声明不一致")
        return self


async def inspect_imaging_capabilities(provider, *, transport=None):
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
                    raise AIExecutionError("IMAGE_CHECK_HTTP_ERROR", f"影像服务检查返回HTTP {response.status_code}，请核对地址、密钥和部署状态")
                body = bytearray()
                async for chunk in response.aiter_bytes():
                    body.extend(chunk)
                    if len(body) > 16384:
                        raise AIExecutionError("IMAGE_CHECK_TOO_LARGE", "影像服务能力报告超过允许大小")
        return ImagingCapabilities.model_validate(json.loads(body)).model_dump()
    except httpx.HTTPError as exc:
        raise AIExecutionError("IMAGE_CHECK_UNAVAILABLE", "无法读取影像服务能力，请检查部署、证书及连接") from exc
    except (ValidationError, ValueError, TypeError, UnicodeError) as exc:
        raise AIExecutionError("IMAGE_CHECK_INVALID", "影像服务能力报告与固定模型和预处理契约不一致") from exc
