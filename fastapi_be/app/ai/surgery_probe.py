"""Read authenticated surgery optimizer metadata without cases or solving."""

import json
from typing import Literal

import httpx
from fastapi import HTTPException
from pydantic import Field, ValidationError, field_validator, model_validator

from app.ai.gateway import AIExecutionError
from app.ai.governance import provider_credential, validate_endpoint
from app.ai.surgery_contract import INPUT_POLICY, MAX_BYTES, RECIPE, SurgeryRuntime, canonical_json
from app.ai.surgery_model import validate_runtime

MAX_REPORT_BYTES = 65536


class SurgeryCapabilities(SurgeryRuntime):
    schema_version: Literal["12"]
    feature_key: Literal["surgery_scheduling"]
    rule_id: Literal["surgery_declared_stage_resources_v1"]
    recipe: dict
    input_policy: dict
    independent_implementation: Literal[True]
    max_request_bytes: int = Field(strict=True, ge=65536, le=MAX_BYTES)
    max_response_bytes: int = Field(strict=True, ge=MAX_BYTES, le=MAX_BYTES)
    timeout_seconds: int = Field(strict=True, ge=1, le=110)
    scope: Literal["declared_case_and_shared_resource_pool"]
    candidate_only: Literal[True]
    automatic_booking: Literal[False]

    @field_validator("independent_implementation", "candidate_only", mode="before")
    @classmethod
    def actual_boolean(cls, value):
        if value is not True:
            raise ValueError("Capability guarantees require actual boolean true")
        return value

    @model_validator(mode="after")
    def complete_fixed_runtime(self):
        if canonical_json(self.recipe) != canonical_json(RECIPE) or canonical_json(self.input_policy) != canonical_json(INPUT_POLICY):
            raise ValueError("Complete fixed declared-stage surgery recipe and input policy differ")
        validate_runtime({key: getattr(self, key) for key in SurgeryRuntime.model_fields})
        return self


def _unique(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("Duplicate capability keys are not accepted")
        value[key] = item
    return value


def _finite(_):
    raise ValueError("Nonfinite capability numbers are not accepted")


async def inspect_surgery_capabilities(provider, *, transport=None):
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
                    raise AIExecutionError("SURGERY_CHECK_HTTP_ERROR", f"手术排程能力检查返回HTTP {response.status_code}，请核对地址、独立密钥及服务状态")
                body = bytearray()
                async for chunk in response.aiter_bytes():
                    if len(body) + len(chunk) > MAX_REPORT_BYTES:
                        raise AIExecutionError("SURGERY_CHECK_TOO_LARGE", "手术排程能力报告超过允许大小")
                    body.extend(chunk)
        return SurgeryCapabilities.model_validate(json.loads(body, object_pairs_hook=_unique, parse_constant=_finite)).model_dump()
    except httpx.InvalidURL as exc:
        raise AIExecutionError("PROVIDER_CONFIGURATION", "手术排程模型地址格式无效，请核对已登记的服务地址") from exc
    except httpx.HTTPError as exc:
        raise AIExecutionError("SURGERY_CHECK_UNAVAILABLE", "无法读取手术排程服务能力，请核对部署、证书和连接") from exc
    except (ValidationError, ValueError, TypeError, UnicodeError, RecursionError) as exc:
        raise AIExecutionError("SURGERY_CHECK_INVALID", "手术排程能力报告与固定规则、完整核心文件或实际运行声明不一致") from exc
