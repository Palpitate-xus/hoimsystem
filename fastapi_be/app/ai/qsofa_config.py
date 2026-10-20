"""Independent qSOFA service settings; never read hospital settings or dotenv."""

import hashlib
import platform
from importlib.metadata import version

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.ai.qsofa_contract import RECIPE, QsofaRuntime, canonical_json, recipe_digest
from app.ai.qsofa_model import implementation_hashes


class QsofaSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="QSOFA_", env_file=None, extra="ignore")
    api_key: SecretStr = Field(validation_alias="AI_PROVIDER_LOCAL_QSOFA_API_KEY")
    max_request_bytes: int = Field(default=131072, ge=16384, le=131072)
    timeout_seconds: int = Field(default=15, ge=1, le=110)


def runtime_descriptor(config=None):
    if config is not None and len(config.api_key.get_secret_value()) < 32:
        raise ValueError("本地qSOFA服务须配置至少32字符的独立密钥")
    identity = {
        "engine": "stdlib-qsofa-rules",
        "rule_id": "qsofa_sepsis3_2016",
        "recipe_digest": recipe_digest(),
        "implementation": implementation_hashes(),
        "python_version": platform.python_version(),
        "engine_versions": {name: version(name) for name in ("fastapi", "pydantic")},
        "prompt_handling": "provenance_only",
        "clinical_validation": "not_provided",
        "population_applicability": "not_independently_verified",
        "independent_implementation": True,
    }
    digest = hashlib.sha256(canonical_json(identity).encode()).hexdigest()
    return {"schema_version": "8", "feature_key": "sepsis_risk", **identity, "runtime_digest": digest, "model_version": "qsofa:" + digest, "recipe": RECIPE, "max_request_bytes": config.max_request_bytes if config else 131072, "timeout_seconds": config.timeout_seconds if config else 15}


def runtime_from_descriptor(descriptor):
    return {key: descriptor[key] for key in QsofaRuntime.model_fields}
