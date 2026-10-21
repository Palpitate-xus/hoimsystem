"""Authenticate standalone supply metadata without reading stock or forecasting."""

import json
from typing import Literal

import httpx
from fastapi import HTTPException
from pydantic import Field, ValidationError, field_validator, model_validator

from app.ai.gateway import AIExecutionError
from app.ai.governance import provider_credential, validate_endpoint
from app.ai.supply_contract import INPUT_POLICY, MAX_BYTES, RECIPE, SupplyRuntime, canonical_json
from app.ai.supply_model import validate_runtime

MAX_REPORT_BYTES = 65536


class SupplyCapabilities(SupplyRuntime):
    schema_version: Literal["13"]
    feature_key: Literal["supply_forecast"]
    rule_id: Literal["supply_recorded_quantity_v1"]
    recipe: dict
    input_policy: dict
    independent_implementation: Literal[True]
    max_request_bytes: int = Field(strict=True, ge=65536, le=MAX_BYTES)
    max_response_bytes: int = Field(strict=True, ge=MAX_BYTES, le=MAX_BYTES)
    timeout_seconds: int = Field(strict=True, ge=1, le=110)
    scope: Literal["single_sku_single_scope_recorded_requests_issues_consumption"]
    forecast_only: Literal[True]

    @field_validator("independent_implementation", "forecast_only", mode="before")
    @classmethod
    def actual_boolean(cls, value):
        if value is not True:
            raise ValueError("Capability guarantees require actual boolean true")
        return value

    @model_validator(mode="after")
    def complete_fixed_runtime(self):
        if canonical_json(self.recipe) != canonical_json(RECIPE) or canonical_json(self.input_policy) != canonical_json(INPUT_POLICY):
            raise ValueError("Complete fixed supply recipe and input policy differ")
        validate_runtime({key: getattr(self, key) for key in SupplyRuntime.model_fields})
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


async def inspect_supply_capabilities(provider, *, transport=None):
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
                    raise AIExecutionError("SUPPLY_CHECK_HTTP_ERROR", f"物资预测能力检查返回HTTP {response.status_code}，请核对地址、独立密钥及服务状态")
                body = bytearray()
                async for chunk in response.aiter_bytes():
                    if len(body) + len(chunk) > MAX_REPORT_BYTES:
                        raise AIExecutionError("SUPPLY_CHECK_TOO_LARGE", "物资预测能力报告超过允许大小")
                    body.extend(chunk)
        return SupplyCapabilities.model_validate(json.loads(body, object_pairs_hook=_unique, parse_constant=_finite)).model_dump()
    except httpx.InvalidURL as exc:
        raise AIExecutionError("PROVIDER_CONFIGURATION", "物资预测模型地址格式无效，请核对已登记的服务地址") from exc
    except httpx.HTTPError as exc:
        raise AIExecutionError("SUPPLY_CHECK_UNAVAILABLE", "无法读取物资预测服务能力，请核对部署、证书和连接") from exc
    except (ValidationError, ValueError, TypeError, UnicodeError, RecursionError) as exc:
        raise AIExecutionError("SUPPLY_CHECK_INVALID", "物资预测能力报告与固定配方、完整核心文件或实际运行声明不一致") from exc
