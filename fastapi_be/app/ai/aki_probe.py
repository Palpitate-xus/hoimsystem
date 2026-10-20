"""Metadata-only verification of a saved independent AKI service."""

import json
from typing import Literal

import httpx
from fastapi import HTTPException
from pydantic import Field, ValidationError, model_validator

from app.ai.aki_contract import RECIPE, AkiRuntime, canonical_json
from app.ai.aki_model import validate_runtime
from app.ai.gateway import AIExecutionError
from app.ai.governance import provider_credential, validate_endpoint


class AkiCapabilities(AkiRuntime):
    schema_version: Literal["7"]
    feature_key: Literal["aki_risk"]
    recipe: dict
    max_request_bytes: int = Field(strict=True, ge=16384, le=131072)
    timeout_seconds: int = Field(strict=True, ge=1, le=110)

    @model_validator(mode="after")
    def fixed_runtime(self):
        if canonical_json(self.recipe) != canonical_json(RECIPE):
            raise ValueError("AKI能力声明须为完整固定规则")
        validate_runtime({key: getattr(self, key) for key in AkiRuntime.model_fields})
        return self


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("能力声明含重复JSON字段")
        result[key] = value
    return result


async def inspect_aki_capabilities(provider, *, transport=None):
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
                    raise AIExecutionError("AKI_CHECK_HTTP_ERROR", f"AKI能力检查返回HTTP {response.status_code}，请核对地址、独立密钥及服务状态")
                body = bytearray()
                async for chunk in response.aiter_bytes():
                    body.extend(chunk)
                    if len(body) > 16384:
                        raise AIExecutionError("AKI_CHECK_TOO_LARGE", "AKI能力报告超过允许大小")
        return AkiCapabilities.model_validate(json.loads(body, object_pairs_hook=_unique)).model_dump()
    except httpx.HTTPError as exc:
        raise AIExecutionError("AKI_CHECK_UNAVAILABLE", "无法读取AKI服务能力，请核对部署、证书和连接") from exc
    except (ValidationError, ValueError, TypeError, UnicodeError, RecursionError) as exc:
        raise AIExecutionError("AKI_CHECK_INVALID", "AKI能力报告与固定规则、源码或实际运行声明不一致") from exc
