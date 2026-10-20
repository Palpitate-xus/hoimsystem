"""Independent SOFA service settings; no hospital configuration or dotenv."""

import platform
from importlib.metadata import version

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.ai.sofa_contract import INPUT_POLICY, MAX_REQUEST_BYTES, RECIPE, SofaRuntime, hash_content, policy_digest, recipe_digest
from app.ai.sofa_model import implementation_hashes


class SofaSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="SOFA_", env_file=None, extra="ignore")
    api_key: SecretStr = Field(validation_alias="AI_PROVIDER_LOCAL_SOFA_API_KEY")
    max_request_bytes: int = Field(default=MAX_REQUEST_BYTES, ge=65536, le=MAX_REQUEST_BYTES)
    timeout_seconds: int = Field(default=60, ge=1, le=110)


def runtime_descriptor(config=None):
    if config is not None and len(config.api_key.get_secret_value()) < 32:
        raise ValueError("本地SOFA服务须配置至少32字符独立密钥")
    identity = {
        "engine": "hoim_sofa1_native_independent",
        "recipe_digest": recipe_digest(),
        "policy_digest": policy_digest(),
        "python_version": platform.python_version(),
        "fastapi_version": version("fastapi"),
        "pydantic_version": version("pydantic"),
        "core_sha256": implementation_hashes(),
        "independent_implementation": True,
        "clinical_validation": "not_provided",
    }
    digest = hash_content(identity)
    return {
        "schema_version": "9",
        "feature_key": "sepsis_risk",
        "rule_id": "sofa1_native_observed_v1",
        **identity,
        "runtime_digest": digest,
        "model_version": "sofa1:" + digest,
        "recipe": RECIPE,
        "input_policy": INPUT_POLICY,
        "max_request_bytes": config.max_request_bytes if config else MAX_REQUEST_BYTES,
        "max_response_bytes": MAX_REQUEST_BYTES,
        "timeout_seconds": config.timeout_seconds if config else 60,
        "prompt_handling": "provenance_only",
        "population_applicability": "not_independently_verified",
    }


def runtime_from_descriptor(descriptor):
    return {key: descriptor[key] for key in SofaRuntime.model_fields}
