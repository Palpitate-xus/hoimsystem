"""Small offline statistics service settings; no hospital database or model weights."""

import hashlib
import platform
from importlib.metadata import version

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.ai.forecast_contract import RECIPE, canonical_json
from app.ai.forecast_model import implementation_hashes


class ForecastSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="FORECAST_", env_file=None, extra="ignore")
    api_key: SecretStr = Field(validation_alias="AI_PROVIDER_LOCAL_FORECAST_API_KEY")
    max_request_bytes: int = Field(default=131072, ge=16384, le=131072)
    timeout_seconds: int = Field(default=30, ge=3, le=110)


def runtime_descriptor(config=None):
    if config is not None and len(config.api_key.get_secret_value()) < 32:
        raise ValueError("本地统计服务须配置至少32字符的独立密钥")
    identity = {
        "engine": "stdlib-statistical-forecast",
        "recipe": "weekday_mean_4w",
        "recipe_digest": hashlib.sha256(canonical_json(RECIPE).encode()).hexdigest(),
        "implementation": implementation_hashes(),
        "python_version": platform.python_version(),
        "engine_versions": {name: version(name) for name in ("fastapi", "pydantic")},
        "prompt_handling": "provenance_only",
        "clinical_validation": "not_provided",
        "operational_validation": "not_provided",
        "coverage_guarantee": "not_provided",
    }
    digest = hashlib.sha256(canonical_json(identity).encode()).hexdigest()
    return {
        "schema_version": "5",
        "feature_key": "visit_forecast",
        **identity,
        "runtime_digest": digest,
        "model_version": "stat-forecast:" + digest,
        "history_min_days": 112,
        "history_max_days": 366,
        "horizon_days": [7, 14],
        "backtest_origins": 28,
        "nominal_coverage": 0.9,
        "max_request_bytes": config.max_request_bytes if config else 131072,
        "timeout_seconds": config.timeout_seconds if config else 30,
    }


def runtime_from_descriptor(descriptor):
    return {
        key: descriptor[key]
        for key in (
            "engine",
            "recipe",
            "recipe_digest",
            "implementation",
            "python_version",
            "engine_versions",
            "runtime_digest",
            "model_version",
            "prompt_handling",
            "clinical_validation",
            "operational_validation",
            "coverage_guarantee",
        )
    }
