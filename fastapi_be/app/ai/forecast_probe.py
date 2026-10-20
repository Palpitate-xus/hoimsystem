"""Inspect a saved statistical adapter without sending series or running forecasts."""

import json
from typing import Annotated, Literal

import httpx
from fastapi import HTTPException
from pydantic import ConfigDict, Field, ValidationError, model_validator

from app.ai.forecast_contract import ForecastRuntime
from app.ai.forecast_model import validate_runtime
from app.ai.gateway import AIExecutionError
from app.ai.governance import provider_credential, validate_endpoint


class ForecastCapabilities(ForecastRuntime):
    """Only the reviewed recipe and explicitly bounded deployment are supported."""

    model_config = ConfigDict(extra="ignore")
    schema_version: Literal["5"]
    feature_key: Literal["visit_forecast"]
    history_min_days: Literal[112]
    history_max_days: Literal[366]
    horizon_days: list[Annotated[int, Field(strict=True)]] = Field(min_length=2, max_length=2)
    backtest_origins: Literal[28]
    nominal_coverage: Literal[0.9]
    max_request_bytes: int = Field(strict=True, ge=16384, le=131072)
    timeout_seconds: int = Field(strict=True, ge=1, le=110)

    @model_validator(mode="after")
    def fixed_contract(self):
        if self.horizon_days != [7, 14] or any(type(item) is not int for item in self.horizon_days):
            raise ValueError("服务须明确支持原7/14日固定预测跨度")
        identity = ForecastRuntime.model_validate({key: getattr(self, key) for key in ForecastRuntime.model_fields})
        validate_runtime(identity)
        return self


async def inspect_forecast_capabilities(provider, *, transport=None):
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
                    raise AIExecutionError("FORECAST_CHECK_HTTP_ERROR", f"统计服务检查返回HTTP {response.status_code}，请核对地址、密钥和部署状态")
                body = bytearray()
                async for chunk in response.aiter_bytes():
                    body.extend(chunk)
                    if len(body) > 16384:
                        raise AIExecutionError("FORECAST_CHECK_TOO_LARGE", "统计服务能力报告超过允许大小")
        return ForecastCapabilities.model_validate(json.loads(body)).model_dump()
    except httpx.HTTPError as exc:
        raise AIExecutionError("FORECAST_CHECK_UNAVAILABLE", "无法读取统计服务能力，请检查部署、证书及连接") from exc
    except (ValidationError, ValueError, TypeError, UnicodeError) as exc:
        raise AIExecutionError("FORECAST_CHECK_INVALID", "统计服务能力报告与固定预测算法、实际运行版本或处理范围不一致") from exc
