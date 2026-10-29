"""Optional offline ECG classifier settings, independent of hospital database credentials."""

import hashlib
import platform
import sys
from importlib.metadata import version
from pathlib import Path

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.ai.ecg_model import LABELS, LEADS, PREPROCESSING, canonical_json, verify_model

CPU_ENGINE_VERSIONS = {"torch": "2.15.0+cpu", "numpy": "2.5.4", "safetensors": "0.8.0"}
# Historical results keep their recorded engine identity after a runtime upgrade.
HISTORICAL_CPU_ENGINE_VERSIONS = {"torch": "2.14.1+cpu", "numpy": "2.4.4", "safetensors": "0.8.0"}


class ECGSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="ECG_", env_file=None, extra="ignore")
    model_dir: Path
    api_key: SecretStr = Field(validation_alias="AI_PROVIDER_LOCAL_ECG_API_KEY")
    cpu_threads: int = Field(default=4, ge=1, le=16)
    max_bytes: int = Field(default=1048576, ge=1024, le=134217728)
    timeout_seconds: int = Field(default=30, ge=3, le=110)

    @field_validator("model_dir")
    @classmethod
    def absolute_model_directory(cls, value):
        return value.expanduser().resolve()


def runtime_descriptor(config):
    if len(config.api_key.get_secret_value()) < 32:
        raise ValueError("本地心电服务须配置至少32字符的独立密钥")
    manifest = verify_model(config.model_dir)
    versions = {name: version(name) for name in ("torch", "numpy", "safetensors")}
    if versions != CPU_ENGINE_VERSIONS:
        raise ValueError("请使用已固定的可选CPU心电运行依赖")
    preprocessing_digest = hashlib.sha256(canonical_json(PREPROCESSING).encode()).hexdigest()
    code = {name: hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest() for name in ("ecg_model.py", "ecg_network.py", "ecg_worker.py", "ecg_config.py", "ecg_contract.py")}
    identity = {
        "model_digest": manifest.digest,
        "versions": versions,
        "preprocessing_digest": preprocessing_digest,
        "device": "cpu",
        "cpu_threads": config.cpu_threads,
        "implementation": code,
        "python_version": platform.python_version(),
        "machine": platform.machine(),
        "byte_order": sys.byteorder,
    }
    fingerprint = hashlib.sha256(canonical_json(identity).encode()).hexdigest()
    return {
        "schema_version": "3",
        "feature_key": "ecg_analysis",
        "model_version": "ssl-ecg:" + fingerprint,
        "engine": "ssl-ecg-cnn",
        "engine_versions": versions,
        "model_repository": manifest.repository,
        "model_revision": manifest.revision,
        "model_digest": manifest.digest,
        "runtime_digest": fingerprint,
        "preprocessing_digest": preprocessing_digest,
        "required_leads": LEADS,
        "sample_rate_hz": 100,
        "samples_per_lead": 1000,
        "labels": LABELS,
        "missing_sample_policy": "reject",
        "prompt_handling": "signal_only",
        "max_bytes": config.max_bytes,
        "timeout_seconds": config.timeout_seconds,
        "clinical_validation": "not_provided",
    }
